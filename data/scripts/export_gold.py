"""Downloads the gold export for serving from Databricks to .local/gold/.

The export is produced in Databricks by the last task of the latam_bank_medallion and
credit_policy_refresh jobs (data/databricks/gold/95_export_for_serving.py), only after the gold
quality checks pass. It lives in the volume <gold_schema>.exports: one Parquet folder per table
(customer_credit_profile, customer_credit_offer_options, ref_*) plus _manifest.json. This script
copies it locally for the demo backend; .local/ is git-ignored because the data is derived from
organizer data.

Usage:
    python data/scripts/export_gold.py --profile <profile>
    python data/scripts/export_gold.py --gold-schema workspace.gold_latam_bank_test --profile <profile>
"""
import argparse
import json
from pathlib import Path

from databricks.sdk import WorkspaceClient

ROOT = Path(__file__).resolve().parents[2]
SKIP_PREFIXES = ("_started", "_committed", "_SUCCESS")   # Spark commit markers


def download_tree(w: WorkspaceClient, remote: str, local: Path) -> int:
    count = 0
    for entry in w.files.list_directory_contents(remote):
        name = entry.path.rstrip("/").split("/")[-1]
        if entry.is_directory:
            count += download_tree(w, entry.path, local / name)
        elif not name.startswith(SKIP_PREFIXES):
            local.mkdir(parents=True, exist_ok=True)
            with open(local / name, "wb") as f:
                f.write(w.files.download(entry.path).contents.read())
            count += 1
    return count


def main(args):
    w = WorkspaceClient(profile=args.profile)
    catalog, schema = args.gold_schema.split(".")
    remote = f"/Volumes/{catalog}/{schema}/exports"
    out = Path(args.out)
    n = download_tree(w, remote, out)
    manifest = json.loads((out / "_manifest.json").read_text(encoding="utf-8"))
    print(f"Downloaded {n} files from {remote} to {out}")
    print(f"exported_at {manifest['exported_at']}, run {manifest['run_id']}, as_of {manifest['as_of_date']}, "
          f"policy {manifest['policy_version']}")
    for table, rows in manifest["rows"].items():
        print(f"  {table}: {rows:,} rows")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", default=None, help="Databricks CLI profile; default auth if omitted")
    p.add_argument("--gold-schema", default="workspace.gold_latam_bank")
    p.add_argument("--out", default=str(ROOT / ".local" / "gold"))
    main(p.parse_args())
