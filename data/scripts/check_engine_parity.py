"""Checks that an offer engine reproduces gold customer_credit_offer_options exactly.

Reads the gold export downloaded by data/scripts/export_gold.py (.local/gold/) and, for each customer profile,
compares the engine options with gold on availability, maximum amount, rate, installment and
the featured option.
It also checks that recalculate() with no declared data leaves every option unchanged.

The engine is any function `fn(profile: dict, policy) -> list[dict]` returning dicts with
option_code, term_months, is_available, offer_max_amount_usd, offer_rate_pct,
offer_monthly_installment_usd and is_featured. Default: the reference implementation in data/policy.

Usage:
    python data/scripts/check_engine_parity.py                       # reference engine, all customers
    python data/scripts/check_engine_parity.py --sample 5000
    python data/scripts/check_engine_parity.py --engine app.policy.offers:offer_options --pythonpath backend
"""
import argparse
import importlib
import math
import random
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data"))
from policy.credit_policy import load_policy, offer_options, recalculate  # noqa: E402

KEYS = ("option_code", "term_months")
TOL = 0.01


def load_engine(spec: str | None):
    if not spec:
        return offer_options
    module, _, name = spec.partition(":")
    return getattr(importlib.import_module(module), name)


def read_table(src: Path, name: str) -> pd.DataFrame:
    """The Databricks export is a folder per table; a single <name>.parquet file also works."""
    folder = src / name
    return pd.read_parquet(folder if folder.is_dir() else src / f"{name}.parquet")


def same(a, b) -> bool:
    if a is None or (isinstance(a, float) and math.isnan(a)):
        return b is None or (isinstance(b, float) and math.isnan(b))
    if b is None or (isinstance(b, float) and math.isnan(b)):
        return False
    return abs(float(a) - float(b)) <= TOL


def main(args):
    for extra in args.pythonpath or []:
        sys.path.insert(0, str(Path(extra).resolve()))
    engine = load_engine(args.engine)
    policy = load_policy()
    src = Path(args.gold_dir)
    profiles = read_table(src, "customer_credit_profile")
    gold = read_table(src, "customer_credit_offer_options")
    if args.sample:
        ids = random.Random(7).sample(list(profiles.customer_id), args.sample)
        profiles = profiles[profiles.customer_id.isin(ids)]
        gold = gold[gold.customer_id.isin(ids)]
    gold_by = {(r.customer_id, r.option_code, r.term_months): r
               for r in gold.itertuples(index=False)}

    checked = mismatches = recalc_changes = 0
    examples = []
    for prof in profiles.to_dict("records"):
        prof["reason_codes"] = list(prof["reason_codes"]) if prof["reason_codes"] is not None else []
        mine = engine(prof, policy)
        unchanged = recalculate(prof, policy).options
        for o, u in zip(mine, unchanged):
            g = gold_by[(prof["customer_id"], o["option_code"], o["term_months"])]
            checked += 1
            ok = (bool(o["is_available"]) == bool(g.is_available)
                  and same(o["offer_max_amount_usd"], g.offer_max_amount_usd)
                  and same(o["offer_rate_pct"], g.offer_rate_pct)
                  and same(o["offer_monthly_installment_usd"], g.offer_monthly_installment_usd)
                  and bool(o.get("is_featured")) == bool(g.is_featured))
            if not ok:
                mismatches += 1
                if len(examples) < 5:
                    examples.append((prof["customer_id"], o, g._asdict()))
            if (u["is_available"], u["offer_max_amount_usd"]) != (o["is_available"], o["offer_max_amount_usd"]):
                recalc_changes += 1
    print(f"customers: {len(profiles):,} | options checked: {checked:,} | mismatches vs gold: {mismatches:,}"
          f" | recalculate() with no new data changed: {recalc_changes:,}")
    for cid, o, g in examples:
        print(f"  {cid} {o['option_code']}/{o['term_months']}: engine={o} gold={g}")
    sys.exit(1 if mismatches or recalc_changes else 0)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gold-dir", default=str(ROOT / ".local" / "gold"))
    p.add_argument("--engine", help="module:function; default is the reference implementation")
    p.add_argument("--pythonpath", action="append", help="extra import path for --engine (repeatable)")
    p.add_argument("--sample", type=int, help="check a random sample of customers")
    main(p.parse_args())
