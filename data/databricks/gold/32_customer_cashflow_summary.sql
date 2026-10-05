-- =============================================================================================
-- customer_cashflow_summary: one row per customer with approved transactions in the last
-- 90 days of data (deposits, expenses, transfers, adjustments in USD) and recent fraud flags.
-- Task of the latam_bank_medallion job; runs after silver, in parallel with the credit tables.
-- Descriptive per-customer summary (not used by the credit rules). Reads the typed, deduplicated
-- silver from 02_silver.sql. Parameters :silver_schema and :gold_schema (catalog.schema).
-- One-time migration: if the table still exists as a VIEW from an earlier run, drop it first
-- (DROP VIEW IF EXISTS <gold_schema>.<table>); CREATE OR REPLACE TABLE cannot replace a view.
-- =============================================================================================

CREATE SCHEMA IF NOT EXISTS IDENTIFIER(:gold_schema);

CREATE OR REPLACE TABLE IDENTIFIER(:gold_schema || '.customer_cashflow_summary') AS
WITH fx AS (
    SELECT
        source_currency, target_currency,
        date AS rate_date,
        exchange_rate
    FROM IDENTIFIER(:silver_schema || '.daily_exchange_rates')
),
snapshot AS (
    SELECT MAX(process_date) AS as_of_date
    FROM IDENTIFIER(:silver_schema || '.transactions')
),
tx_usd AS (
    SELECT
        t.transaction_id, t.customer_id, t.transaction_type,
        t.transaction_status, t.process_date, t.is_fraud,
        CASE WHEN t.currency = 'USD' THEN t.amount
             ELSE COALESCE(t.amount_usd, t.amount * fx.exchange_rate) END AS amount_usd_final
    FROM IDENTIFIER(:silver_schema || '.transactions') t
    LEFT JOIN fx
        ON fx.source_currency = t.currency
       AND fx.target_currency = 'USD'
       AND fx.rate_date = LEAST(CAST(t.transaction_date AS DATE), DATE '2026-06-17')
),
tx_recent AS (
    SELECT tu.*
    FROM tx_usd tu
    CROSS JOIN snapshot s
    WHERE tu.transaction_status = 'Approved'
      AND tu.process_date > DATE_SUB(s.as_of_date, 90)
)
SELECT
    customer_id,
    COUNT(*) AS total_transactions_90d,
    SUM(CASE WHEN transaction_type = 'Deposit' THEN amount_usd_final ELSE 0 END) AS total_income_usd_90d,
    SUM(CASE WHEN transaction_type IN ('Withdrawal', 'Payment', 'Purchase') THEN amount_usd_final ELSE 0 END) AS total_expense_usd_90d,
    SUM(CASE WHEN transaction_type = 'Transfer' THEN amount_usd_final ELSE 0 END) AS total_transfer_usd_90d,
    SUM(CASE WHEN transaction_type = 'Adjustment' THEN amount_usd_final ELSE 0 END) AS total_adjustment_usd_90d,
    ROUND(AVG(amount_usd_final), 2) AS avg_transaction_amount_usd,
    COUNT(*) FILTER (WHERE is_fraud) AS fraud_flags_90d,
    (COUNT(*) FILTER (WHERE is_fraud) > 0) AS has_recent_fraud
FROM tx_recent
GROUP BY customer_id;
