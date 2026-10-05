-- products profile: monthly snapshots, so a product appears several times
SELECT
    count(*)                                   AS row_count,
    count(DISTINCT product_id)                 AS unique_products,
    count(DISTINCT customer_id)                AS customers_with_product,
    min(last_updated)                          AS first_update,
    max(last_updated)                          AS last_update
FROM raw_products;

-- Products by type and status, on the latest version of each product
WITH latest AS (
    SELECT * FROM raw_products
    QUALIFY row_number() OVER (PARTITION BY product_id ORDER BY last_updated DESC) = 1
)
SELECT
    product_type,
    currency,
    count(*)                                              AS products,
    round(100.0 * avg((product_status = 'Active')::int), 1) AS pct_active,
    round(100.0 * avg((interest_rate IS NULL)::int), 1)   AS pct_no_rate,
    round(100.0 * avg((days_past_due IS NULL)::int), 1)   AS pct_no_delinquency_reported
FROM latest
GROUP BY ALL
ORDER BY product_type, currency;
