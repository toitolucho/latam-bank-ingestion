# Credit reference tables

Synthetic, team-defined tables that stand in for data the dataset lacks: a credit product
catalog and pricing. In Databricks they live in **silver** as `silver_latam_bank.ref_<name>`,
next to cleaned source data. These CSVs are the source of truth.

All files carry `is_synthetic = true`. They are **static**: values are fixed in the CSV and do
not change with new data or exchange rates. The SQL in `derivation/` documents how they were
derived from the organizer data; rerun it only to deliberately regenerate a table. It runs in
DuckDB over the raw CSVs exposed as `raw_<table>` views, from the repository root.

All amounts are in **USD** and the tables are **country-agnostic**: in the source data, rates
and amounts are the same across Mexico, Colombia and Argentina. Amounts are converted to the
customer's local currency at serving time, with that day's exchange rate.

Credit products in scope are the three raw `product_type` values `Tarjeta Crédito`,
`Préstamo Personal` and `Préstamo Hipotecario`.

## ref_product_catalog.csv
One row per credit product: credit card (`CC`), personal loan (`PL`), mortgage (`MG`).

| Column | Source |
|---|---|
| `source_product_type` | Raw label in `products` (Spanish, with accents), used to join with the data |
| `product_type` | English mapping of `source_product_type` |
| `min_amount_usd`, `max_amount_usd` | Observed min/max `credit_limit` of active products, in USD (`derivation/06_credit_catalog_observed.sql`), rounded |
| `min_rate_pct`, `max_rate_pct` | Observed min/max `interest_rate` of active products (`derivation/06`) |
| `allowed_terms_months` | **Synthetic**, defined by the team: credit card 5 years; personal loan 2–5 years (yearly steps); mortgage 15, 20, 25 or 30 years. The data has no loan term (`expiration_date` is null for loans) |

Known data limitation: personal loans and mortgages share the same amount range in the source data.

## ref_term_grid.csv
Reference rate and amount range per product and term, with credit cards split into tiers
(12 rows). Derived with `derivation/07_term_rate_amount_grid.sql`.

**Synthetic rule**, because the data has no loan term and rates show no relationship with
amount, score or product age:
- Loans: the reference rate rises with term (term k of n takes the observed rate quantile
  k/(n+1)); larger amounts map to longer terms (observed amounts split into n equal-frequency
  slices).
- Credit cards: one row per tier (see `ref_card_tiers.csv`).

Amounts rounded to the nearest 1,000 USD and clamped to the catalog bounds; rates to one decimal.

How the amounts are used (policy 0.4): for credit cards they are the tier's credit limit
range. For loans they are a typical amount range per term, used only to infer the term of a
customer's existing loans; new loan offers can use any amount in the product range at any
term up to the band maximum (`ref_policy_bands`).

## ref_card_tiers.csv
Credit card tiers (Classic, Gold, Platinum, Black). **Synthetic.** Derivation input for
`derivation/07` only; not loaded to Databricks, since its result is already in
`ref_term_grid`. Each tier takes a slice of the observed credit limits
(`limit_from_pct`–`limit_to_pct`, a 40/30/20/10 customer pyramid) and the observed rate at
percentile `rate_pct` (Classic p80 → Black p20, so higher tiers get lower rates).

## Credit policy (policy_version 0.4)
`ref_policy_params.csv`, `ref_policy_bands.csv` and `ref_segment_adjustments.csv` hold the
parameters of the credit rules in `docs/CREDIT_RULES.md`. **Synthetic.** The gold SQL and the
rules service must read the same values.

| File | Contents |
|---|---|
| `ref_policy_params.csv` | Scalars: 20% debt-to-income hard limit, hard-filter thresholds, offer validity, cutoff date, policy version |
| `ref_policy_bands.csv` | Bands A–E by `credit_score` (fallback until the risk model exists): rate adjustment, maximum personal loan and mortgage term, whether an offer is allowed |
| `ref_segment_adjustments.csv` | Rate adjustment by customer segment |

## Loading to Databricks
Reload silver only when a CSV changes:

```bash
pip install -r data/scripts/requirements.txt
databricks auth login --host <workspace-url> --profile <profile>
python data/scripts/load_reference.py --profile <profile> --warehouse-id <sql-warehouse-id>
```

The script uploads the loaded CSVs to `/Volumes/workspace/silver_latam_bank/reference/` and runs
`data/databricks/load_silver_reference.sql`, which recreates `ref_product_catalog`,
`ref_term_grid`, `ref_policy_params`, `ref_policy_bands` and `ref_segment_adjustments` with
explicit types, column comments, `policy_version` and load metadata (`_source_file`,
`_loaded_at`). The `databricks` CLI must be on `PATH` (the SDK uses it for OAuth).
