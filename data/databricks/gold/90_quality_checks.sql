-- =============================================================================================
-- Quality checks for the gold tables. Last task of the latam_bank_medallion and
-- credit_policy_refresh jobs.
-- Every check writes one row per metric to <gold_schema>.pipeline_quality_metrics (layer 'gold')
-- FIRST, and the last statement then fails the run (raise_error) if any metric of this run has
-- status 'fail'. A broken rebuild fails the job and its notification instead of reaching the agent
-- silently, and failed runs keep their metrics for diagnosis.
-- Parameters (catalog.schema): :silver_schema, :gold_schema; :run_id is the job run id (empty when
-- run by hand: a 'manual-<uuid>' id is generated).
-- =============================================================================================

CREATE TABLE IF NOT EXISTS IDENTIFIER(:gold_schema || '.pipeline_quality_metrics') (
    run_id     STRING    NOT NULL COMMENT 'Job run id, or manual-<uuid> for hand runs',
    run_at     TIMESTAMP NOT NULL COMMENT 'When the metric was computed',
    layer      STRING    NOT NULL COMMENT 'bronze, silver or gold',
    table_name STRING    NOT NULL COMMENT 'Table the metric describes',
    metric     STRING    NOT NULL COMMENT 'Metric name',
    value      DOUBLE             COMMENT 'Measured value',
    threshold  STRING             COMMENT 'Rule the value is checked against, as text (e.g. "= 0", "<= 0.20", "0.20-0.50")',
    status     STRING    NOT NULL COMMENT 'ok, warn (recorded, does not stop the run) or fail (stops the run)'
)
COMMENT 'Data quality and lineage metrics, one row per pipeline run, table and metric. Appended by the quality tasks of the latam_bank_medallion and credit_policy_refresh jobs; never rebuilt.';

INSERT INTO IDENTIFIER(:gold_schema || '.pipeline_quality_metrics')
WITH run AS (
    SELECT coalesce(nullif(:run_id, ''), concat('manual-', uuid())) AS run_id, current_timestamp() AS run_at
),
checks AS (
    -- 1. One profile row per current customer in silver.
    SELECT 'customer_credit_profile' AS table_name, 'rows_vs_silver_customers' AS metric,
           CAST(p.n AS DOUBLE) AS value,
           concat('= silver customers (', c.n, ') and = distinct ids (', p.n_ids, ')') AS threshold,
           CASE WHEN p.n = p.n_ids AND p.n = c.n THEN 'ok' ELSE 'fail' END AS status
    FROM (SELECT count(*) AS n, count(DISTINCT customer_id) AS n_ids
          FROM IDENTIFIER(:gold_schema || '.customer_credit_profile')) p
    CROSS JOIN (SELECT count(*) AS n FROM IDENTIFIER(:silver_schema || '.customers')) c

    -- 2. Cutoff date, policy version and exchange rate present on every row.
    UNION ALL
    SELECT 'customer_credit_profile', 'rows_missing_cutoff_policy_or_fx',
           CAST(count_if(as_of_date IS NULL OR policy_version IS NULL OR fx_to_usd IS NULL) AS DOUBLE),
           '= 0',
           CASE WHEN count_if(as_of_date IS NULL OR policy_version IS NULL OR fx_to_usd IS NULL) = 0 THEN 'ok' ELSE 'fail' END
    FROM IDENTIFIER(:gold_schema || '.customer_credit_profile')

    -- 3. The profile was built with the policy version currently loaded in silver.
    UNION ALL
    SELECT 'customer_credit_profile', 'policy_versions_in_profile',
           CAST(p.versions AS DOUBLE),
           concat('= 1 and = silver policy_version ', coalesce(r.v, 'null'), ' (profile: ', coalesce(p.v, 'null'), ')'),
           CASE WHEN p.versions = 1 AND p.v = r.v THEN 'ok' ELSE 'fail' END
    FROM (SELECT count(DISTINCT policy_version) AS versions, max(policy_version) AS v
          FROM IDENTIFIER(:gold_schema || '.customer_credit_profile')) p
    CROSS JOIN (SELECT max(param_value) AS v FROM IDENTIFIER(:silver_schema || '.ref_policy_params')
                WHERE param_name = 'policy_version') r

    -- 4. Eligible share inside the expected range (33.8% at the 2026-06-30 cutoff with policy 0.4).
    --    A share outside 20%-50% usually means a broken join, cast or parameter, not a real change.
    UNION ALL
    SELECT 'customer_credit_profile', 'eligible_share',
           round(avg(CAST(is_eligible AS INT)), 4),
           '0.20-0.50',
           CASE WHEN avg(CAST(is_eligible AS INT)) BETWEEN 0.20 AND 0.50 THEN 'ok' ELSE 'fail' END
    FROM IDENTIFIER(:gold_schema || '.customer_credit_profile')

    -- 5. One option row per customer and term-grid row.
    UNION ALL
    SELECT 'customer_credit_offer_options', 'rows_vs_customers_x_grid',
           CAST(o.n AS DOUBLE),
           concat('= ', p.n * g.n),
           CASE WHEN o.n = p.n * g.n THEN 'ok' ELSE 'fail' END
    FROM (SELECT count(*) AS n FROM IDENTIFIER(:gold_schema || '.customer_credit_offer_options')) o
    CROSS JOIN (SELECT count(*) AS n FROM IDENTIFIER(:gold_schema || '.customer_credit_profile')) p
    CROSS JOIN (SELECT count(*) AS n FROM IDENTIFIER(:silver_schema || '.ref_term_grid')) g

    -- 6. No available option exceeds the 20% capacity.
    UNION ALL
    SELECT 'customer_credit_offer_options', 'available_above_capacity',
           CAST(count(*) AS DOUBLE), '= 0',
           CASE WHEN count(*) = 0 THEN 'ok' ELSE 'fail' END
    FROM IDENTIFIER(:gold_schema || '.customer_credit_offer_options') o
    JOIN IDENTIFIER(:gold_schema || '.customer_credit_profile') p USING (customer_id)
    WHERE o.is_available AND o.offer_monthly_installment_usd > p.available_installment_usd + 0.01

    -- 7. No available loan option above the band maximum term.
    UNION ALL
    SELECT 'customer_credit_offer_options', 'available_above_band_max_term',
           CAST(count(*) AS DOUBLE), '= 0',
           CASE WHEN count(*) = 0 THEN 'ok' ELSE 'fail' END
    FROM IDENTIFIER(:gold_schema || '.customer_credit_offer_options') o
    JOIN IDENTIFIER(:gold_schema || '.customer_credit_profile') p USING (customer_id)
    WHERE o.is_available
      AND ((o.product_code = 'PL' AND o.term_months > p.max_term_personal_loan_months)
        OR (o.product_code = 'MG' AND o.term_months > p.max_term_mortgage_months))

    -- 8. Available amounts inside the option range; no option for non-eligible customers.
    UNION ALL
    SELECT 'customer_credit_offer_options', 'available_out_of_range_or_not_eligible',
           CAST(n AS DOUBLE), '= 0',
           CASE WHEN n = 0 THEN 'ok' ELSE 'fail' END
    FROM (SELECT count_if(is_available AND (offer_max_amount_usd < option_min_amount_usd
                                            OR offer_max_amount_usd > option_max_amount_usd
                                            OR unavailable_reason IS NOT NULL
                                            OR offer_mode = 'none')) AS n
          FROM IDENTIFIER(:gold_schema || '.customer_credit_offer_options'))

    -- 8b. Exactly one featured option per customer and product with any available option, none
    --     otherwise, and never an unavailable one.
    UNION ALL
    SELECT 'customer_credit_offer_options', 'featured_option_violations',
           CAST(count(*) AS DOUBLE), '= 0',
           CASE WHEN count(*) = 0 THEN 'ok' ELSE 'fail' END
    FROM (SELECT customer_id, product_code
          FROM IDENTIFIER(:gold_schema || '.customer_credit_offer_options')
          GROUP BY customer_id, product_code
          HAVING count_if(is_featured) != CASE WHEN bool_or(is_available) THEN 1 ELSE 0 END
              OR count_if(is_featured AND NOT is_available) > 0)

    -- 9. Customer summaries (gold/30-32): one row per customer. A duplicate means a join (usually
    --    the exchange rate one) multiplied rows.
    UNION ALL
    SELECT t, 'duplicate_customer_rows', CAST(n - n_ids AS DOUBLE), '= 0',
           CASE WHEN n = n_ids THEN 'ok' ELSE 'fail' END
    FROM (
        SELECT 'customer_products_summary' AS t, count(*) AS n, count(DISTINCT customer_id) AS n_ids
        FROM IDENTIFIER(:gold_schema || '.customer_products_summary')
        UNION ALL
        SELECT 'customer_complaints_summary', count(*), count(DISTINCT customer_id)
        FROM IDENTIFIER(:gold_schema || '.customer_complaints_summary')
        UNION ALL
        SELECT 'customer_cashflow_summary', count(*), count(DISTINCT customer_id)
        FROM IDENTIFIER(:gold_schema || '.customer_cashflow_summary')
    )

    -- 10. Contract with the API: the columns and types the backend and data/policy/credit_policy.py
    --     read from the profile and the offer options (documented in data/databricks/README.md).
    --     A renamed, dropped or retyped column fails the run here instead of breaking the agent.
    UNION ALL
    SELECT e.table_name, 'contract_violations', CAST(count_if(c.column_name IS NULL) AS DOUBLE), '= 0',
           CASE WHEN count_if(c.column_name IS NULL) = 0 THEN 'ok' ELSE 'fail' END
    FROM (VALUES
        ('customer_credit_profile', 'customer_id', 'string'), ('customer_credit_profile', 'is_eligible', 'boolean'),
        ('customer_credit_profile', 'offer_mode', 'string'), ('customer_credit_profile', 'not_proactive_reason', 'string'),
        ('customer_credit_profile', 'reason_codes', 'array<string>'),
        ('customer_credit_profile', 'requires_advisor_review', 'boolean'),
        ('customer_credit_profile', 'can_become_eligible_with_declared_income', 'boolean'),
        ('customer_credit_profile', 'risk_band', 'string'), ('customer_credit_profile', 'segment', 'string'),
        ('customer_credit_profile', 'local_currency', 'string'), ('customer_credit_profile', 'fx_to_usd', 'double'),
        ('customer_credit_profile', 'fx_date', 'date'), ('customer_credit_profile', 'income_used_usd', 'double'),
        ('customer_credit_profile', 'income_source', 'string'),
        ('customer_credit_profile', 'current_installments_usd', 'double'),
        ('customer_credit_profile', 'max_total_installment_usd', 'double'),
        ('customer_credit_profile', 'available_installment_usd', 'double'),
        ('customer_credit_profile', 'total_rate_adjustment_pp', 'double'),
        ('customer_credit_profile', 'max_term_personal_loan_months', 'int'),
        ('customer_credit_profile', 'max_term_mortgage_months', 'int'),
        ('customer_credit_profile', 'open_complaints', 'bigint'),
        ('customer_credit_profile', 'open_priority_complaints', 'bigint'),
        ('customer_credit_profile', 'open_critical_complaints', 'bigint'),
        ('customer_credit_profile', 'as_of_date', 'date'), ('customer_credit_profile', 'policy_version', 'string'),
        ('customer_credit_offer_options', 'customer_id', 'string'), ('customer_credit_offer_options', 'option_code', 'string'),
        ('customer_credit_offer_options', 'product_code', 'string'), ('customer_credit_offer_options', 'product_type', 'string'),
        ('customer_credit_offer_options', 'tier', 'string'), ('customer_credit_offer_options', 'term_months', 'int'),
        ('customer_credit_offer_options', 'offer_rate_pct', 'double'),
        ('customer_credit_offer_options', 'option_min_amount_usd', 'int'),
        ('customer_credit_offer_options', 'option_max_amount_usd', 'int'),
        ('customer_credit_offer_options', 'is_available', 'boolean'),
        ('customer_credit_offer_options', 'is_featured', 'boolean'),
        ('customer_credit_offer_options', 'unavailable_reason', 'string'),
        ('customer_credit_offer_options', 'offer_mode', 'string'),
        ('customer_credit_offer_options', 'offer_max_amount_usd', 'bigint'),
        ('customer_credit_offer_options', 'offer_monthly_installment_usd', 'double'),
        ('customer_credit_offer_options', 'offer_max_amount_local', 'double'),
        ('customer_credit_offer_options', 'offer_monthly_installment_local', 'double'),
        ('customer_credit_offer_options', 'local_currency', 'string'),
        ('customer_credit_offer_options', 'fx_to_usd', 'double')
    ) AS e(table_name, column_name, data_type)
    LEFT JOIN IDENTIFIER(split_part(:gold_schema, '.', 1) || '.information_schema.columns') c
      ON c.table_schema = split_part(:gold_schema, '.', 2)
     AND c.table_name = e.table_name
     AND c.column_name = e.column_name
     AND lower(c.full_data_type) = e.data_type
    GROUP BY e.table_name
)
SELECT r.run_id, r.run_at, 'gold', c.table_name, c.metric, c.value, c.threshold, c.status
FROM checks c CROSS JOIN run r;

-- Gate: fail the run if any gold metric of this run failed (latest gold run; jobs run one at a time).
SELECT CASE
    WHEN count_if(status = 'fail') > 0 THEN raise_error(concat(
        'GOLD QUALITY CHECKS FAILED: ',
        array_join(collect_list(CASE WHEN status = 'fail'
                                     THEN concat(table_name, '.', metric, ' = ', CAST(value AS STRING), ' (', threshold, ')') END), '; ')))
    ELSE concat('Gold quality checks OK: ', count(*), ' metrics')
END AS result
FROM IDENTIFIER(:gold_schema || '.pipeline_quality_metrics')
WHERE layer = 'gold'
  AND run_at = (SELECT max(run_at) FROM IDENTIFIER(:gold_schema || '.pipeline_quality_metrics') WHERE layer = 'gold');
