-- =============================================================================================
-- Assertions of the update-correctness fixture (see 00_update_fixture_setup.sql). Runs after
-- 02_silver.sql and 02_silver_quality_checks.sql on the *_fixture schemas; each statement fails
-- with assert_true if the pipeline did not handle its case correctly.
-- Parameters (catalog.schema): :bronze_schema, :silver_schema, :gold_schema (fixture schemas).
-- =============================================================================================

-- A late_status_update: one row, the later delivery wins.
SELECT assert_true(count(*) = 1 AND max(status) = 'Resolved',
                   concat('late_status_update: rows ', count(*), ', status ', max(status)))
FROM IDENTIFIER(:silver_schema || '.complaints')
WHERE complaint_id = (SELECT record_key FROM IDENTIFIER(:bronze_schema || '._fixture_cases') WHERE case_name = 'late_status_update');

-- B exact_duplicate: delivered twice in bronze, once in silver.
SELECT assert_true(b.n = 2 AND s.n = 1, concat('exact_duplicate: bronze ', b.n, ', silver ', s.n))
FROM (SELECT count(*) AS n FROM IDENTIFIER(:bronze_schema || '.transactions')
      WHERE transaction_id = (SELECT record_key FROM IDENTIFIER(:bronze_schema || '._fixture_cases') WHERE case_name = 'exact_duplicate')) b
CROSS JOIN (SELECT count(*) AS n FROM IDENTIFIER(:silver_schema || '.transactions')
            WHERE transaction_id = (SELECT record_key FROM IDENTIFIER(:bronze_schema || '._fixture_cases') WHERE case_name = 'exact_duplicate')) s;

-- C late_arrival: present with its original creation date.
SELECT assert_true(count(*) = 1 AND CAST(max(creation_date) AS DATE) = DATE'2024-01-15',
                   concat('late_arrival: rows ', count(*), ', creation_date ', max(creation_date)))
FROM IDENTIFIER(:silver_schema || '.complaints')
WHERE complaint_id = 'FIXTURE-LATE-0001';

-- D schema_change: the row still reaches silver.
SELECT assert_true(count(*) = 1, concat('schema_change: silver rows ', count(*)))
FROM IDENTIFIER(:silver_schema || '.transactions')
WHERE transaction_id = 'FIXTURE-RESCUED-0001';

-- E null_key: dropped in silver.
SELECT assert_true(count(*) = 0, concat('null_key: silver rows without transaction_id ', count(*)))
FROM IDENTIFIER(:silver_schema || '.transactions')
WHERE transaction_id IS NULL;

-- Metrics of the latest silver quality run record every case with the expected status.
SELECT assert_true(
    max(CASE WHEN table_name = 'transactions' AND metric = 'rescued_rows' THEN value = 1 AND status = 'warn' END)
    AND max(CASE WHEN table_name = 'transactions' AND metric = 'null_key_rows' THEN value = 1 AND status = 'warn' END)
    AND max(CASE WHEN table_name = 'transactions' AND metric = 'key_duplicates_removed_share' THEN value > 0 AND status = 'ok' END)
    AND max(CASE WHEN table_name = 'complaints' AND metric = 'key_duplicates_removed_share' THEN value > 0 AND status = 'ok' END)
    AND max(CASE WHEN table_name = 'transactions' AND metric = 'key_duplicate_rows_left' THEN value = 0 END)
    AND max(CASE WHEN table_name = 'complaints' AND metric = 'key_duplicate_rows_left' THEN value = 0 END),
    'pipeline_quality_metrics did not record the fixture cases as expected')
FROM IDENTIFIER(:gold_schema || '.pipeline_quality_metrics')
WHERE layer IN ('bronze', 'silver')
  AND run_at = (SELECT max(run_at) FROM IDENTIFIER(:gold_schema || '.pipeline_quality_metrics') WHERE layer = 'silver');
