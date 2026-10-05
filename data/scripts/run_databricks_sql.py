"""Runs SQL files statement by statement on a Databricks SQL warehouse.

Authentication uses a Databricks CLI profile (OAuth, `databricks auth login`); the `databricks`
CLI must be on PATH. Statements are split on ';' at line end. Named parameter markers in the SQL
(e.g. `:as_of_date`) take their values from `--param name=value`; the same values are sent to
every statement.

Usage:
    python data/scripts/run_databricks_sql.py data/databricks/gold/00_deploy_objects.sql --profile <profile> --warehouse-id <id>
    python data/scripts/run_databricks_sql.py data/databricks/gold/10_customer_credit_profile.sql \\
        data/databricks/gold/20_customer_credit_offer_options.sql data/databricks/gold/90_quality_checks.sql \\
        --param as_of_date= --profile <profile> --warehouse-id <id>
"""
import argparse
import sys
import time
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState

sys.path.insert(0, str(Path(__file__).parent))
from load_reference import statements  # noqa: E402

RUNNING = (StatementState.PENDING, StatementState.RUNNING)


def run(w: WorkspaceClient, warehouse_id: str, sql: str, params=None):
    # Only send parameters the statement uses: the API rejects unused named parameters.
    used = [p for p in (params or []) if f":{p.name}" in sql]
    r = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=warehouse_id, wait_timeout="50s", parameters=used or None)
    while r.status.state in RUNNING:
        time.sleep(5)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{r.status.state}: {r.status.error.message if r.status.error else ''}\n{sql[:300]}")
    return r


def parse_params(items):
    params = []
    for item in items or []:
        name, sep, value = item.partition("=")
        if not sep or not name:
            raise SystemExit(f"--param expects name=value, got {item!r}")
        params.append(StatementParameterListItem(name=name, value=value))
    return params


def main(args):
    w = WorkspaceClient(profile=args.profile)
    params = parse_params(args.param)
    for file in args.files:
        for s in statements(Path(file).read_text(encoding="utf-8")):
            t0 = time.time()
            run(w, args.warehouse_id, s, params)
            print(f"ok ({time.time() - t0:.0f}s): {s.splitlines()[0][:100]}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+")
    p.add_argument("--param", action="append", help="named parameter as name=value; repeatable")
    p.add_argument("--profile", default=None, help="Databricks CLI profile; default auth if omitted")
    p.add_argument("--warehouse-id", required=True)
    main(p.parse_args())
