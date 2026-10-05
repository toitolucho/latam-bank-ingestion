-- Does delinquency increase from band A to E? If not, the score cutoffs are wrong.
-- Delinquency = any snapshot more than 30 days past due on a credit product.
WITH customers AS (
    SELECT customer_id, country, credit_score FROM raw_customers
    QUALIFY row_number() OVER (PARTITION BY customer_id ORDER BY last_updated DESC) = 1
),
delinquency AS (
    SELECT customer_id, max(coalesce(days_past_due, 0)) AS max_days_past_due
    FROM raw_products
    WHERE product_type IN ('Tarjeta Crédito', 'Préstamo Personal', 'Préstamo Hipotecario')
    GROUP BY customer_id
)
SELECT
    c.country,
    CASE WHEN c.credit_score >= 740 THEN 'A'
         WHEN c.credit_score >= 680 THEN 'B'
         WHEN c.credit_score >= 620 THEN 'C'
         WHEN c.credit_score >= 560 THEN 'D'
         WHEN c.credit_score IS NULL THEN 'no score'
         ELSE 'E' END                                        AS band,
    count(*)                                                 AS customers_with_credit,
    round(100.0 * avg((d.max_days_past_due > 30)::int), 1)   AS pct_dpd_30,
    round(100.0 * avg((d.max_days_past_due > 90)::int), 1)   AS pct_dpd_90
FROM delinquency d
JOIN customers c USING (customer_id)
GROUP BY ALL
ORDER BY c.country, band;
