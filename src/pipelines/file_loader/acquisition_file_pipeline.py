# =============================================================================
# acquisition_file_pipeline.py
# =============================================================================
# File Loader — raw file acquisition into append-only staging tables.
#
# Auto Loader (cloudFiles) reads files and appends them to one streaming
# table per config YAML. No CDC, no dedup, no transforms — only file
# provenance columns are added.
#
# Config-driven: every *.yml in pipeline_config_dir becomes one staging table.
# =============================================================================

import os
import sys

from pyspark import pipelines as dp
from pyspark.sql import functions as F

# ---------------------------------------------------------------------------
# Import the shared naming/config helpers
# ---------------------------------------------------------------------------
for _candidate in (spark.conf.get("pipeline_source_dir", None), os.getcwd()):
    if _candidate and _candidate not in sys.path:
        sys.path.insert(0, _candidate)

try:
    import axos_framework as axos
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError(
        "Could not import axos_framework.py. Ensure it sits next to this file "
        "in src/pipelines/file_loader/ and the pipeline's `configuration:` block "
        "sets 'pipeline_source_dir' to the synced workspace path of that folder. "
        f"sys.path was: {sys.path[:3]}"
    ) from exc

# ---------------------------------------------------------------------------
# Config folder scan
# ---------------------------------------------------------------------------
_ENV = axos.resolve_env(spark)
_CONFIG_DIR = axos.resolve_config_dir(spark)
_SOURCES = list(axos.load_table_configs(_CONFIG_DIR))
_PIPELINE_CATALOG = spark.conf.get("pipeline.catalog", None)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
axos.validate_acquisition(_SOURCES, _ENV)

# ---------------------------------------------------------------------------
# Provenance columns
# ---------------------------------------------------------------------------

def _add_provenance(df):
    """Stamp file provenance metadata on every row."""
    return (
        df
        .withColumn("_staging_ingested_at", F.current_timestamp())
        .withColumn("_source_file_path", F.col("_metadata.file_path"))
        .withColumn("_source_file_name", F.col("_metadata.file_name"))
        .withColumn("_source_file_size", F.col("_metadata.file_size").cast("long"))
        .withColumn("_source_file_modified", F.col("_metadata.file_modification_time"))
    )

# ---------------------------------------------------------------------------
# Dynamic registration: one streaming table per config YAML
# ---------------------------------------------------------------------------
for _filename, _src in _SOURCES:

    staging_table = (
        f"{_PIPELINE_CATALOG}.{axos.staging_schema(_src)}.{_src['source_table']}"
        if _PIPELINE_CATALOG
        else axos.staging_fqn(_src, _ENV)
    )

    _table_properties = {
        "pipelines.autoOptimize.managed": "true",
        "ingestion.source_type": "file",
        "ingestion.source_path": str(_src["source_path"]),
        "ingestion.file_format": str(_src["file_format"]),
        "ingestion.config_file": _filename,
        "quality": "staging",
        **axos.source_tags(_src),
    }

    dp.create_streaming_table(
        name=staging_table,
        comment=_src.get("description")
        or f"Raw file acquisition (append-only): {_src['source_table']}",
        table_properties=_table_properties,
    )

    @dp.append_flow(
        target=staging_table,
        name=f"{_src['source_table']}_autoloader_flow",
    )
    def acquire_files(src=_src):
        reader = (
            spark.readStream
            .format("cloudFiles")
            .options(**axos.autoloader_options(src))
        )
        return reader.load(src["source_path"]).transform(_add_provenance)
