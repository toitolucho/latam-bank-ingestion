"""
axos_framework.py
================================================================================
Shared helpers for the TCI config-driven file-loader pipeline.
================================================================================

Adapted from the processibeam bundle's axos_framework. Provides:
  - Naming standard (catalog.schema.table construction)
  - Config folder scanning
  - Auto Loader option mapping
  - Validation

CURRENT AXOS STANDARD
    catalog.schema.table  =  {division}_{env}.{layer}_{sor}.{table}
    e.g.                     enterprise_dev.staging_tci.some_table
"""

import glob
import os
import re


# =============================================================================
# NAMING STANDARD
# =============================================================================

DEFAULT_DIVISION = "enterprise"

LAYER_STAGING = "staging"
LAYER_BRONZE = "bronze"
LAYER_SILVER = "silver"


def division(src: dict) -> str:
    """Division token that prefixes the catalog."""
    return str(src.get("division") or DEFAULT_DIVISION)


def _catalog(src: dict, env: str, override_key: str) -> str:
    prefix = src.get(override_key) or division(src)
    return f"{prefix}_{env}"


def _schema(src: dict, layer: str, override_key: str) -> str:
    override = src.get(override_key)
    if override:
        return str(override)
    sor = src.get("sor")
    if not sor:
        raise ValueError(
            f"Table '{src.get('source_table', '<unnamed>')}' is missing 'sor', "
            f"which is required to build the {layer} schema name."
        )
    return f"{layer}_{sor}"


def staging_catalog(src: dict, env: str) -> str:
    return _catalog(src, env, "staging_catalog")


def staging_schema(src: dict) -> str:
    return _schema(src, LAYER_STAGING, "staging_schema")


def staging_fqn(src: dict, env: str) -> str:
    """Append-only Auto Loader landing table."""
    return f"{staging_catalog(src, env)}.{staging_schema(src)}.{src['source_table']}"


# =============================================================================
# ENVIRONMENT RESOLUTION
# =============================================================================

_ENV_CONF_KEYS = ("catalog_env", "target_env")


def resolve_env(spark) -> str:
    """Read the environment token from pipeline configuration."""
    for key in _ENV_CONF_KEYS:
        value = spark.conf.get(key, None)
        if value:
            return str(value).strip()
    raise ValueError(
        "No environment token found in the pipeline configuration. Set one of "
        f"{list(_ENV_CONF_KEYS)} in the pipeline's `configuration:` block."
    )


def resolve_config_dir(spark) -> str:
    """The config folder this pipeline owns."""
    config_dir = spark.conf.get("pipeline_config_dir", None)
    if not config_dir:
        raise ValueError(
            "Pipeline configuration key 'pipeline_config_dir' is not set."
        )
    return config_dir


# =============================================================================
# CONFIG FOLDER SCAN
# =============================================================================

def load_table_configs(config_dir: str) -> list:
    """
    Glob every *.yml in `config_dir` and load one table config per file.
    Returns [(filename, config_dict), ...].
    """
    if not os.path.isdir(config_dir):
        raise FileNotFoundError(
            f"Config directory not found: '{config_dir}'. Check the "
            "pipeline_config_dir value in databricks.yml."
        )

    # Reject .yaml files (only .yml is supported)
    stray = sorted(
        os.path.basename(p) for p in glob.glob(os.path.join(config_dir, "*.yaml"))
    )
    if stray:
        raise ValueError(
            f"Config directory '{config_dir}' contains .yaml files: {stray}. "
            "Table configs must use the .yml extension."
        )

    paths = sorted(glob.glob(os.path.join(config_dir, "*.yml")))

    # Skip template files (prefixed with _)
    paths = [p for p in paths if not os.path.basename(p).startswith("_")]

    if not paths:
        raise FileNotFoundError(
            f"No *.yml table configs found in '{config_dir}'. "
            "Populate the folder before deploying; one YAML = one table."
        )

    return [(os.path.basename(p), _load_one(p)) for p in paths]


def _load_one(path: str) -> dict:
    """Load a single table config YAML. Accepts a mapping or single-item list."""
    import yaml

    with open(path, "r") as f:
        data = yaml.safe_load(f)
    if isinstance(data, list):
        if not data:
            raise ValueError(f"[{os.path.basename(path)}] File is empty.")
        return data[0]
    if not isinstance(data, dict):
        raise ValueError(
            f"[{os.path.basename(path)}] Expected a mapping or single-item list."
        )
    return data


# =============================================================================
# VALIDATION
# =============================================================================

def validate_identity(sources: list):
    """Check source_table uniqueness and sor presence."""
    seen = set()
    for filename, src in sources:
        table = src.get("source_table")
        if not table:
            raise ValueError(f"[{filename}] Missing required field 'source_table'.")
        if table in seen:
            raise ValueError(f"[{filename}] Duplicate source_table '{table}'.")
        seen.add(table)
        if not src.get("sor"):
            raise ValueError(
                f"[{filename}] Missing required field 'sor' for '{table}'."
            )


# Dev landing accounts — block non-dev environments from reading dev data.
DEV_ENV = "dev"
DEV_LANDING_ACCOUNTS = ("axdevdbxlanding",)
_ABFSS_HOST = re.compile(r"^abfss://[^@/]*@([^/]+)", re.IGNORECASE)


def storage_account(source_path: str):
    match = _ABFSS_HOST.match(str(source_path).strip())
    if not match:
        return None
    return match.group(1).split(".")[0].lower()


def validate_acquisition(sources: list, env: str):
    """Validate fields the acquisition layer needs."""
    validate_identity(sources)

    for filename, src in sources:
        table = src["source_table"]

        if not src.get("source_path"):
            raise ValueError(
                f"[{filename}] Missing 'source_path' for '{table}'."
            )

        # Block dev landing paths in non-dev envs
        source_path = str(src["source_path"])
        account = storage_account(source_path)
        if env != DEV_ENV and account in DEV_LANDING_ACCOUNTS:
            raise ValueError(
                f"[{filename}] source_path for '{table}' points at DEV landing "
                f"account '{account}' but environment is '{env}'."
            )

        file_format = str(src.get("file_format") or "").lower()
        if not file_format:
            raise ValueError(f"[{filename}] Missing 'file_format' for '{table}'.")
        if file_format not in FILE_FORMAT_ALIASES:
            raise ValueError(
                f"[{filename}] Unsupported file_format '{src['file_format']}' for "
                f"'{table}'. Valid: {sorted(FILE_FORMAT_ALIASES)}."
            )

        bronze_options = src.get("bronze_options") or {}
        csv_options = bronze_options.get("csv_options") or {}

        if file_format == "csv" and not csv_options:
            raise ValueError(
                f"[{filename}] file_format 'csv' for '{table}' requires a "
                "non-empty 'csv_options' block under bronze_options."
            )

        # XML requires explicit rowTag so the reader knows which element = one row
        xml_options = bronze_options.get("xml_options") or {}
        if file_format == "xml" and not xml_options.get("rowTag"):
            raise ValueError(
                f"[{filename}] file_format 'xml' for '{table}' requires an "
                "'xml_options' block under bronze_options with an explicit "
                "'rowTag' naming the repeating element (e.g. rowTag: Application)."
            )


# =============================================================================
# AUTO LOADER OPTIONS
# =============================================================================

FILE_FORMAT_ALIASES = {
    "json": "json",
    "parquet": "parquet",
    "csv": "csv",
    "avro": "avro",
    "text": "text",
    "excel": "excel",
    "xml": "xml",
}

BRONZE_OPTION_MAP = {
    "schema_hints": "cloudFiles.schemaHints",
    "schema_evolution_mode": "cloudFiles.schemaEvolutionMode",
    "include_existing_files": "cloudFiles.includeExistingFiles",
    "ignore_corrupt_files": "ignoreCorruptFiles",
    "file_name_pattern": "pathGlobFilter",
    "use_managed_file_events": "cloudFiles.useManagedFileEvents",
    "backfill_interval": "cloudFiles.backfillInterval",
}

INFER_COLUMN_TYPES_OPTION = "cloudFiles.inferColumnTypes"


def _option_value(value) -> str:
    """Convert Python bools to Spark option strings."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def autoloader_options(src: dict) -> dict:
    """Assemble the full reader option dict for one source's Auto Loader stream."""
    options = {
        "cloudFiles.format": FILE_FORMAT_ALIASES[str(src["file_format"]).lower()],
    }

    bronze_options = src.get("bronze_options") or {}

    for yaml_key, option_key in BRONZE_OPTION_MAP.items():
        value = bronze_options.get(yaml_key)
        if value is not None:
            options[option_key] = _option_value(value)

    # csv_options passthrough
    for key, value in (bronze_options.get("csv_options") or {}).items():
        options[key] = _option_value(value)

    # json_options passthrough
    for key, value in (bronze_options.get("json_options") or {}).items():
        options[key] = _option_value(value)

    # xml_options passthrough (rowTag, rootTag, etc.)
    for key, value in (bronze_options.get("xml_options") or {}).items():
        options[key] = _option_value(value)

    # Disable type inference for flat formats (Bronze stays STRING).
    # XML requires inference so nested elements become STRUCT/ARRAY, not STRING.
    file_fmt = str(src["file_format"]).lower()
    options[INFER_COLUMN_TYPES_OPTION] = "true" if file_fmt == "xml" else "false"

    return options


# =============================================================================
# TABLE PROPERTIES
# =============================================================================

def source_tags(src: dict) -> dict:
    """Per-table tags surfaced as table properties."""
    return {f"source.{k}": str(v) for k, v in (src.get("tags") or {}).items()}
