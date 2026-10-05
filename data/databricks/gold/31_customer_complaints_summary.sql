-- =============================================================================================
-- customer_complaints_summary: one row per customer with complaint counts by type, status
-- and priority, SLA breaches and claimed/compensated amounts in USD. creation_date is a TIMESTAMP
-- in silver and is cast to DATE for the exchange rate join.
-- Task of the latam_bank_medallion job; runs after silver, in parallel with the credit tables.
-- Descriptive per-customer summary (not used by the credit rules). Reads the typed, deduplicated
-- silver from 02_silver.sql. Parameters :silver_schema and :gold_schema (catalog.schema).
-- One-time migration: if the table still exists as a VIEW from an earlier run, drop it first
-- (DROP VIEW IF EXISTS <gold_schema>.<table>); CREATE OR REPLACE TABLE cannot replace a view.
-- =============================================================================================

CREATE SCHEMA IF NOT EXISTS IDENTIFIER(:gold_schema);

CREATE OR REPLACE TABLE IDENTIFIER(:gold_schema || '.customer_complaints_summary') AS
WITH fx AS (
    SELECT
        source_currency, target_currency,
        date AS rate_date,
        exchange_rate
    FROM IDENTIFIER(:silver_schema || '.daily_exchange_rates')
),
complaints_usd AS (
    SELECT
        c.*,
        CASE WHEN c.currency = 'USD' OR c.claimed_amount IS NULL THEN c.claimed_amount
             ELSE c.claimed_amount * fx_claim.exchange_rate END AS claimed_amount_usd,
        CASE WHEN c.currency = 'USD' OR c.compensation_granted IS NULL THEN c.compensation_granted
             ELSE c.compensation_granted * fx_comp.exchange_rate END AS compensation_granted_usd
    FROM IDENTIFIER(:silver_schema || '.complaints') c
    LEFT JOIN fx fx_claim
        ON fx_claim.source_currency = c.currency AND fx_claim.target_currency = 'USD'
       AND fx_claim.rate_date = LEAST(CAST(c.creation_date AS DATE), DATE '2026-06-17')
    LEFT JOIN fx fx_comp
        ON fx_comp.source_currency = c.currency AND fx_comp.target_currency = 'USD'
       AND fx_comp.rate_date = LEAST(COALESCE(c.resolution_date, CAST(c.creation_date AS DATE)), DATE '2026-06-17')
)
SELECT
    customer_id,
    COUNT(*) AS total_complaints,
    COUNT(*) FILTER (WHERE case_type = 'Claim') AS total_claims,
    COUNT(*) FILTER (WHERE case_type = 'Complaint') AS total_complaints_only,
    COUNT(*) FILTER (WHERE case_type = 'Request') AS total_requests,
    COUNT(*) FILTER (WHERE case_type = 'Suggestion') AS total_suggestions,
    COUNT(*) FILTER (WHERE status IN ('Open', 'In Process', 'Escalated')) AS open_cases,
    COUNT(*) FILTER (WHERE status IN ('Resolved', 'Closed')) AS resolved_cases,
    COUNT(*) FILTER (WHERE status = 'Rejected') AS rejected_cases,
    COUNT(*) FILTER (WHERE priority = 'Critical') AS critical_cases,
    COUNT(*) FILTER (
        WHERE priority IN ('High', 'Critical') AND status IN ('Open', 'In Process', 'Escalated')
    ) AS open_priority_cases,
    COUNT(*) FILTER (WHERE sla_breached) AS sla_breaches,
    COUNT(*) FILTER (WHERE is_repeat_complainer) AS repeat_complaint_flags,
    SUM(claimed_amount_usd) AS total_claimed_amount_usd,
    SUM(compensation_granted_usd) AS total_compensation_granted_usd,
    AVG(resolution_days) AS avg_resolution_days,
    MAX(resolution_days) AS max_resolution_days,
    AVG(resolution_satisfaction) AS avg_resolution_satisfaction,
    (COUNT(*) FILTER (WHERE sla_breached) > 0) AS has_sla_breach,
    (COUNT(*) FILTER (WHERE priority = 'Critical') > 0) AS has_critical_complaint,
    (COUNT(*) FILTER (
        WHERE priority IN ('High', 'Critical') AND status IN ('Open', 'In Process', 'Escalated')
    ) > 0) AS has_open_priority_complaint
FROM complaints_usd
GROUP BY customer_id;
