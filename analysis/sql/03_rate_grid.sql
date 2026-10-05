-- Actual rate grid by country and credit product type.
-- Finding: rates are uniform per product type and identical across countries (see README).
WITH customers AS (
    SELECT customer_id, country FROM raw_customers
    QUALIFY row_number() OVER (PARTITION BY customer_id ORDER BY last_updated DESC) = 1
),
products AS (
    SELECT * FROM raw_products
    QUALIFY row_number() OVER (PARTITION BY product_id ORDER BY last_updated DESC) = 1
)
SELECT
    c.country,
    p.product_type,
    count(*)                                       AS products,
    round(quantile_cont(p.interest_rate, 0.10), 2) AS floor_p10,
    round(quantile_cont(p.interest_rate, 0.25), 2) AS band_a_p25,
    round(quantile_cont(p.interest_rate, 0.40), 2) AS band_b_p40,
    round(quantile_cont(p.interest_rate, 0.50), 2) AS band_c_p50,
    round(quantile_cont(p.interest_rate, 0.75), 2) AS band_d_p75,
    round(quantile_cont(p.interest_rate, 0.90), 2) AS ceiling_p90
FROM products p
JOIN customers c USING (customer_id)
WHERE p.product_type IN ('Tarjeta Crédito', 'Préstamo Personal', 'Préstamo Hipotecario')
  AND p.product_status = 'Active'
  AND p.interest_rate IS NOT NULL
GROUP BY ALL
ORDER BY c.country, p.product_type;
