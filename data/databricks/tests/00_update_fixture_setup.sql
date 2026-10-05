-- =============================================================================================
-- Update-correctness fixture (TEST DATA). The hackathon data is static, so this shows that the
-- pipeline handles a new delivery correctly: it builds a small bronze in :bronze_schema (a
-- *_fixture schema) from a sample of :source_bronze_schema and appends a labeled "next day"
-- delivery with five cases. 02_silver.sql and 02_silver_quality_checks.sql then run on it
-- unchanged, and 99_update_fixture_assertions.sql checks the outcome of every case.
--
-- Every team-made row has _source_file_path = 'fixture://update-correctness/<case>'.
--   A late_status_update   an existing complaint arrives again, later, with status Resolved
--   B exact_duplicate      a transaction delivered twice with the same id
--   C late_arrival         a complaint created in 2024 that only arrives in June 2026
--   D schema_change        a transaction whose CSV row carried an unknown column (_rescued_data)
--   E null_key             a transaction without transaction_id
-- Parameters (catalog.schema): :source_bronze_schema, :bronze_schema. Safe to drop the schemas.
-- =============================================================================================

CREATE SCHEMA IF NOT EXISTS IDENTIFIER(:bronze_schema)
COMMENT 'Update-correctness test fixture: sample of bronze plus labeled team-made rows. Safe to drop.';

-- Small tables in full; large ones as a deterministic sample (first rows by key).
CREATE OR REPLACE TABLE IDENTIFIER(:bronze_schema || '.branches') AS
SELECT * FROM IDENTIFIER(:source_bronze_schema || '.branches');
CREATE OR REPLACE TABLE IDENTIFIER(:bronze_schema || '.service_agents') AS
SELECT * FROM IDENTIFIER(:source_bronze_schema || '.service_agents');
CREATE OR REPLACE TABLE IDENTIFIER(:bronze_schema || '.marketing_campaigns') AS
SELECT * FROM IDENTIFIER(:source_bronze_schema || '.marketing_campaigns');
CREATE OR REPLACE TABLE IDENTIFIER(:bronze_schema || '.daily_exchange_rates') AS
SELECT * FROM IDENTIFIER(:source_bronze_schema || '.daily_exchange_rates');
CREATE OR REPLACE TABLE IDENTIFIER(:bronze_schema || '.customers') AS
SELECT * FROM IDENTIFIER(:source_bronze_schema || '.customers') ORDER BY customer_id LIMIT 3000;
CREATE OR REPLACE TABLE IDENTIFIER(:bronze_schema || '.products') AS
SELECT * FROM IDENTIFIER(:source_bronze_schema || '.products') ORDER BY product_id LIMIT 3000;
CREATE OR REPLACE TABLE IDENTIFIER(:bronze_schema || '.transactions') AS
SELECT * FROM IDENTIFIER(:source_bronze_schema || '.transactions') ORDER BY transaction_id LIMIT 3000;
CREATE OR REPLACE TABLE IDENTIFIER(:bronze_schema || '.complaints') AS
SELECT * FROM IDENTIFIER(:source_bronze_schema || '.complaints') ORDER BY complaint_id LIMIT 3000;
CREATE OR REPLACE TABLE IDENTIFIER(:bronze_schema || '.call_center_interactions') AS
SELECT * FROM IDENTIFIER(:source_bronze_schema || '.call_center_interactions') ORDER BY interaction_id LIMIT 3000;
CREATE OR REPLACE TABLE IDENTIFIER(:bronze_schema || '.campaign_sends') AS
SELECT * FROM IDENTIFIER(:source_bronze_schema || '.campaign_sends') ORDER BY send_id LIMIT 3000;

-- Expected outcome of each case, read by the assertions.
CREATE OR REPLACE TABLE IDENTIFIER(:bronze_schema || '._fixture_cases') (
    case_name STRING, table_name STRING, record_key STRING, expectation STRING
)
COMMENT 'Update-correctness fixture: the five cases and what silver and the metrics must show.';

INSERT INTO IDENTIFIER(:bronze_schema || '._fixture_cases')
SELECT 'late_status_update', 'complaints', min(complaint_id), 'silver keeps one row, status Resolved (latest process_date wins)'
FROM IDENTIFIER(:bronze_schema || '.complaints') WHERE status = 'Open';

INSERT INTO IDENTIFIER(:bronze_schema || '._fixture_cases')
SELECT 'exact_duplicate', 'transactions', min(transaction_id), 'silver keeps one row; key_duplicates_removed_share > 0'
FROM IDENTIFIER(:bronze_schema || '.transactions');

INSERT INTO IDENTIFIER(:bronze_schema || '._fixture_cases') VALUES
    ('late_arrival', 'complaints', 'FIXTURE-LATE-0001', 'present in silver with creation_date 2024-01-15'),
    ('schema_change', 'transactions', 'FIXTURE-RESCUED-0001', 'loaded to silver; bronze rescued_rows = 1 (warn)'),
    ('null_key', 'transactions', NULL, 'dropped in silver; bronze null_key_rows = 1 (warn)');

-- ---------------------------------------------------------------------------------------------
-- The "next day" delivery
-- ---------------------------------------------------------------------------------------------
-- A: the same complaint, five days later, now Resolved.
INSERT INTO IDENTIFIER(:bronze_schema || '.complaints') BY NAME
SELECT * EXCEPT (status, process_date, resolution_date, _source_file_path, _bronze_ingested_at),
       'Resolved' AS status,
       CAST(date_add(to_date(process_date), 5) AS STRING) AS process_date,
       CAST(date_add(to_date(process_date), 5) AS STRING) AS resolution_date,
       'fixture://update-correctness/late_status_update' AS _source_file_path,
       current_timestamp() AS _bronze_ingested_at
FROM IDENTIFIER(:bronze_schema || '.complaints')
WHERE complaint_id = (SELECT record_key FROM IDENTIFIER(:bronze_schema || '._fixture_cases') WHERE case_name = 'late_status_update');

-- B: a transaction delivered again, identical.
INSERT INTO IDENTIFIER(:bronze_schema || '.transactions') BY NAME
SELECT * EXCEPT (_source_file_path, _bronze_ingested_at),
       'fixture://update-correctness/exact_duplicate' AS _source_file_path,
       current_timestamp() AS _bronze_ingested_at
FROM IDENTIFIER(:bronze_schema || '.transactions')
WHERE transaction_id = (SELECT record_key FROM IDENTIFIER(:bronze_schema || '._fixture_cases') WHERE case_name = 'exact_duplicate');

-- C: a complaint from January 2024 that only arrives with the June 2026 delivery.
INSERT INTO IDENTIFIER(:bronze_schema || '.complaints') BY NAME
SELECT * EXCEPT (complaint_id, creation_date, process_date, _source_file_path, _bronze_ingested_at),
       'FIXTURE-LATE-0001' AS complaint_id,
       '2024-01-15 10:00:00' AS creation_date,
       '2026-06-20' AS process_date,
       'fixture://update-correctness/late_arrival' AS _source_file_path,
       current_timestamp() AS _bronze_ingested_at
FROM IDENTIFIER(:bronze_schema || '.complaints')
WHERE complaint_id = (SELECT max(complaint_id) FROM IDENTIFIER(:bronze_schema || '.complaints')
                      WHERE _source_file_path NOT LIKE 'fixture://%');

-- D: a CSV row that carried a column the bronze schema does not know.
INSERT INTO IDENTIFIER(:bronze_schema || '.transactions') BY NAME
SELECT * EXCEPT (transaction_id, _rescued_data, _source_file_path, _bronze_ingested_at),
       'FIXTURE-RESCUED-0001' AS transaction_id,
       '{"loyalty_points":"120","_file_path":"fixture://update-correctness/schema_change"}' AS _rescued_data,
       'fixture://update-correctness/schema_change' AS _source_file_path,
       current_timestamp() AS _bronze_ingested_at
FROM IDENTIFIER(:bronze_schema || '.transactions')
WHERE transaction_id = (SELECT max(transaction_id) FROM IDENTIFIER(:bronze_schema || '.transactions')
                        WHERE _source_file_path NOT LIKE 'fixture://%');

-- E: a transaction without its key.
INSERT INTO IDENTIFIER(:bronze_schema || '.transactions') BY NAME
SELECT * EXCEPT (transaction_id, _source_file_path, _bronze_ingested_at),
       CAST(NULL AS STRING) AS transaction_id,
       'fixture://update-correctness/null_key' AS _source_file_path,
       current_timestamp() AS _bronze_ingested_at
FROM IDENTIFIER(:bronze_schema || '.transactions')
WHERE transaction_id = (SELECT max(transaction_id) FROM IDENTIFIER(:bronze_schema || '.transactions')
                        WHERE _source_file_path NOT LIKE 'fixture://%' AND transaction_id NOT LIKE 'FIXTURE-%');
