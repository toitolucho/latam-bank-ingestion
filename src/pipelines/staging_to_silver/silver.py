"""
silver.py
================================================================================
Config-Driven Silver Layer — Lakeflow Spark Declarative Pipelines
================================================================================

PURPOSE: Reads typed bronze tables, applies SCD Type 2 via apply_changes.
         A YAML is used only when it has scd_2_key_list.

PIPELINE: staging_to_silver
================================================================================
"""

import os
import re
import sys
import glob
import yaml
from pyspark import pipelines as dp
from pyspark.sql import functions as F


# ─────────────────────────────────────────────────────────────────────────────
# Make utilities importable
# ─────────────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = spark.conf.get("pipeline.project_root")

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.utilities.schema_parser import get_bit_column_names


# ─────────────────────────────────────────────────────────────────────────────
# Config folder scan
# ─────────────────────────────────────────────────────────────────────────────

_CONFIG_DIR = spark.conf.get(
    "pipeline.config_dir",
    os.path.join(_PROJECT_ROOT, "src", "configs"),
)
_SCHEMA_DIR = os.path.join(_PROJECT_ROOT, "src", "utilities")

if not os.path.isdir(_CONFIG_DIR):
    raise FileNotFoundError(
        f"Config directory not found: '{_CONFIG_DIR}'."
    )

_YAML_FILES = sorted(glob.glob(os.path.join(_CONFIG_DIR, "*.yml")))

if not _YAML_FILES:
    raise FileNotFoundError(
        f"No .yml files found in '{_CONFIG_DIR}'."
    )

def _load_source(path: str) -> dict:
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    if isinstance(data, list):
        return data[0]
    return data

_SOURCES_ALL = [_load_source(f) for f in _YAML_FILES]

# pipeline_group filter ─────────────────────────────────────────────────────
_TABLE_GROUP = spark.conf.get("pipeline.table_group", None)

if _TABLE_GROUP:
    _SOURCES  = [s for s in _SOURCES_ALL if s.get("pipeline_group") == _TABLE_GROUP]
    _YAML_FILES = [f for f, s in zip(_YAML_FILES, _SOURCES_ALL)
                   if s.get("pipeline_group") == _TABLE_GROUP]
    if not _SOURCES:
        raise ValueError(
            f"pipeline.table_group='{_TABLE_GROUP}' matched no configs in '{_CONFIG_DIR}'."
        )
else:
    _SOURCES = [s for s in _SOURCES_ALL if not s.get("pipeline_group")]
    _YAML_FILES = [f for f, s in zip(_YAML_FILES, _SOURCES_ALL)
                   if not s.get("pipeline_group")]

def _config_label(src: dict) -> str:
    if src.get("source_table"):
        return src["source_table"]
    source = src.get("source")
    if isinstance(source, dict) and source.get("name"):
        return source["name"]
    return "<unnamed>"


# Skip stub configs not yet configured for silver (empty scd_2_key_list) ─────
_pairs   = [(s, f) for s, f in zip(_SOURCES, _YAML_FILES) if s.get("scd_2_key_list")]
_skipped = [_config_label(s) for s in _SOURCES if not s.get("scd_2_key_list")]
if _skipped:
    _preview = _skipped[:5]
    _suffix  = f" ... +{len(_skipped)-5} more" if len(_skipped) > 5 else ""
    print(f"INFO: {len(_skipped)} config(s) skipped (no scd_2_key_list): {_preview}{_suffix}")
if _pairs:
    _SOURCES, _YAML_FILES = map(list, zip(*_pairs))
else:
    _SOURCES, _YAML_FILES = [], []

# Normalize scd_2_key_list to list
for _s in _SOURCES:
    _keys = _s.get("scd_2_key_list")
    if isinstance(_keys, str):
        _s["scd_2_key_list"] = [k.strip() for k in _keys.split(",") if k.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Catalog override
# ─────────────────────────────────────────────────────────────────────────────

_CATALOG = spark.conf.get("pipeline.catalog", None)

if _CATALOG:
    for _s in _SOURCES:
        _s["source_catalog"] = _CATALOG
        _s["target_catalog_prefix"] = _CATALOG


# ─────────────────────────────────────────────────────────────────────────────
# Schema defaults
# ─────────────────────────────────────────────────────────────────────────────

for _s in _SOURCES:
    _sor = _s.get("sor", "latam_bank")
    _s.setdefault("source_catalog", _CATALOG)
    _s.setdefault("source_schema", f"bronze_{_sor}")
    _s.setdefault("target_catalog_prefix", _CATALOG)
    _s.setdefault("target_schema", f"silver_{_sor}")


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────

def _validate_sources(sources: list, yaml_files: list):
    seen_names = set()
    for src, filepath in zip(sources, yaml_files):
        filename = os.path.basename(filepath)
        name     = src.get("source_table", "<unnamed>")
        if not src.get("source_table"):
            raise ValueError(f"[{filename}] Missing required field 'source_table'.")
        if name in seen_names:
            raise ValueError(f"[{filename}] Duplicate source_table '{name}'.")
        seen_names.add(name)
        if not src.get("source_catalog"):
            raise ValueError(f"[{filename}] Missing 'source_catalog' for '{name}'.")
        if not src.get("source_schema"):
            raise ValueError(f"[{filename}] Missing 'source_schema' for '{name}'.")
        if not src.get("target_catalog_prefix"):
            raise ValueError(f"[{filename}] Missing 'target_catalog_prefix' for '{name}'.")
        if not src.get("target_schema"):
            raise ValueError(f"[{filename}] Missing 'target_schema' for '{name}'.")
        if not src.get("scd_2_key_list"):
            raise ValueError(f"[{filename}] Missing 'scd_2_key_list' for '{name}'.")

_validate_sources(_SOURCES, _YAML_FILES)


# ─────────────────────────────────────────────────────────────────────────────
# Filter out configs whose source (bronze) table does not exist yet
# ─────────────────────────────────────────────────────────────────────────────

def _get_existing_source_tables() -> set:
    schema_groups = {}
    for s in _SOURCES:
        key = (s["source_catalog"], s["source_schema"])
        schema_groups.setdefault(key, [])
    existing = set()
    for (cat, sch) in schema_groups:
        try:
            rows = spark.sql(
                f"SELECT table_name FROM `{cat}`.information_schema.tables "
                f"WHERE table_schema = '{sch}'"
            ).collect()
            for row in rows:
                existing.add((cat, sch, row.table_name))
        except Exception as e:
            print(f"WARN: Could not query information_schema for {cat}.{sch}: {e}")
    return existing

_EXISTING_SOURCES = _get_existing_source_tables()

if _EXISTING_SOURCES:
    def _source_table_exists(src: dict) -> bool:
        return (src["source_catalog"], src["source_schema"], src["source_table"]) in _EXISTING_SOURCES

    _pairs_exist = [(s, f) for s, f in zip(_SOURCES, _YAML_FILES) if _source_table_exists(s)]
    _skipped_missing = [s["source_table"] for s in _SOURCES if not _source_table_exists(s)]

    if _skipped_missing:
        _preview = _skipped_missing[:10]
        _suffix = f" ... +{len(_skipped_missing)-10} more" if len(_skipped_missing) > 10 else ""
        print(f"INFO: {len(_skipped_missing)} config(s) skipped (source table not found): {_preview}{_suffix}")

    if _pairs_exist:
        _SOURCES, _YAML_FILES = map(list, zip(*_pairs_exist))
    else:
        _SOURCES, _YAML_FILES = [], []
else:
    print("WARN: information_schema query returned empty; bypassing source table filter.")


# ─────────────────────────────────────────────────────────────────────────────
# Stream helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_table_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "", name)

def _normalize_column_name(name: str) -> str:
    return name

def _silver_col_name(col_def: dict) -> str:
    return col_def.get("rename") or col_def["name"]


def _translate_expr_columns(expr: str, rename_map: dict) -> str:
    for from_name, to_name in sorted(rename_map.items(), key=lambda x: -len(x[0])):
        expr = expr.replace(f"`{from_name}`", f"`{to_name}`")
        expr = re.sub(rf"\b{re.escape(from_name)}\b", f"`{to_name}`", expr)
    return expr


def _translate_expr_to_bronze(expr: str, silver_columns: list) -> str:
    reverse_rename = {}
    for c in (silver_columns or []):
        bronze_name = c["name"]
        silver_name = _silver_col_name(c)
        if silver_name != bronze_name:
            reverse_rename[silver_name] = bronze_name
    return _translate_expr_columns(expr, reverse_rename)


def _apply_common_transforms(df, src: dict, include_sequencing: bool = True):
    silver_cols_cfg = src.get("silver_columns") or []

    dq_rules = src.get("data_quality_rules") or []
    if dq_rules:
        combined_expr = " AND ".join(
            f"(({_translate_expr_to_bronze(r['expr'], silver_cols_cfg)}) IS NOT FALSE)"
            for r in dq_rules
        )
        df = df.filter(F.expr(combined_expr))

    rename_map = {}
    for col_def in silver_cols_cfg:
        bronze_name = col_def["name"]
        silver_name = _silver_col_name(col_def)
        if silver_name != bronze_name:
            rename_map[bronze_name] = silver_name

    for orig, final in rename_map.items():
        df = df.withColumnRenamed(orig, final)

    if silver_cols_cfg:
        allow_missing = bool(src.get("allow_missing_columns", False))
        if allow_missing:
            existing = set(df.columns)
            select_exprs = []
            for c in silver_cols_cfg:
                user_silver = _silver_col_name(c)
                if user_silver in existing:
                    select_exprs.append(F.col(user_silver))
                else:
                    select_exprs.append(F.lit(None).cast("string").alias(user_silver))
            df = df.select(*select_exprs)
        else:
            df = df.select(*[_silver_col_name(c) for c in silver_cols_cfg])

    for col in (src.get("exclude_columns") or []):
        if col in df.columns:
            df = df.drop(col)

    bit_cols = get_bit_column_names(src["source_table"], schema_dir=_SCHEMA_DIR)
    for bit_col in bit_cols:
        silver_name = rename_map.get(bit_col, bit_col)
        if silver_name in df.columns:
            df = df.withColumn(silver_name, F.col(silver_name).cast("boolean"))

    if include_sequencing:
        scd_seq = src.get("history_timestamp_source") or "pipeline_timestamp"
        if scd_seq == "pipeline_timestamp":
            pass
        elif isinstance(scd_seq, list):
            ts_format = src["history_timestamp_format"]
            silver_seq_cols = [rename_map.get(c, c) for c in scd_seq]
            df = df.withColumn(
                "_scd_sequence_ts",
                F.to_timestamp(
                    F.concat_ws(" ", *[F.col(c).cast("string") for c in silver_seq_cols]),
                    ts_format
                )
            )
        else:
            silver_col = rename_map.get(scd_seq, scd_seq)
            ts_format = src.get("history_timestamp_format")
            if ts_format:
                df = df.withColumn(silver_col, F.to_timestamp(F.col(silver_col), ts_format))

    return df


def _build_silver_stream(src: dict):
    bronze_fqn = f"{src['source_catalog']}.{src['source_schema']}.{src['source_table']}"
    df = spark.readStream.table(bronze_fqn)
    return _apply_common_transforms(df, src, include_sequencing=True)


def _build_quarantine_stream(src: dict):
    bronze_fqn = f"{src['source_catalog']}.{src['source_schema']}.{src['source_table']}"
    df = spark.readStream.option("skipChangeCommits", "true").table(bronze_fqn)

    silver_cols_cfg = src.get("silver_columns") or []
    rules           = src.get("data_quality_rules") or []
    failed_exprs    = [
        F.when(
            ~F.expr(_translate_expr_to_bronze(rule["expr"], silver_cols_cfg)),
            F.lit(rule["description"])
        )
        for rule in rules
    ]

    df = (
        df
        .withColumn("_failed_dq_rules",     F.array_compact(F.array(*failed_exprs)))
        .withColumn("_quarantine_timestamp", F.current_timestamp())
        .withColumn("_source_table",         F.lit(src["source_table"]))
        .filter(F.size(F.col("_failed_dq_rules")) > 0)
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Silver table registration
# ─────────────────────────────────────────────────────────────────────────────

for src in _SOURCES:

    table_name              = src["source_table"]
    silver_table            = _normalize_table_name(table_name)
    silver_stream_view_name = f"{table_name}_silver_stream"
    scd_type                = src.get("scd_type", 2)

    silver_fqn = (
        f"{src['target_catalog_prefix']}"
        f".{src['target_schema']}"
        f".{silver_table}"
    )
    quarantine_fqn = (
        f"{src['target_catalog_prefix']}"
        f".{src['target_schema']}"
        f".{silver_table}_qtn"
    )

    silver_cols_cfg  = src.get("silver_columns") or []
    rename_map       = {
        c["name"]: _silver_col_name(c)
        for c in silver_cols_cfg
        if _silver_col_name(c) != c["name"]
    }
    silver_cols_user = [_silver_col_name(c) for c in silver_cols_cfg]

    cdf_renames = {
        user: _normalize_column_name(user)
        for user in silver_cols_user
        if _normalize_column_name(user) != user
    }
    silver_cols = [cdf_renames.get(u, u) for u in silver_cols_user]

    if silver_cols_cfg:
        def to_silver(bronze_name, _rm=rename_map, _cdf=cdf_renames):
            user_silver = _rm.get(bronze_name, bronze_name)
            return _cdf.get(user_silver, user_silver)
    else:
        def to_silver(bronze_name):
            return _normalize_column_name(bronze_name)

    if silver_cols_cfg:
        dq_expectations = {
            rule["description"]: _translate_expr_columns(rule["expr"], cdf_renames)
            for rule in (src.get("data_quality_rules") or [])
        }
    else:
        def _build_implicit_dq_renames(rules):
            referenced = set()
            for rule in rules:
                referenced.update(re.findall(r"`([^`]+)`", rule["expr"]))
            return {n: _normalize_column_name(n) for n in referenced
                    if _normalize_column_name(n) != n}
        implicit_dq_renames = _build_implicit_dq_renames(
            src.get("data_quality_rules") or []
        )
        dq_expectations = {
            rule["description"]: _translate_expr_columns(rule["expr"], implicit_dq_renames)
            for rule in (src.get("data_quality_rules") or [])
        }

    @dp.temporary_view(name=silver_stream_view_name)
    def silver_stream(src=src, silver_cols_cfg=silver_cols_cfg, cdf_renames=cdf_renames):
        df = _build_silver_stream(src)
        if silver_cols_cfg:
            for user_name, norm_name in cdf_renames.items():
                df = df.withColumnRenamed(user_name, norm_name)
        else:
            for c in list(df.columns):
                if c.startswith("_"):
                    continue
                norm = _normalize_column_name(c)
                if norm != c:
                    df = df.withColumnRenamed(c, norm)
        if src.get("scd_2_key_list") == ["_identity_hash"]:
            hash_cols = sorted([c for c in df.columns if not c.startswith("_")])
            df = df.withColumn(
                "_identity_hash",
                F.md5(F.concat_ws("||", *[F.coalesce(F.col(c).cast("string"), F.lit("__NULL__")) for c in hash_cols]))
            )
        return df

    cluster_by_normalized = [to_silver(c) for c in (src.get("cluster_by") or [])]
    dp.create_streaming_table(
        name               = silver_fqn,
        comment            = src.get("description", f"Silver SCD{scd_type} table: {table_name}"),
        cluster_by         = cluster_by_normalized,
        expect_all_or_drop = dq_expectations,
        table_properties   = {
            "quality":                        "silver",
            "pipelines.autoOptimize.managed": "true",
            "silver.scd_type":                str(scd_type),
            **{f"source.{k}": str(v) for k, v in src.get("tags", {}).items()},
        },
    )

    keys_normalized = [to_silver(k) for k in src["scd_2_key_list"]]

    scd_seq = src.get("history_timestamp_source") or "pipeline_timestamp"
    if scd_seq == "pipeline_timestamp":
        sequence_by_col = "_bronze_ingested_at"
        except_cols     = []
    elif isinstance(scd_seq, list):
        sequence_by_col = "_scd_sequence_ts"
        except_cols     = ["_scd_sequence_ts"]
    else:
        sequence_by_col = to_silver(scd_seq)
        except_cols     = []

    _SYSTEM_AUDIT_COLS = [
        "_bronze_ingested_at",
        "_staging_ingested_at",
        "_source_file_path",
        "_source_file_name",
        "_source_file_size",
        "_source_file_modified",
        "_rescued_data",
    ]
    if isinstance(scd_seq, list):
        _SYSTEM_AUDIT_COLS = _SYSTEM_AUDIT_COLS + ["_scd_sequence_ts"]

    _bronze_cols = None
    try:
        _bronze_cols = set(
            r.column_name for r in spark.sql(
                f"SELECT column_name FROM {src['source_catalog']}.information_schema.columns "
                f"WHERE table_schema = '{src['source_schema']}' "
                f"AND table_name = '{src['source_table']}'"
            ).collect()
        )
        scd_2_exclude_normalized = [
            to_silver(c) for c in (src.get("scd_2_exclude_list") or [])
            if to_silver(c) in _bronze_cols
        ]
    except Exception:
        scd_2_exclude_normalized = [
            to_silver(c) for c in (src.get("scd_2_exclude_list") or [])
        ]

    if silver_cols_cfg:
        silver_cols_tracked = [c for c in silver_cols if c not in scd_2_exclude_normalized]
        track_history_kwargs = {"track_history_column_list": silver_cols_tracked}
    else:
        track_history_kwargs = {
            "track_history_except_column_list": [
                c for c in list(dict.fromkeys(_SYSTEM_AUDIT_COLS + scd_2_exclude_normalized))
                if _bronze_cols is not None and c in _bronze_cols
            ]
        }

    dp.apply_changes(
        target                    = silver_fqn,
        source                    = silver_stream_view_name,
        keys                      = keys_normalized,
        sequence_by               = sequence_by_col,
        stored_as_scd_type        = scd_type,
        except_column_list        = except_cols,
        **track_history_kwargs,
    )

    if dq_expectations:
        dp.create_streaming_table(
            name             = quarantine_fqn,
            comment          = f"Quarantine: rows from {table_name} that failed data quality rules.",
            table_properties = {
                "quality":                        "quarantine",
                "pipelines.autoOptimize.managed": "true",
                **{f"source.{k}": str(v) for k, v in src.get("tags", {}).items()},
            },
        )

        @dp.append_flow(target=quarantine_fqn, name=f"{silver_table}_quarantine_flow")
        def quarantine_flow(src=src):
            return _build_quarantine_stream(src)


# ─────────────────────────────────────────────────────────────────────────────
# Silver manifest
# ─────────────────────────────────────────────────────────────────────────────

@dp.temporary_view(name="_silver_manifest")
def silver_manifest():
    rows = [
        {
            "source_table":      s["source_table"],
            "source_catalog":    s.get("source_catalog", ""),
            "source_schema":     s.get("source_schema", ""),
            "target_catalog":    s.get("target_catalog_prefix", ""),
            "target_schema":     s.get("target_schema", ""),
            "scd_type":          str(s.get("scd_type", 2)),
            "scd_2_key_list":    str(s.get("scd_2_key_list", [])),
            "history_timestamp_source": str(s.get("history_timestamp_source") or "pipeline_timestamp"),
            "config_file":       os.path.basename(f),
            "tags":              str(s.get("tags", {})),
        }
        for s, f in zip(_SOURCES, _YAML_FILES)
    ]
    if not rows:
        from pyspark.sql.types import StructType, StructField, StringType
        schema = StructType([
            StructField("source_table", StringType()),
            StructField("source_catalog", StringType()),
            StructField("source_schema", StringType()),
            StructField("target_catalog", StringType()),
            StructField("target_schema", StringType()),
            StructField("scd_type", StringType()),
            StructField("scd_2_key_list", StringType()),
            StructField("history_timestamp_source", StringType()),
            StructField("config_file", StringType()),
            StructField("tags", StringType()),
        ])
        return spark.createDataFrame([], schema)
    return spark.createDataFrame(rows)
