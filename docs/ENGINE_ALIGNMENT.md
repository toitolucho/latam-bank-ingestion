# Aligning the backend credit engine to policy 0.4

The backend engine (`backend/app/policy/credit_engine.py` + `backend/policy/credit_policy.yaml`)
was built on a preliminary version of the credit rules so the team could work in parallel.
Policy 0.4 (`docs/CREDIT_RULES.md`, parameters in `data/reference/`) is the reference version,
already computed in Databricks gold. This guide lists what the backend needs so the agent offers
exactly what gold computes, and the tools that are ready to help.

## What is ready

| Piece | Where | Status |
|---|---|---|
| Gold profile and offer options (150,000 customers, 1.8M options) | `workspace.gold_latam_bank` | Built with policy 0.4 |
| Parquet export of gold + `ref_*` for serving | Written by the jobs to `workspace.gold_latam_bank.exports` (`gold/95_export_for_serving.py`); `data/scripts/export_gold.py` downloads it to `.local/gold/` (git-ignored) | Production export available (2026-06-30 cutoff, policy 0.4) |
| Reference implementation of the policy in Python | `data/policy/credit_policy.py` | Matches gold on all 1.8M options, including `is_featured` |
| Parity check for any engine | `data/scripts/check_engine_parity.py` | 0 mismatches for the reference |
| Agent view of the profile (25 contract columns, one row per customer) | `workspace.gold_latam_bank.customer_credit_offer_context` | Rebuilt with the profile |
| Unit tests on the worked example (no organizer data) | `data/policy/test_credit_policy.py` | 15 passing |

The reference module is standard library only and pure: `load_policy()`, `offer_options()`,
`recalculate()` and `build_credit_offer()`. It can be imported by the backend or used as an
executable spec.

```bash
python data/scripts/export_gold.py --profile <profile>     # download the export
python data/scripts/check_engine_parity.py                 # reference engine vs gold
pytest data/policy                                         # worked example
```

## Differences to close

| Topic | Backend today | Policy 0.4 |
|---|---|---|
| Bands | 5 bands from score 520 (`score_bands`), spread +6 to −2 | A–E at 740/680/620/560 (`ref_policy_bands`), −2 to +2 pp, plus segment −1 to +1 pp |
| Rate | Base rate per product (20 / 31.5 / 9) + band spread − 1 pp with 3+ products | `ref_term_grid` rate per term or card tier + band + segment, clamped to the product range |
| Products | Personal loan and mortgage; credit card handed off | Credit card offered by tier (Classic, Gold, Platinum, Black) |
| Terms | Fixed: personal 36, mortgage 180 | Any term in the grid up to the band maximum (personal A/B 60, C 48, D 36; mortgage A/B 360, C 300, D 240 months) |
| Amount | `max_amount` for the requested term | Each grid option is an alternative using the whole capacity; loans span 5,000–150,000 USD |
| 20% limit | `max_dti` 0.20 plus a 10% borderline margin to review | 0.20 hard limit, no margin; above it there is no offer |
| Existing debt | Card 5% of balance; loans 36/180 months on balance | From gold `current_installments_usd` (grid term on original amount; cards over 60 months) |
| Hard filters | Status, missing data, delinquency 30/90 | R01–R08 in gold `reason_codes`; only R05 (income) and R08 (capacity) change with chat data |
| Declared income | Uplift above 50% goes to review | Replaces income used; offer conditional with `F03`; no uplift handoff |
| Household income | Not asked | Ask every customer (not by marital status); when added, also ask that person's installments and pass both to `recalculate(additional_income_usd=..., external_installments_usd=...)` |
| Age | Not used | Term capped so loans end before 75 (`max_term_*` in the profile already include it) |
| Proactive offer | Consent + moment + not pre-approved on declared income | Same, but eligibility and mode from gold `offer_mode` (`proactive` only with consent and no open critical complaint) |
| Currency | Income currency (local) | USD internally (`fx_to_usd`); local only for display |
| Flags | — | `F02_NEAR_LIMIT_DECLARED_INCOME`, `F03_DECLARED_DATA`, `F04_OPEN_COMPLAINTS` |

## Reading the data: Databricks first, Parquet as fallback

The options do not need to be downloaded: they are computed from one profile row and the five
small `ref_*` tables, in milliseconds and identical to gold.

```
at startup:          SELECT * FROM <silver>.ref_*                          -> memory
at authentication:   SELECT * FROM <gold>.customer_credit_offer_context
                     WHERE customer_id = :id                               -> 1 row
in the chat:         offer_options() / recalculate() in memory
on acceptance:       INSERT INTO <gold>.credit_offers
```

| | Query Databricks | Parquet export |
|---|---|---|
| Data | Always current | Snapshot of the last job |
| Credentials in the container | Service principal token in `backend/.env` | None |
| Warehouse asleep or no network | First query takes a few seconds; fails without network | Works offline |
| Jury clones the repo and runs the demo | Not possible without workspace access | Possible with the sample set |

Use both: Databricks when credentials are set, and the Parquet export (or the sample set) as the
automatic fallback, so the demo keeps working if Databricks does not answer (the brief asks for a
safe fallback). The repository interface in the backend already allows swapping the source.

## Changes by file

1. **Data (`backend/scripts/build_snapshot.py`, `app/data/repository.py`).** Join the snapshot
   customers with the downloaded export (`.local/gold/customer_credit_profile/`, a Parquet folder) instead of
   `.local/derived/gold_customer_credit_profile.parquet`, and keep the offer options of the
   sampled customers. `credit_profile()` returns the gold profile row (USD) instead of
   `monthly_income` / `existing_monthly_debt` in local currency.
2. **Policy (`app/policy/`).** Replace `credit_engine.evaluate` and `credit_policy.yaml` with the
   reference module, or port it. If the Docker build context stays `backend/`, copy
   `data/policy/credit_policy.py` and `data/reference/*.csv` into the image (or move the build
   context to the repository root).
3. **Tools (`app/agent/tools.py`).** Three tools, none taking `customer_id`:
   - `get_offers()`: gold options for the session customer, gated by `offer_mode`
     (`on_customer_interest` only after the customer asks about credit). Present the
     `is_featured` option of each product first (the highest; see CREDIT_RULES section 7) and
     keep the rest as alternatives;
   - `recalculate_offer(declared_income, additional_income, external_installments, product,
     amount, term)`: converts local amounts with `fx_to_usd`, calls `recalculate()`;
   - `accept_offer(option_code, term_months, amount)`: recomputes, calls `build_credit_offer()`
     (which rejects amounts outside the option or above 20% and adds `F02`), writes the row, and
     hands off to an advisor.
4. **Orchestrator and templates.** Add `credit_card` (tiers) to the supported products; use the
   allowed terms per band instead of `DEFAULT_MONTHS`; present amounts in local currency; replace
   the `INCOME_UPLIFT_REVIEW` path with a conditional offer (`F03`).
5. **Handoff summary (`app/agent/handoff.py`).** Include `offer_id`, option, amount, rate,
   installment, `debt_to_income_after`, flags, open complaints and `policy_version`.
6. **Fixture and tests.** `make_fixture.py` must generate the gold profile columns for its
   team-made customers. `test_credit_engine.py` (9 tests) is replaced by the policy 0.4 cases;
   `test_proactive.py` keeps its behavior with the new eligibility source.

## Writing accepted offers

`build_credit_offer()` returns exactly the columns of `gold_latam_bank.credit_offers`
(`data/databricks/gold/00_deploy_objects.sql`). The table has CHECK constraints on status,
origin, positive amounts and the 20% limit, so an invalid row is rejected by Databricks too.
Two ways to get rows there from the demo:

- **A. Local + sync (no credentials in the container):** the API appends rows to a local file
  (e.g. `.local/credit_offers.jsonl`) and a script inserts them into Databricks.
- **B. Direct:** the API inserts through a SQL warehouse with a service principal token passed as
  an environment variable.

## Done when

- [ ] `check_engine_parity.py --engine <backend function>` reports 0 mismatches.
- [ ] Backend tests pass with the policy 0.4 cases; CI green.
- [ ] Demo shows a proactive offer equal to gold, a recalculation with declared income, an
      accepted offer recorded in `credit_offers`, and the advisor handoff with flags.
