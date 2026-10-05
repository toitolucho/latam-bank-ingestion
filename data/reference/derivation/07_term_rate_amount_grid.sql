-- Derivation of data/reference/ref_term_grid.csv: reference rate and amount range per product
-- and term (credit cards per tier). The output is saved once as a STATIC reference table;
-- rerun only to deliberately regenerate it.
--
-- Country-agnostic and in USD: rates and amounts are the same across countries in the source
-- data, so the three countries are pooled. Local-currency amounts are computed at serving time
-- with the exchange rate of that day, never stored here.
--
-- SYNTHETIC RULE anchored on observed data: the source has no loan term and rates show no
-- relationship with amount, score or product age, so the structure is team-defined:
--   * loans: reference rate rises with term (term k of n takes the observed rate quantile
--     k/(n+1)); larger amounts map to longer terms (observed amounts split into n
--     equal-frequency slices, term k gets [q((k-1)/n), q(k/n)])
--   * credit cards: split into tiers (data/reference/ref_card_tiers.csv); each tier takes a slice of
--     the observed credit limits [limit_from_pct, limit_to_pct] and the observed rate at
--     rate_pct (higher tiers get lower rates)
-- Amounts: credit_limit of active products converted to USD at the latest exchange rate,
-- rounded to the nearest 1,000 USD and clamped to the catalog bounds. Rates rounded to one decimal.
WITH fx_latest AS (
    SELECT source_currency AS currency, arg_max(exchange_rate, date) AS to_usd
    FROM raw_daily_exchange_rates
    WHERE target_currency = 'USD'
    GROUP BY source_currency
    UNION ALL
    SELECT 'USD', 1.0
),
catalog AS (
    SELECT
        product_code, product_type, source_product_type,
        min_amount_usd::int AS catalog_min_usd,
        max_amount_usd::int AS catalog_max_usd,
        unnest(string_split(CAST(allowed_terms_months AS VARCHAR), '|'))::int AS term_months,
        len(string_split(CAST(allowed_terms_months AS VARCHAR), '|'))        AS n_terms
    FROM read_csv('data/reference/ref_product_catalog.csv', all_varchar = true)
),
catalog_ranked AS (
    SELECT *, row_number() OVER (PARTITION BY product_code ORDER BY term_months) AS term_rank
    FROM catalog
),
observed AS (
    SELECT
        p.product_type AS source_product_type,
        -- percentiles 0..100; element i + 1 holds percentile i
        quantile_cont(p.interest_rate,          [i / 100 for i in range(101)]) AS rate_pct,
        quantile_cont(p.credit_limit * fx.to_usd, [i / 100 for i in range(101)]) AS amount_pct
    FROM raw_products p
    JOIN fx_latest fx ON fx.currency = p.currency
    WHERE p.product_type IN ('Tarjeta Crédito', 'Préstamo Personal', 'Préstamo Hipotecario')
      AND p.product_status = 'Active'
    GROUP BY ALL
),
card_tiers AS (
    SELECT * FROM read_csv('data/reference/ref_card_tiers.csv')
),
positions AS (
    -- loans: one row per term
    SELECT
        k.*,
        NULL::varchar                                       AS tier,
        NULL::int                                           AS tier_rank,
        k.product_code                                      AS grid_code,
        round(100 * k.term_rank / (k.n_terms + 1))::int + 1 AS rate_idx,
        round(100 * (k.term_rank - 1) / k.n_terms)::int + 1 AS amount_lo_idx,
        round(100 * k.term_rank / k.n_terms)::int + 1       AS amount_hi_idx
    FROM catalog_ranked k
    WHERE k.product_type <> 'Credit Card'
    UNION ALL
    -- credit cards: one row per tier
    SELECT
        k.*,
        t.tier,
        t.tier_rank,
        k.product_code || '-' || t.tier_code,
        t.rate_pct + 1,
        t.limit_from_pct + 1,
        t.limit_to_pct + 1
    FROM catalog_ranked k
    CROSS JOIN card_tiers t
    WHERE k.product_type = 'Credit Card'
)
SELECT
    k.grid_code                                   AS product_code,
    k.product_type,
    k.tier,
    k.term_months,
    k.term_months // 12                           AS term_years,
    round(o.rate_pct[k.rate_idx], 1)              AS reference_rate_pct,
    -- clamp to the catalog bounds so rounding never exceeds them
    greatest(round(o.amount_pct[k.amount_lo_idx], -3)::int, k.catalog_min_usd) AS min_amount_usd,
    least(round(o.amount_pct[k.amount_hi_idx], -3)::int, k.catalog_max_usd)    AS max_amount_usd,
    true                                          AS is_synthetic
FROM positions k
JOIN observed o USING (source_product_type)
ORDER BY k.product_type, k.tier_rank, k.term_months;
