# Databricks notebook source
# =============================================================================================
# 95_export_for_serving: Parquet export of gold for the demo backend. Last task of the
# latam_bank_medallion and credit_policy_refresh jobs, after the gold quality checks pass, so only
# validated data is exported.
#
# Writes to the Unity Catalog volume <gold_schema>.exports:
#   customer_credit_profile/, customer_credit_offer_options/   gold tables
#   ref_*/                                                     policy tables from silver
#   _manifest.json                                             rows per table, as_of_date, policy
#                                                              version, run id and export time
# The backend downloads the folder (data/scripts/export_gold.py) and reads it with pandas/pyarrow,
# so the container needs no Databricks credentials. The export stays in the workspace: it is
# derived from organizer data and is never committed.
#
# Widgets (catalog.schema): gold_schema, silver_schema; run_id is the job run id.
# =============================================================================================

import json
from datetime import datetime, timezone

dbutils.widgets.text("gold_schema", "workspace.gold_latam_bank")
dbutils.widgets.text("silver_schema", "workspace.silver_latam_bank")
dbutils.widgets.text("run_id", "")
gold_schema = dbutils.widgets.get("gold_schema")
silver_schema = dbutils.widgets.get("silver_schema")
run_id = dbutils.widgets.get("run_id") or "manual"

catalog, schema = gold_schema.split(".")
export_dir = f"/Volumes/{catalog}/{schema}/exports"
spark.sql(f"CREATE VOLUME IF NOT EXISTS {gold_schema}.exports "
          "COMMENT 'Parquet export of gold for the demo backend (written by 95_export_for_serving)'")

TABLES = [
    (gold_schema, "customer_credit_profile"),
    (gold_schema, "customer_credit_offer_options"),
    (silver_schema, "ref_product_catalog"),
    (silver_schema, "ref_term_grid"),
    (silver_schema, "ref_policy_params"),
    (silver_schema, "ref_policy_bands"),
    (silver_schema, "ref_segment_adjustments"),
]

# COMMAND ----------

rows = {}
for source_schema, table in TABLES:
    df = spark.table(f"{source_schema}.{table}")
    # One file per table: the largest (offer options, 1.8M rows) is ~20 MB compressed.
    df.coalesce(1).write.mode("overwrite").parquet(f"{export_dir}/{table}")
    rows[table] = spark.read.parquet(f"{export_dir}/{table}").count()
    print(f"{table}: {rows[table]:,} rows -> {export_dir}/{table}")

# COMMAND ----------

profile = spark.table(f"{gold_schema}.customer_credit_profile")
meta = profile.selectExpr("max(as_of_date) AS as_of_date", "max(policy_version) AS policy_version").first()
manifest = {
    "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "run_id": run_id,
    "gold_schema": gold_schema,
    "silver_schema": silver_schema,
    "as_of_date": str(meta.as_of_date),
    "policy_version": meta.policy_version,
    "rows": rows,
}
dbutils.fs.put(f"{export_dir}/_manifest.json", json.dumps(manifest, indent=2), overwrite=True)

# The export must match the tables it came from.
expected = {t: spark.table(f"{s}.{t}").count() for s, t in TABLES}
mismatch = {t: (rows[t], expected[t]) for t in rows if rows[t] != expected[t]}
if mismatch:
    raise ValueError(f"Export row counts differ from the source tables: {mismatch}")
print(json.dumps(manifest, indent=2))
