# Credit data exploration (DuckDB)

Profiling queries over the organizer CSVs, run locally in DuckDB with each table exposed as a
`raw_<table>` view. They support the decisions in `docs/CREDIT_RULES.md` and the synthetic
reference tables in `data/reference/`. Results are offline.

| File | Question |
|---|---|
| `01_profile_customers.sql` | Volume, nulls, score and income by country, size of each score band |
| `02_profile_products.sql` | Products by type, currency and status; missing rates and delinquency |
| `03_rate_grid.sql` | Observed rate percentiles by country and credit product |
| `04_delinquency_by_band.sql` | Does delinquency rise from band A to E? |
| `05_rate_ranges_by_country.sql` | Rate ranges by country, credit product and currency |

## Findings that shaped the design
- `customers` and `products` have one row per id (150,000 and 400,000): not monthly snapshots.
- `product_type` values are Spanish with accents (`Tarjeta Crédito`, `Préstamo Personal`,
  `Préstamo Hipotecario`); `country` uses `México` with an accent.
- Mexico has no MXN products: all 200,398 are in USD. Colombia and Argentina are ~90% local
  currency and ~10% USD.
- Rates are uniform within a fixed range per product type (personal loan 12–28%, credit card
  18–45%, mortgage 6–12%) and identical across countries and currencies.
- Rate and delinquency show no correlation with `credit_score` or income (|r| < 0.03), so the
  data has no risk-based pricing to learn from and the rate grid is synthetic.
- Loans have no `expiration_date`, so loan terms are synthetic.
- `credit_score` is missing for 15% of customers and `estimated_monthly_income` for 20%.
- Observed deposits are sparse (median under 2 per year per customer), so declared income is
  used for the 20% limit.
