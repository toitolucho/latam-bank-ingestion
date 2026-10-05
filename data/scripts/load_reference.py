"""Loads data/reference/*.csv into the silver reference tables in Databricks.

Steps: create the volume, upload the CSVs in data/reference to it, then run
data/databricks/load_silver_reference.sql with :silver_schema set to --silver-schema (the ref_*
tables are created there; the CSVs always go to the workspace.silver_latam_bank.reference volume).
Authentication uses a Databricks CLI profile (OAuth, `databricks auth login`); no tokens in code.

Usage:
    python data/scripts/load_reference.py --profile <profile> --warehouse-id <id>
    python data/scripts/load_reference.py --silver-schema workspace.silver_latam_bank_test --profile <profile> --warehouse-id <id>
"""
import argparse
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState

ROOT = Path(__file__).resolve().parents[2]
SQL_FILE = ROOT / "data" / "databricks" / "load_silver_reference.sql"
VOLUME_PATH = "/Volumes/workspace/silver_latam_bank/reference"
FILES = [
    "ref_product_catalog.csv",
    "ref_term_grid.csv",
    "ref_policy_params.csv",
    "ref_policy_bands.csv",
    "ref_segment_adjustments.csv",
]


def statements(sql: str):
    """Split on ';' at line end and drop comment-only chunks."""
    for chunk in sql.split(";\n"):
        code = "\n".join(l for l in chunk.splitlines() if not l.strip().startswith("--")).strip()
        if code:
            yield code


def run(w: WorkspaceClient, warehouse_id: str, sql: str, params=None):
    # Only send parameters the statement uses: the API rejects unused named parameters.
    used = [p for p in (params or []) if f":{p.name}" in sql]
    r = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=warehouse_id, wait_timeout="50s", parameters=used or None)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{r.status.state}: {r.status.error.message if r.status.error else ''}\n{sql[:200]}")
    return r


def main(args):
    w = WorkspaceClient(profile=args.profile)
    params = [StatementParameterListItem(name="silver_schema", value=args.silver_schema)]
    stmts = list(statements(SQL_FILE.read_text(encoding="utf-8")))
    # the first statement creates the volume, which must exist before uploading
    run(w, args.warehouse_id, stmts[0])
    for name in FILES:
        with open(ROOT / "data" / "reference" / name, "rb") as f:
            w.files.upload(f"{VOLUME_PATH}/{name}", f, overwrite=True)
        print(f"uploaded {name}")
    for s in stmts[1:]:
        run(w, args.warehouse_id, s, params)
        print("ok:", s.splitlines()[0][:90])
    for name in FILES:
        table = name.removesuffix(".csv")
        n = run(w, args.warehouse_id, f"SELECT count(*) FROM IDENTIFIER(:silver_schema || '.{table}')",
                params).result.data_array[0][0]
        print(f"{args.silver_schema}.{table}: {n} rows")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", default=None, help="Databricks CLI profile; default auth if omitted")
    p.add_argument("--warehouse-id", required=True)
    p.add_argument("--silver-schema", default="workspace.silver_latam_bank",
                   help="catalog.schema for the ref_* tables (default: %(default)s)")
    main(p.parse_args())
