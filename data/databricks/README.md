# Databricks: medallion pipeline and credit layers

Notebooks, SQL, scripts and a Databricks Asset Bundle that build the LATAM Bank data in Unity
Catalog (`workspace` catalog): bronze → silver → gold, with data quality metrics on every run.
Policy and formulas are in `docs/CREDIT_RULES.md`; reference tables in `data/reference/`. All
policy values are synthetic and results are offline.

## Schemas and parameters

Every file takes the schemas as parameters (`catalog.schema`), so the same code runs against the
test or the real schemas: SQL files use named parameters with `IDENTIFIER(:silver_schema || '.table')`,
the bronze notebook a `bronze_schema` widget.

| Parameter | Real (`prod` target) | Test (`dev` target) |
|---|---|---|
| `bronze_schema` | `workspace.bronze_latam_bank` | `workspace.bronze_latam_bank_test` |
| `silver_schema` | `workspace.silver_latam_bank` | `workspace.silver_latam_bank_test` |
| `gold_schema` | `workspace.gold_latam_bank` | `workspace.gold_latam_bank_test` |

Table names have no layer prefix (the schema already says it): `<layer>_latam_bank.<entity>`,
snake_case; gold tables per customer are `customer_<subject>`.

## Files

| File | Builds | Layer | When |
|---|---|---|---|
| `01_bronze.py` | The 10 landing entities as delivered: explicit schema, all STRING, `_rescued_data`, `_source_file_path`, `_bronze_ingested_at`; large tables partitioned by `process_date` | bronze | Job `latam_bank_medallion` |
| `02_silver.sql` | The same 10 tables typed and deduplicated by business key (latest version wins) | silver | Job `latam_bank_medallion` |
| `02_silver_quality_checks.sql` | Bronze/silver metrics in `pipeline_quality_metrics`, then a gate that fails the run | silver | Job `latam_bank_medallion` |
| `load_silver_reference.sql` | `ref_product_catalog`, `ref_term_grid`, `ref_policy_params`, `ref_policy_bands`, `ref_segment_adjustments` | silver | When a CSV in `data/reference/` changes (`load_reference.py`) |
| `gold/00_deploy_objects.sql` | `fn_monthly_installment`, `fn_max_principal`, `credit_offers` | gold | Jobs `credit_gold_deploy` and `latam_bank_medallion` (idempotent) |
| `gold/10_customer_credit_profile.sql` | `customer_credit_profile` and the agent view `customer_credit_offer_context` | gold | Jobs `latam_bank_medallion` and `credit_policy_refresh` |
| `gold/20_customer_credit_offer_options.sql` | `customer_credit_offer_options` | gold | After the profile |
| `gold/30_customer_products_summary.sql` | `customer_products_summary` | gold | Job `latam_bank_medallion` |
| `gold/31_customer_complaints_summary.sql` | `customer_complaints_summary` | gold | Job `latam_bank_medallion` |
| `gold/32_customer_cashflow_summary.sql` | `customer_cashflow_summary` | gold | Job `latam_bank_medallion` |
| `gold/90_quality_checks.sql` | Gold metrics in `pipeline_quality_metrics`, then a gate that fails the run | gold | Both jobs, after the gold tables |
| `gold/95_export_for_serving.py` | Parquet export of the profile, offer options and `ref_*` to the volume `<gold_schema>.exports`, with `_manifest.json` | gold | Last task of both jobs, only after the checks pass |
| `tests/00_update_fixture_setup.sql`, `tests/99_update_fixture_assertions.sql` | Labeled test delivery on `*_fixture` schemas and the assertions of each case | fixture | Job `data_update_fixture_test` |

## Gold objects

| Object | Grain | Purpose |
|---|---|---|
| `customer_credit_profile` | one row per customer | Income used, current installments, 20% capacity, risk band, rate adjustment, maximum terms, reason codes R01–R08, `is_eligible`, `offer_mode`, advisor-review flag, FX used |
| `customer_credit_offer_options` | customer × `ref_term_grid` option | Alternatives, each using the whole 20% capacity: offer rate, maximum amount, installment and availability, in USD and local currency. Loans at any amount in the product range up to the band maximum term. `is_featured` marks the option to present first per product (highest tier or amount; ties to the shortest term) |
| `customer_credit_offer_context` (view) | one row per customer | The 25 profile columns the agent and the rules service need (eligibility, offer mode, capacity, pricing inputs, band maximum terms, open complaints). Rebuilt with the profile |
| `credit_offers` | one row per accepted offer | Written by the API only. Change Data Feed on; CHECK constraints on status, origin, positive amounts and the 20% limit. Never dropped by a deploy |
| `customer_products_summary`, `customer_complaints_summary`, `customer_cashflow_summary` | one row per customer | Descriptive context (products and delinquency, complaints by type/status/priority, last 90 days of transactions). Not used by the credit rules |
| `pipeline_quality_metrics` | run × table × metric | Data quality and lineage metrics of every run (`run_id`, `run_at`, `layer`, `table_name`, `metric`, `value`, `threshold`, `status`). Appended, never rebuilt |
| `fn_monthly_installment`, `fn_max_principal` | — | Annuity formulas the rules service must reproduce exactly |

Every column of the profile, the options and the view has a description in Unity Catalog
(`ALTER COLUMN ... COMMENT` at the end of `gold/10` and `gold/20`, reapplied on each rebuild).

`offer_mode`: `proactive` (eligible, marketing consent, no open Critical complaint),
`on_customer_interest` (eligible, offer only if the customer asks about credit) or `none`.

## Data quality

The dataset documentation lists duplicates (~2%), nulls (~5%), late arrivals and schema
evolution. The pipeline handles and measures them; every metric goes to
`pipeline_quality_metrics` **before** the gate, so failed runs keep their metrics.

| Characteristic | Handling | Metric (status) |
|---|---|---|
| Duplicates | Silver keeps one row per business key, latest version first (`QUALIFY ROW_NUMBER()`) | `key_duplicates_removed_share` (fail > 5%), `key_duplicate_rows_left` (fail > 0), `content_duplicate_rows`: same record under another id (warn) |
| Nulls | Rows with a null key are dropped; other nulls are kept and the credit rules treat them as missing data (R05, R06) | `null_key_rows` in bronze (warn); `null_share_<column>` per critical column with its own threshold, e.g. `credit_score` ≤ 20%, `estimated_monthly_income` ≤ 25% (fail) |
| Schema evolution | Bronze reads with an explicit schema; new columns or malformed rows go to `_rescued_data` instead of being lost or breaking the load | `rescued_rows` (warn) |
| Late arrivals | Every run reloads all landing files, so a late file enters the next run; dedup by `process_date DESC` keeps the latest version whatever the arrival order | — |

Measured on the test schemas: 0 key duplicates and 0 content duplicates in every table except 6
repeated `product_number` values across different products; the "~2%" duplicates of the dataset
documentation do not show up in the files.

Gold checks (`gold/90_quality_checks.sql`) fail the run when: the profile does not have one row per
silver customer; cutoff, policy version or exchange rate is missing; the profile was built with a
different policy version than silver; the eligible share leaves 20–50%; the options are not one per
customer and grid row; any available option exceeds the 20% capacity, the band maximum term or its
amount range; a product with available options has not exactly one featured option; a
customer summary has duplicate customers; or the gold contract is broken.

### Gold contract for the API

`gold/90_quality_checks.sql` (check 10, `contract_violations`) fails the run if any of these columns
is missing or changes type. They are what the backend and `data/policy/credit_policy.py` read.

| Table | Columns (type) |
|---|---|
| `customer_credit_profile` | `customer_id`, `offer_mode`, `not_proactive_reason`, `risk_band`, `segment`, `local_currency`, `income_source`, `policy_version` (string); `is_eligible`, `requires_advisor_review`, `can_become_eligible_with_declared_income` (boolean); `reason_codes` (array<string>); `fx_to_usd`, `income_used_usd`, `current_installments_usd`, `max_total_installment_usd`, `available_installment_usd`, `total_rate_adjustment_pp` (double); `max_term_personal_loan_months`, `max_term_mortgage_months` (int); `open_complaints`, `open_priority_complaints`, `open_critical_complaints` (bigint); `fx_date`, `as_of_date` (date) |
| `customer_credit_offer_options` | `customer_id`, `option_code`, `product_code`, `product_type`, `tier`, `unavailable_reason`, `offer_mode`, `local_currency` (string); `term_months`, `option_min_amount_usd`, `option_max_amount_usd` (int); `is_available`, `is_featured` (boolean); `offer_max_amount_usd` (bigint); `offer_rate_pct`, `offer_monthly_installment_usd`, `offer_max_amount_local`, `offer_monthly_installment_local`, `fx_to_usd` (double) |

Adding columns is safe; renaming, dropping or retyping one of these needs a coordinated change.

### Update correctness on static data (test fixture)

The data is static, so the job `data_update_fixture_test` shows that a new delivery is handled
correctly. It copies a bronze sample to `*_fixture` schemas, appends a **labeled test delivery**
(`_source_file_path = 'fixture://update-correctness/<case>'`), runs the production `02_silver.sql`
and `02_silver_quality_checks.sql` unchanged, and asserts each case
(`tests/00_update_fixture_setup.sql`, `tests/99_update_fixture_assertions.sql`):

| Case | Delivery | Expected and observed |
|---|---|---|
| Late status update | An existing complaint arrives again 5 days later as `Resolved` | Silver keeps one row, `Resolved` |
| Exact duplicate | A transaction delivered twice | Bronze 2 rows, silver 1; `key_duplicates_removed_share` > 0 (ok) |
| Late arrival | A complaint created in 2024 arrives with the June 2026 delivery | Present in silver with its 2024 `creation_date` |
| Schema change | A row with an unknown column (`_rescued_data`) | Loaded to silver; `rescued_rows` = 1 (warn) |
| Null key | A transaction without `transaction_id` | Dropped in silver; `null_key_rows` = 1 (warn) |

All five pass; run against a silver without the fixture delivery, the assertions fail as expected.

## Jobs (Databricks Asset Bundle)

The bundle in this folder (`databricks.yml`, `resources/`) defines three jobs. Schema parameters
default to the target's variables (`dev` → `_test`, `prod` → real schemas).

| Job | Tasks | Trigger |
|---|---|---|
| `latam_bank_medallion` | `bronze_load` → `silver_typed_dedup` → `silver_quality_checks` → `gold_deploy_objects` → `gold_customer_credit_profile` → `gold_customer_credit_offer_options`; the three customer summaries in parallel after the silver checks; `gold_quality_checks` → `gold_export_for_serving` last | Daily at 06:00 America/Bogota, deployed **paused** (static data: run by hand) |
| `credit_policy_refresh` | `gold_customer_credit_profile` → `gold_customer_credit_offer_options` → `gold_quality_checks` → `gold_export_for_serving` | When the policy changes: by hand, or the (paused) `table_update` trigger on the policy `ref_*` tables |
| `credit_gold_deploy` | `gold_deploy_objects` | Manual, once per deploy |
| `data_update_fixture_test` | `fixture_setup` → `silver_typed_dedup` → `silver_quality_checks` → `fixture_assertions`, on the `*_fixture` schemas | Manual; shows update correctness on static data |

- **Parameter `as_of_date`** (`YYYY-MM-DD`): empty uses the policy cutoff in
  `ref_policy_params` (2026-06-30 for the static hackathon data). With live data, set its
  default to `{{job.start_time.iso_date}}`.
- **Retries and limits:** one retry per build task, task and job timeouts, one concurrent run.

```bash
cd data/databricks
databricks bundle validate -t dev --profile <profile> --var="warehouse_id=<id>"
databricks bundle deploy   -t dev --profile <profile> --var="warehouse_id=<id>"
databricks bundle run latam_bank_medallion  -t dev --profile <profile> --var="warehouse_id=<id>"
databricks bundle run credit_policy_refresh -t dev --profile <profile> --var="warehouse_id=<id>"
# one-off rebuild as of another date
databricks bundle run credit_policy_refresh -t dev --profile <profile> --var="warehouse_id=<id>" --params as_of_date=2026-05-31
```

`dev` prefixes the jobs with `[dev <user>]` and keeps schedules and triggers paused. Before using
the `prod` target: set `run_as` to a service principal, add failure notifications
(`email_notifications.on_failure` or a webhook) and unpause the schedule.

## Manual run order (without the bundle)

```bash
pip install -r data/scripts/requirements.txt
databricks auth login --host <workspace-url> --profile <profile>
S="--param bronze_schema=workspace.bronze_latam_bank_test --param silver_schema=workspace.silver_latam_bank_test \
   --param gold_schema=workspace.gold_latam_bank_test --param run_id= --param as_of_date="

# 1. bronze: run data/databricks/01_bronze.py as a notebook (widget bronze_schema)
#    (needs the daily CSVs in /Volumes/workspace/staging_latam_bank/landing/<table>/)
# 2. silver reference tables (rerun when a CSV in data/reference changes)
python data/scripts/load_reference.py --silver-schema workspace.silver_latam_bank_test --profile <profile> --warehouse-id <id>
# 3. silver and its quality gate
python data/scripts/run_databricks_sql.py data/databricks/02_silver.sql data/databricks/02_silver_quality_checks.sql $S --profile <profile> --warehouse-id <id>
# 4. gold objects, tables and checks
python data/scripts/run_databricks_sql.py data/databricks/gold/00_deploy_objects.sql \
    data/databricks/gold/10_customer_credit_profile.sql data/databricks/gold/20_customer_credit_offer_options.sql \
    data/databricks/gold/30_customer_products_summary.sql data/databricks/gold/31_customer_complaints_summary.sql \
    data/databricks/gold/32_customer_cashflow_summary.sql data/databricks/gold/90_quality_checks.sql \
    $S --profile <profile> --warehouse-id <id>
```

The SQL files can also be opened in the SQL editor, which asks for the parameter values.

## Export for the demo backend

The backend reads Parquet instead of querying Databricks (no credentials in the container). The
export is part of the pipeline: the last task of `latam_bank_medallion` and `credit_policy_refresh`
(`gold/95_export_for_serving.py`) writes it to the volume `<gold_schema>.exports` only after the gold
checks pass, so the demo always serves validated data:

```
/Volumes/workspace/gold_latam_bank/exports/
  customer_credit_profile/  customer_credit_offer_options/  ref_*/   one Parquet file each
  _manifest.json            rows per table, as_of_date, policy_version, run id, export time
```

The task checks that every exported table has the same row count as its source. Download it for
the demo and check an engine against it:

```bash
python data/scripts/export_gold.py --profile <profile>     # -> .local/gold/ (git-ignored)
python data/scripts/check_engine_parity.py                 # engine vs gold options
```

`data/policy/credit_policy.py` is a reference implementation of the policy that matches gold on
all options; see `docs/ENGINE_ALIGNMENT.md` for the backend changes.

## One-time migration notes

- The customer summaries used to be views (`gold_customer_*_summary`). `CREATE OR REPLACE TABLE`
  cannot replace a view: drop the old views once in each gold schema
  (`DROP VIEW IF EXISTS <gold_schema>.gold_customer_products_summary`, same for
  `complaints`, `cashflow` and `credit_features`).
- Before the first run against the real schemas: the old silver `customers`, `products` and
  `daily_exchange_rates` were built by the ingestion pipeline (SCD2 with `__END_AT`) and
  `silver_transactions` was a manual table. `02_silver.sql` replaces the first three with typed,
  deduplicated tables; drop them first if the pipeline still manages them, and drop
  `silver_transactions` once nothing reads it.

## Results as of the 2026-06-30 cutoff (policy 0.4)
- 150,000 customers; 50,707 eligible; 24,953 `proactive`, 25,754 `on_customer_interest`.
  A run on the test schemas must give the same numbers.
- Main reasons for no offer: missing income 30,033 (recoverable by asking the customer),
  blocked or suspended product 25,519, missing score 22,492, inactive customer 22,300.
- Band term limits: eligible customers without any personal loan option dropped from 10,772
  (policy 0.2 grid) to 5,319; no option exceeds the band maximum term or the 20% capacity.
- SQL and Python annuity results match (40,000 USD at 6.2% over 180 months: 341.88 per month).
- Building the profile, options and checks takes about 50 seconds on the serverless starter
  warehouse; with `as_of_date=2026-05-31` it yields 50,110 eligible customers.
