-- =============================================================================================
-- customer_products_summary: one row per customer with product counts, active credit
-- limit and balance in USD, credit interest rate and delinquency.
-- Task of the latam_bank_medallion job; runs after silver, in parallel with the credit tables.
-- Descriptive per-customer summary (not used by the credit rules). Reads the typed, deduplicated
-- silver from 02_silver.sql (and silver ref_product_catalog). Parameters :silver_schema and
-- :gold_schema (catalog.schema).
-- One-time migration: if the table still exists as a VIEW from an earlier run, drop it first
-- (DROP VIEW IF EXISTS <gold_schema>.<table>); CREATE OR REPLACE TABLE cannot replace a view.
-- =============================================================================================

CREATE SCHEMA IF NOT EXISTS IDENTIFIER(:gold_schema);

CREATE OR REPLACE TABLE IDENTIFIER(:gold_schema || '.customer_products_summary') AS
WITH fx AS (
    SELECT
        source_currency,
        target_currency,
        date AS rate_date,
        exchange_rate
    FROM IDENTIFIER(:silver_schema || '.daily_exchange_rates')
),
products_typed AS (
    SELECT
        p.product_id,
        p.customer_id,
        p.product_type,                       -- raw Spanish label, kept for display
        rpc.product_type AS product_type_en,   -- English label via official mapping
        p.product_status,
        p.currency,
        p.current_balance,
        p.credit_limit,
        p.interest_rate,
        p.days_past_due,
        p.last_updated
    FROM IDENTIFIER(:silver_schema || '.products') p
    LEFT JOIN IDENTIFIER(:silver_schema || '.ref_product_catalog') rpc
        ON rpc.source_product_type = p.product_type
),
products_usd AS (
    SELECT
        pt.*,
        CASE WHEN pt.currency = 'USD' THEN pt.current_balance
             ELSE pt.current_balance * fx.exchange_rate END AS current_balance_usd,
        CASE WHEN pt.currency = 'USD' OR pt.credit_limit IS NULL THEN pt.credit_limit
             ELSE pt.credit_limit * fx.exchange_rate END AS credit_limit_usd
    FROM products_typed pt
    LEFT JOIN fx
        ON fx.source_currency = pt.currency
       AND fx.target_currency = 'USD'
       AND fx.rate_date = LEAST(pt.last_updated, DATE '2026-06-17')
)
SELECT
    customer_id,
    COUNT(*) AS total_products,
    COUNT(*) FILTER (WHERE product_status = 'Active') AS active_products,
    ARRAY_JOIN(COLLECT_SET(product_type), ', ') AS product_types,
    SUM(credit_limit_usd) FILTER (WHERE product_status = 'Active') AS total_credit_limit_usd,
    SUM(current_balance_usd) FILTER (WHERE product_status = 'Active') AS total_current_balance_usd,
    ROUND(AVG(interest_rate) FILTER (
        WHERE product_type_en IN ('Credit Card', 'Personal Loan', 'Mortgage')
    ), 2) AS avg_credit_interest_rate,
    MAX(days_past_due) AS max_days_past_due,
    ROUND(AVG(days_past_due), 1) AS avg_days_past_due,
    MAX(CASE WHEN days_past_due > 30 THEN 1 ELSE 0 END) AS has_delinquent_product,
    MAX(CASE WHEN product_type_en IN ('Credit Card', 'Personal Loan', 'Mortgage')
             THEN 1 ELSE 0 END) AS has_credit_product
FROM products_usd
GROUP BY customer_id;
