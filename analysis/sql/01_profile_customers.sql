-- customers profile: volume, duplicates and nulls in the credit columns
SELECT
    count(*)                                              AS row_count,
    count(DISTINCT customer_id)                           AS unique_customers,
    count(*) - count(DISTINCT customer_id)                AS repeated_rows,
    round(100.0 * avg((credit_score IS NULL)::int), 2)    AS pct_score_null,
    round(100.0 * avg((estimated_monthly_income IS NULL)::int), 2) AS pct_income_null
FROM raw_customers;

-- Score distribution by country, on the latest version of each customer
WITH latest AS (
    SELECT * FROM raw_customers
    QUALIFY row_number() OVER (PARTITION BY customer_id ORDER BY last_updated DESC) = 1
)
SELECT
    country,
    count(*)                                   AS customers,
    round(100.0 * avg((customer_status = 'Active')::int), 1) AS pct_active,
    round(100.0 * avg(accepts_marketing::int), 1)            AS pct_accepts_marketing,
    quantile_cont(credit_score, 0.10)::int     AS score_p10,
    quantile_cont(credit_score, 0.50)::int     AS score_p50,
    quantile_cont(credit_score, 0.90)::int     AS score_p90,
    round(quantile_cont(estimated_monthly_income, 0.50)) AS income_local_p50
FROM latest
GROUP BY country
ORDER BY country;

-- Size of each score band (provisional cutoffs from docs/CREDIT_RULES.md)
WITH latest AS (
    SELECT * FROM raw_customers
    QUALIFY row_number() OVER (PARTITION BY customer_id ORDER BY last_updated DESC) = 1
),
bands AS (
    SELECT
        country,
        CASE WHEN credit_score >= 740 THEN 'A'
             WHEN credit_score >= 680 THEN 'B'
             WHEN credit_score >= 620 THEN 'C'
             WHEN credit_score >= 560 THEN 'D'
             WHEN credit_score IS NULL THEN 'no score'
             ELSE 'E' END AS band,
        count(*) AS customers
    FROM latest
    GROUP BY ALL
)
SELECT
    country,
    band,
    customers,
    round(100.0 * customers / sum(customers) OVER (PARTITION BY country), 1) AS pct_of_country
FROM bands
ORDER BY country, band;
