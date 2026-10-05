"""Copy objects from S3 into a Unity Catalog volume. Never writes tables.

A config is used only when it has an s3_copy block. Files land under
/Volumes/<catalog>/<schema>/<volume>/<source_table>/ and Auto Loader reads
that folder. A file already in the volume with the same size is skipped.
"""

import fnmatch
import glob
import os

import yaml


def get_secret(scope, key):
    try:
        from pyspark.dbutils import DBUtils
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        return DBUtils(spark).secrets.get(scope=scope, key=key)
    except Exception:
        env_key = f"{scope}__{key}".upper().replace("-", "_")
        value = os.environ.get(env_key)
        if value is None:
            raise RuntimeError(
                f"Secret {scope}/{key} not found via dbutils, and env var "
                f"{env_key} is not set for local fallback."
            )
        return value


def load_copy_configs(config_dir):
    configs = []
    for path in sorted(glob.glob(os.path.join(config_dir, "*.yml"))):
        if os.path.basename(path).startswith("_"):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        if isinstance(data, list):
            data = data[0] if data else {}
        if isinstance(data, dict) and data.get("s3_copy"):
            configs.append((os.path.basename(path), data))
    return configs


def _split_volume(name):
    parts = str(name).split(".")
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"s3_copy.volume must be catalog.schema.volume, got {name!r}")
    return parts


def target_dir(cfg):
    catalog, schema, volume = _split_volume(cfg["s3_copy"]["volume"])
    return f"/Volumes/{catalog}/{schema}/{volume}/{cfg['source_table']}"


def validate(filename, cfg):
    copy = cfg["s3_copy"]
    for field in ("bucket", "region", "volume", "secret_scope",
                  "access_key_secret", "secret_key_secret"):
        if not copy.get(field):
            raise ValueError(f"[{filename}] s3_copy.{field} is required")
    if not cfg.get("source_table"):
        raise ValueError(f"[{filename}] source_table is required")
    expected = target_dir(cfg).rstrip("/")
    actual = str(cfg.get("source_path") or "").rstrip("/")
    if actual != expected:
        raise ValueError(
            f"[{filename}] source_path must be {expected}/ so Auto Loader reads "
            f"the copied files, got {cfg.get('source_path')!r}"
        )


def build_s3_client(copy):
    import boto3

    return boto3.client(
        "s3",
        region_name=copy["region"],
        aws_access_key_id=get_secret(copy["secret_scope"], copy["access_key_secret"]),
        aws_secret_access_key=get_secret(copy["secret_scope"], copy["secret_key_secret"]),
    )


def copy_source(cfg, s3_client, spark):
    copy = cfg["s3_copy"]
    catalog, schema, volume = _split_volume(copy["volume"])
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}`")
    spark.sql(f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`{schema}`.`{volume}`")

    destination = target_dir(cfg)
    os.makedirs(destination, exist_ok=True)

    prefix = copy.get("prefix") or ""
    pattern = copy.get("file_name_pattern") or "*"
    copied = 0
    skipped = 0

    pages = s3_client.get_paginator("list_objects_v2").paginate(
        Bucket=copy["bucket"], Prefix=prefix
    )
    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            if not fnmatch.fnmatch(key.rsplit("/", 1)[-1], pattern):
                continue
            relative = key[len(prefix):] if key.startswith(prefix) else key
            target = os.path.join(destination, relative.lstrip("/").replace("/", "__"))
            if os.path.exists(target) and os.path.getsize(target) == obj["Size"]:
                skipped += 1
                continue
            # Direct binary stream from S3 into target volume path (16 MB chunks)
            # Eliminates driver /tmp disk buffering per INGESTION_STRATEGY_FACT_TABLES.md
            response = s3_client.get_object(Bucket=copy["bucket"], Key=key)
            with open(target, "wb") as f_out:
                for chunk in response["Body"].iter_chunks(chunk_size=16 * 1024 * 1024):
                    f_out.write(chunk)
            copied += 1
    return copied, skipped


def run(config_dir):
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()
    configs = load_copy_configs(config_dir)
    if not configs:
        raise ValueError(f"No configs with an s3_copy block in {config_dir}")
    for filename, cfg in configs:
        validate(filename, cfg)
    for filename, cfg in configs:
        client = build_s3_client(cfg["s3_copy"])
        copied, skipped = copy_source(cfg, client, spark)
        print(f"{filename}: copied={copied} skipped={skipped} into {target_dir(cfg)}")
