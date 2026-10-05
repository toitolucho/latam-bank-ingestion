-- Observed credit product catalog: what customers hold today, by country and product type.
-- Source: active products only (product_status = 'Active'), credit scope products only.
-- Amounts: credit_limit (card limit / loan amount) converted to USD with the latest
-- available exchange rate (daily_exchange_rates ends 2026-06-17), then back to local currency.
-- Term is not derivable: loans have no expiration_date, and card expiration is card validity.
WITH customers AS (
    SELECT customer_id, any_value(country) AS country
    FROM raw_customers
    GROUP BY customer_id
),
fx_latest AS (
    SELECT source_currency AS currency, arg_max(exchange_rate, date) AS to_usd
    FROM raw_daily_exchange_rates
    WHERE target_currency = 'USD'
    GROUP BY source_currency
    UNION ALL
    SELECT 'USD', 1.0
),
local_currency AS (
    SELECT * FROM (VALUES ('México', 'MXN'), ('Colombia', 'COP'), ('Argentina', 'ARS')) t(country, currency)
),
active AS (
    SELECT
        c.country,
        p.product_type,
        p.customer_id,
        p.currency,
        p.interest_rate,
        p.credit_limit * fx.to_usd AS amount_usd
    FROM raw_products p
    JOIN customers c USING (customer_id)
    JOIN fx_latest fx ON fx.currency = p.currency
    WHERE p.product_type IN ('Tarjeta Crédito', 'Préstamo Personal', 'Préstamo Hipotecario')
      AND p.product_status = 'Active'
)
SELECT
    a.country,
    a.product_type,
    lc.currency                                         AS local_currency,
    count(*)                                            AS active_products,
    count(DISTINCT a.customer_id)                       AS customers,
    round(100.0 * avg((a.currency = 'USD')::int), 1)    AS pct_usd_denominated,
    round(min(a.interest_rate), 2)                      AS rate_min,
    round(quantile_cont(a.interest_rate, 0.50), 2)      AS rate_p50,
    round(max(a.interest_rate), 2)                      AS rate_max,
    round(min(a.amount_usd))                            AS amount_usd_min,
    round(quantile_cont(a.amount_usd, 0.50))            AS amount_usd_p50,
    round(max(a.amount_usd))                            AS amount_usd_max,
    round(min(a.amount_usd) / fxl.to_usd)               AS amount_local_min,
    round(quantile_cont(a.amount_usd, 0.50) / fxl.to_usd) AS amount_local_p50,
    round(max(a.amount_usd) / fxl.to_usd)               AS amount_local_max
FROM active a
JOIN local_currency lc USING (country)
JOIN fx_latest fxl ON fxl.currency = lc.currency
GROUP BY a.country, a.product_type, lc.currency, fxl.to_usd
ORDER BY a.product_type, a.country;
