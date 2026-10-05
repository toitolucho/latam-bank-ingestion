-- Interest rate ranges by country, product type and currency.
-- product_type values are raw Spanish labels; country comes from customers.
-- Products with null interest_rate (~10%) are excluded from the percentiles.
WITH customers AS (
    SELECT customer_id, any_value(country) AS country
    FROM raw_customers
    GROUP BY customer_id
)
SELECT
    c.country,
    p.product_type,
    p.currency,
    count(*)                                       AS products,
    count(p.interest_rate)                         AS with_rate,
    round(min(p.interest_rate), 2)                 AS rate_min,
    round(quantile_cont(p.interest_rate, 0.10), 2) AS rate_p10,
    round(quantile_cont(p.interest_rate, 0.25), 2) AS rate_p25,
    round(quantile_cont(p.interest_rate, 0.50), 2) AS rate_p50,
    round(quantile_cont(p.interest_rate, 0.75), 2) AS rate_p75,
    round(quantile_cont(p.interest_rate, 0.90), 2) AS rate_p90,
    round(max(p.interest_rate), 2)                 AS rate_max
FROM raw_products p
JOIN customers c USING (customer_id)
WHERE p.product_type IN ('Tarjeta Crédito', 'Préstamo Personal', 'Préstamo Hipotecario')
GROUP BY ALL
ORDER BY c.country, p.product_type, p.currency;
