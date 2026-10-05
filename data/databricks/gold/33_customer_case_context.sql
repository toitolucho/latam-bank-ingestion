-- =============================================================================================
-- customer_case_context: one row per customer and OPEN case, so the chat can acknowledge what is
-- still pending before anything else and hand the advisor a ready context.
--   * every complaint still open (Open / In Process / Escalated), with no time limit;
--   * every call-center interaction left unresolved in the last 90 days:
--     NOT was_resolved AND (requires_followup OR was_escalated).
-- An interaction that is the origin of a complaint is dropped: the complaint is the case.
-- Window and age are measured from :as_of_date, never from current_date(): the dataset is static
-- (it ends 2026-06-17) and a window anchored on today would be empty.
-- Parameter :as_of_date (YYYY-MM-DD); empty means the policy cutoff in silver ref_policy_params.
-- Parameters :silver_schema and :gold_schema (catalog.schema), as in the other gold files.
-- Descriptive only: not used by the credit rules.
--
-- Deliberately NOT carried over (the chat must not disclose account detail; see docs):
--   description, claimed_amount, compensation_granted, resolution, assigned_agent_id and the
--   interaction free fields (mentioned_products has an unconfirmed format in 02_silver.sql).
--
-- NOT wired into the latam_bank_medallion job yet: add it as a task after silver_quality_checks
-- (and to the depends_on of gold_quality_checks) once the migration to the real schemas has been
-- validated. Reference implementation for the local snapshot: backend/scripts/case_context.py
-- (keep both in sync).
-- =============================================================================================

CREATE SCHEMA IF NOT EXISTS IDENTIFIER(:gold_schema);

CREATE OR REPLACE TABLE IDENTIFIER(:gold_schema || '.customer_case_context')
COMMENT 'One row per customer and open case: complaints still open (any age) and call-center interactions unresolved in the last 90 days. Age measured from as_of_date. No amounts, descriptions or resolutions.'
AS
WITH params AS (
    SELECT
        coalesce(try_cast(nullif(:as_of_date, '') AS DATE),
                 max(CASE WHEN param_name = 'as_of_date' THEN CAST(param_value AS DATE) END)) AS as_of_date,
        90 AS window_days
    FROM IDENTIFIER(:silver_schema || '.ref_policy_params')
),
open_complaints AS (
    SELECT
        c.customer_id,
        'complaint'                                   AS case_source,
        c.complaint_id                                AS case_id,
        CAST(c.creation_date AS DATE)                 AS opened_on,
        c.reception_channel                           AS channel,
        c.category,
        c.case_type,
        c.priority,
        c.status,
        (c.status = 'Escalated')                      AS is_escalated,
        coalesce(c.sla_breached, FALSE)               AS sla_breached,
        CAST(NULL AS STRING)                          AS sentiment,
        coalesce(c.is_repeat_complainer, FALSE)       AS is_repeat_complainer
    FROM IDENTIFIER(:silver_schema || '.complaints') c
    CROSS JOIN params p
    WHERE c.status IN ('Open', 'In Process', 'Escalated')
      AND CAST(c.creation_date AS DATE) <= p.as_of_date
),
unresolved_interactions AS (
    SELECT
        i.customer_id,
        'interaction'                                 AS case_source,
        i.interaction_id                              AS case_id,
        CAST(i.interaction_date AS DATE)              AS opened_on,
        i.channel,
        i.reason_category                             AS category,
        CAST(NULL AS STRING)                          AS case_type,
        CAST(NULL AS STRING)                          AS priority,
        'Unresolved'                                  AS status,
        coalesce(i.was_escalated, FALSE)              AS is_escalated,
        FALSE                                         AS sla_breached,
        i.detected_sentiment                          AS sentiment,
        FALSE                                         AS is_repeat_complainer
    FROM IDENTIFIER(:silver_schema || '.call_center_interactions') i
    CROSS JOIN params p
    WHERE i.was_resolved = FALSE
      AND (i.requires_followup = TRUE OR i.was_escalated = TRUE)
      AND CAST(i.interaction_date AS DATE) >  date_sub(p.as_of_date, p.window_days)
      AND CAST(i.interaction_date AS DATE) <= p.as_of_date
      AND NOT EXISTS (
          SELECT 1 FROM IDENTIFIER(:silver_schema || '.complaints') c
          WHERE c.origin_interaction_id = i.interaction_id
      )
),
cases AS (
    SELECT * FROM open_complaints
    UNION ALL
    SELECT * FROM unresolved_interactions
)
SELECT
    cs.customer_id,
    cs.case_source,
    cs.case_id,
    cs.opened_on,
    datediff(p.as_of_date, cs.opened_on) AS days_open,
    cs.channel,
    cs.category,
    cs.case_type,
    cs.priority,
    cs.status,
    cs.is_escalated,
    cs.sla_breached,
    cs.sentiment,
    cs.is_repeat_complainer,
    p.as_of_date
FROM cases cs
CROSS JOIN params p;
