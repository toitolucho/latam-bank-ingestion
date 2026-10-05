-- =====================================================================
-- 02_silver_quality_checks — Métricas de calidad de bronze y silver en
-- cada corrida, y gate que corta el job si alguna falla. Corre DESPUÉS de
-- 02_silver.sql y ANTES de gold.
--
-- Cubre las características de calidad que documenta el datathon:
--   - Duplicados (~2%): duplicados por clave eliminados en silver (bronze
--     vs silver), duplicados por clave que hayan quedado en silver (deben
--     ser 0) y duplicados de CONTENIDO (mismo registro con otro ID).
--   - Nulos (~5%): proporción de nulos en columnas críticas, con umbral
--     por columna a partir de lo observado (credit_score ~15% e ingreso
--     ~20% vienen así del origen).
--   - Cambios de esquema: filas con _rescued_data en bronze (columna
--     nueva o fila mal formada en el CSV fuente).
--   - Llegadas tardías: la recarga completa de cada corrida las absorbe
--     y el dedup por process_date DESC se queda con la versión más
--     reciente, sin importar el orden de llegada (no se mide aparte).
--
-- Cada métrica se INSERTA primero en <gold_schema>.pipeline_quality_metrics
-- (una fila por corrida, tabla y métrica; historial que nunca se borra) y
-- recién después la última sentencia falla (raise_error) si alguna quedó
-- en 'fail'. 'warn' queda registrado pero no corta la ejecución.
--
-- Parámetros (catálogo.schema): :bronze_schema, :silver_schema,
-- :gold_schema; :run_id = id de la corrida del job (vacío a mano: se
-- genera 'manual-<uuid>').
-- Los umbrales de nulos de FKs y montos (10%) son iniciales: ajustarlos con
-- lo que muestre la primera corrida.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS IDENTIFIER(:gold_schema);

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
stats AS (
    -- branches
    SELECT 'branches' AS table_name, b.n_rows AS bronze_rows, b.rescued_rows, b.null_key_rows, s.n_rows AS silver_rows,
           s.key_dup_rows, c.content_dup_rows AS content_dup_rows
    FROM (SELECT count(*) AS n_rows, count_if(_rescued_data IS NOT NULL) AS rescued_rows,
                 count_if(branch_id IS NULL) AS null_key_rows
          FROM IDENTIFIER(:bronze_schema || '.branches')) b
    CROSS JOIN (SELECT count(*) AS n_rows, count(*) - count(DISTINCT branch_id) AS key_dup_rows
                FROM IDENTIFIER(:silver_schema || '.branches')) s
    CROSS JOIN (SELECT coalesce(sum(n - 1), 0) AS content_dup_rows
                FROM (SELECT count(*) AS n FROM IDENTIFIER(:silver_schema || '.branches')
                      WHERE branch_code IS NOT NULL
                      GROUP BY branch_code HAVING count(*) > 1)) c
    UNION ALL
    -- call_center_interactions
    SELECT 'call_center_interactions' AS table_name, b.n_rows AS bronze_rows, b.rescued_rows, b.null_key_rows, s.n_rows AS silver_rows,
           s.key_dup_rows, c.content_dup_rows AS content_dup_rows
    FROM (SELECT count(*) AS n_rows, count_if(_rescued_data IS NOT NULL) AS rescued_rows,
                 count_if(interaction_id IS NULL) AS null_key_rows
          FROM IDENTIFIER(:bronze_schema || '.call_center_interactions')) b
    CROSS JOIN (SELECT count(*) AS n_rows, count(*) - count(DISTINCT interaction_id) AS key_dup_rows
                FROM IDENTIFIER(:silver_schema || '.call_center_interactions')) s
    CROSS JOIN (SELECT coalesce(sum(n - 1), 0) AS content_dup_rows
                FROM (SELECT count(*) AS n FROM IDENTIFIER(:silver_schema || '.call_center_interactions')
                      WHERE customer_id IS NOT NULL AND agent_id IS NOT NULL AND interaction_date IS NOT NULL
                      GROUP BY customer_id, agent_id, interaction_date HAVING count(*) > 1)) c
    UNION ALL
    -- campaign_sends
    SELECT 'campaign_sends' AS table_name, b.n_rows AS bronze_rows, b.rescued_rows, b.null_key_rows, s.n_rows AS silver_rows,
           s.key_dup_rows, c.content_dup_rows AS content_dup_rows
    FROM (SELECT count(*) AS n_rows, count_if(_rescued_data IS NOT NULL) AS rescued_rows,
                 count_if(send_id IS NULL) AS null_key_rows
          FROM IDENTIFIER(:bronze_schema || '.campaign_sends')) b
    CROSS JOIN (SELECT count(*) AS n_rows, count(*) - count(DISTINCT send_id) AS key_dup_rows
                FROM IDENTIFIER(:silver_schema || '.campaign_sends')) s
    CROSS JOIN (SELECT coalesce(sum(n - 1), 0) AS content_dup_rows
                FROM (SELECT count(*) AS n FROM IDENTIFIER(:silver_schema || '.campaign_sends')
                      WHERE campaign_id IS NOT NULL AND customer_id IS NOT NULL AND send_date IS NOT NULL
                      GROUP BY campaign_id, customer_id, send_date HAVING count(*) > 1)) c
    UNION ALL
    -- complaints
    SELECT 'complaints' AS table_name, b.n_rows AS bronze_rows, b.rescued_rows, b.null_key_rows, s.n_rows AS silver_rows,
           s.key_dup_rows, c.content_dup_rows AS content_dup_rows
    FROM (SELECT count(*) AS n_rows, count_if(_rescued_data IS NOT NULL) AS rescued_rows,
                 count_if(complaint_id IS NULL) AS null_key_rows
          FROM IDENTIFIER(:bronze_schema || '.complaints')) b
    CROSS JOIN (SELECT count(*) AS n_rows, count(*) - count(DISTINCT complaint_id) AS key_dup_rows
                FROM IDENTIFIER(:silver_schema || '.complaints')) s
    CROSS JOIN (SELECT coalesce(sum(n - 1), 0) AS content_dup_rows
                FROM (SELECT count(*) AS n FROM IDENTIFIER(:silver_schema || '.complaints')
                      WHERE customer_id IS NOT NULL AND creation_date IS NOT NULL AND case_type IS NOT NULL AND category IS NOT NULL
                      GROUP BY customer_id, creation_date, case_type, category HAVING count(*) > 1)) c
    UNION ALL
    -- customers
    SELECT 'customers' AS table_name, b.n_rows AS bronze_rows, b.rescued_rows, b.null_key_rows, s.n_rows AS silver_rows,
           s.key_dup_rows, c.content_dup_rows AS content_dup_rows
    FROM (SELECT count(*) AS n_rows, count_if(_rescued_data IS NOT NULL) AS rescued_rows,
                 count_if(customer_id IS NULL) AS null_key_rows
          FROM IDENTIFIER(:bronze_schema || '.customers')) b
    CROSS JOIN (SELECT count(*) AS n_rows, count(*) - count(DISTINCT customer_id) AS key_dup_rows
                FROM IDENTIFIER(:silver_schema || '.customers')) s
    CROSS JOIN (SELECT coalesce(sum(n - 1), 0) AS content_dup_rows
                FROM (SELECT count(*) AS n FROM IDENTIFIER(:silver_schema || '.customers')
                      WHERE document_number IS NOT NULL
                      GROUP BY document_number HAVING count(*) > 1)) c
    UNION ALL
    -- daily_exchange_rates
    SELECT 'daily_exchange_rates' AS table_name, b.n_rows AS bronze_rows, b.rescued_rows, b.null_key_rows, s.n_rows AS silver_rows,
           s.key_dup_rows, CAST(NULL AS BIGINT) AS content_dup_rows
    FROM (SELECT count(*) AS n_rows, count_if(_rescued_data IS NOT NULL) AS rescued_rows,
                 count_if(source_currency IS NULL OR target_currency IS NULL OR date IS NULL) AS null_key_rows
          FROM IDENTIFIER(:bronze_schema || '.daily_exchange_rates')) b
    CROSS JOIN (SELECT count(*) AS n_rows, count(*) - count(DISTINCT source_currency, target_currency, date) AS key_dup_rows
                FROM IDENTIFIER(:silver_schema || '.daily_exchange_rates')) s
    UNION ALL
    -- marketing_campaigns
    SELECT 'marketing_campaigns' AS table_name, b.n_rows AS bronze_rows, b.rescued_rows, b.null_key_rows, s.n_rows AS silver_rows,
           s.key_dup_rows, c.content_dup_rows AS content_dup_rows
    FROM (SELECT count(*) AS n_rows, count_if(_rescued_data IS NOT NULL) AS rescued_rows,
                 count_if(campaign_id IS NULL) AS null_key_rows
          FROM IDENTIFIER(:bronze_schema || '.marketing_campaigns')) b
    CROSS JOIN (SELECT count(*) AS n_rows, count(*) - count(DISTINCT campaign_id) AS key_dup_rows
                FROM IDENTIFIER(:silver_schema || '.marketing_campaigns')) s
    CROSS JOIN (SELECT coalesce(sum(n - 1), 0) AS content_dup_rows
                FROM (SELECT count(*) AS n FROM IDENTIFIER(:silver_schema || '.marketing_campaigns')
                      WHERE campaign_name IS NOT NULL AND start_date IS NOT NULL
                      GROUP BY campaign_name, start_date HAVING count(*) > 1)) c
    UNION ALL
    -- products
    SELECT 'products' AS table_name, b.n_rows AS bronze_rows, b.rescued_rows, b.null_key_rows, s.n_rows AS silver_rows,
           s.key_dup_rows, c.content_dup_rows AS content_dup_rows
    FROM (SELECT count(*) AS n_rows, count_if(_rescued_data IS NOT NULL) AS rescued_rows,
                 count_if(product_id IS NULL) AS null_key_rows
          FROM IDENTIFIER(:bronze_schema || '.products')) b
    CROSS JOIN (SELECT count(*) AS n_rows, count(*) - count(DISTINCT product_id) AS key_dup_rows
                FROM IDENTIFIER(:silver_schema || '.products')) s
    CROSS JOIN (SELECT coalesce(sum(n - 1), 0) AS content_dup_rows
                FROM (SELECT count(*) AS n FROM IDENTIFIER(:silver_schema || '.products')
                      WHERE product_number IS NOT NULL
                      GROUP BY product_number HAVING count(*) > 1)) c
    UNION ALL
    -- service_agents
    SELECT 'service_agents' AS table_name, b.n_rows AS bronze_rows, b.rescued_rows, b.null_key_rows, s.n_rows AS silver_rows,
           s.key_dup_rows, c.content_dup_rows AS content_dup_rows
    FROM (SELECT count(*) AS n_rows, count_if(_rescued_data IS NOT NULL) AS rescued_rows,
                 count_if(agent_id IS NULL) AS null_key_rows
          FROM IDENTIFIER(:bronze_schema || '.service_agents')) b
    CROSS JOIN (SELECT count(*) AS n_rows, count(*) - count(DISTINCT agent_id) AS key_dup_rows
                FROM IDENTIFIER(:silver_schema || '.service_agents')) s
    CROSS JOIN (SELECT coalesce(sum(n - 1), 0) AS content_dup_rows
                FROM (SELECT count(*) AS n FROM IDENTIFIER(:silver_schema || '.service_agents')
                      WHERE employee_code IS NOT NULL
                      GROUP BY employee_code HAVING count(*) > 1)) c
    UNION ALL
    -- transactions
    SELECT 'transactions' AS table_name, b.n_rows AS bronze_rows, b.rescued_rows, b.null_key_rows, s.n_rows AS silver_rows,
           s.key_dup_rows, c.content_dup_rows AS content_dup_rows
    FROM (SELECT count(*) AS n_rows, count_if(_rescued_data IS NOT NULL) AS rescued_rows,
                 count_if(transaction_id IS NULL) AS null_key_rows
          FROM IDENTIFIER(:bronze_schema || '.transactions')) b
    CROSS JOIN (SELECT count(*) AS n_rows, count(*) - count(DISTINCT transaction_id) AS key_dup_rows
                FROM IDENTIFIER(:silver_schema || '.transactions')) s
    CROSS JOIN (SELECT coalesce(sum(n - 1), 0) AS content_dup_rows
                FROM (SELECT count(*) AS n FROM IDENTIFIER(:silver_schema || '.transactions')
                      WHERE customer_id IS NOT NULL AND product_id IS NOT NULL AND transaction_date IS NOT NULL AND amount IS NOT NULL AND transaction_type IS NOT NULL
                      GROUP BY customer_id, product_id, transaction_date, amount, transaction_type HAVING count(*) > 1)) c
),
metrics AS (
    -- bronze: volumen, cambios de esquema y claves nulas (se descartan en silver)
    SELECT 'bronze' AS layer, table_name, 'rows' AS metric, CAST(bronze_rows AS DOUBLE) AS value,
           '> 0' AS threshold, CASE WHEN bronze_rows > 0 THEN 'ok' ELSE 'fail' END AS status
    FROM stats
    UNION ALL
    SELECT 'bronze', table_name, 'rescued_rows', CAST(rescued_rows AS DOUBLE),
           '= 0 (warn: schema change or malformed rows)', CASE WHEN rescued_rows = 0 THEN 'ok' ELSE 'warn' END
    FROM stats
    UNION ALL
    SELECT 'bronze', table_name, 'null_key_rows', CAST(null_key_rows AS DOUBLE),
           '= 0 (warn: dropped in silver)', CASE WHEN null_key_rows = 0 THEN 'ok' ELSE 'warn' END
    FROM stats
    -- silver: volumen, duplicados eliminados, duplicados restantes y de contenido
    UNION ALL
    SELECT 'silver', table_name, 'rows', CAST(silver_rows AS DOUBLE),
           '> 0', CASE WHEN silver_rows > 0 THEN 'ok' ELSE 'fail' END
    FROM stats
    UNION ALL
    SELECT 'silver', table_name, 'key_duplicates_removed_share',
           round((bronze_rows - null_key_rows - silver_rows) / nullif(bronze_rows, 0), 4),
           '<= 0.05', CASE WHEN (bronze_rows - null_key_rows - silver_rows) / nullif(bronze_rows, 0) <= 0.05 THEN 'ok' ELSE 'fail' END
    FROM stats
    UNION ALL
    SELECT 'silver', table_name, 'key_duplicate_rows_left', CAST(key_dup_rows AS DOUBLE),
           '= 0', CASE WHEN key_dup_rows = 0 THEN 'ok' ELSE 'fail' END
    FROM stats
    UNION ALL
    SELECT 'silver', table_name, 'content_duplicate_rows', CAST(content_dup_rows AS DOUBLE),
           '= 0 (warn: same record under another id)', CASE WHEN content_dup_rows = 0 THEN 'ok' ELSE 'warn' END
    FROM stats
    WHERE content_dup_rows IS NOT NULL
    -- silver: nulos en columnas críticas, umbral por columna
    UNION ALL
    SELECT 'silver', table_name, metric, value, threshold, status FROM (
        SELECT 'call_center_interactions' AS table_name, 'null_share_customer_id' AS metric,
               round(count_if(customer_id IS NULL) / count(*), 4) AS value, '<= 0.10' AS threshold,
               CASE WHEN count_if(customer_id IS NULL) / count(*) <= 0.1 THEN 'ok' ELSE 'fail' END AS status
        FROM IDENTIFIER(:silver_schema || '.call_center_interactions')
        UNION ALL
        SELECT 'campaign_sends' AS table_name, 'null_share_customer_id' AS metric,
               round(count_if(customer_id IS NULL) / count(*), 4) AS value, '<= 0.10' AS threshold,
               CASE WHEN count_if(customer_id IS NULL) / count(*) <= 0.1 THEN 'ok' ELSE 'fail' END AS status
        FROM IDENTIFIER(:silver_schema || '.campaign_sends')
        UNION ALL
        SELECT 'complaints' AS table_name, 'null_share_customer_id' AS metric,
               round(count_if(customer_id IS NULL) / count(*), 4) AS value, '<= 0.10' AS threshold,
               CASE WHEN count_if(customer_id IS NULL) / count(*) <= 0.1 THEN 'ok' ELSE 'fail' END AS status
        FROM IDENTIFIER(:silver_schema || '.complaints')
        UNION ALL
        SELECT 'customers' AS table_name, 'null_share_credit_score' AS metric,
               round(count_if(credit_score IS NULL) / count(*), 4) AS value, '<= 0.20' AS threshold,
               CASE WHEN count_if(credit_score IS NULL) / count(*) <= 0.2 THEN 'ok' ELSE 'fail' END AS status
        FROM IDENTIFIER(:silver_schema || '.customers')
        UNION ALL
        SELECT 'customers' AS table_name, 'null_share_estimated_monthly_income' AS metric,
               round(count_if(estimated_monthly_income IS NULL) / count(*), 4) AS value, '<= 0.25' AS threshold,
               CASE WHEN count_if(estimated_monthly_income IS NULL) / count(*) <= 0.25 THEN 'ok' ELSE 'fail' END AS status
        FROM IDENTIFIER(:silver_schema || '.customers')
        UNION ALL
        SELECT 'daily_exchange_rates' AS table_name, 'null_share_exchange_rate' AS metric,
               round(count_if(exchange_rate IS NULL) / count(*), 4) AS value, '<= 0.00' AS threshold,
               CASE WHEN count_if(exchange_rate IS NULL) / count(*) <= 0.0 THEN 'ok' ELSE 'fail' END AS status
        FROM IDENTIFIER(:silver_schema || '.daily_exchange_rates')
        UNION ALL
        SELECT 'products' AS table_name, 'null_share_customer_id' AS metric,
               round(count_if(customer_id IS NULL) / count(*), 4) AS value, '<= 0.10' AS threshold,
               CASE WHEN count_if(customer_id IS NULL) / count(*) <= 0.1 THEN 'ok' ELSE 'fail' END AS status
        FROM IDENTIFIER(:silver_schema || '.products')
        UNION ALL
        SELECT 'products' AS table_name, 'null_share_currency' AS metric,
               round(count_if(currency IS NULL) / count(*), 4) AS value, '<= 0.10' AS threshold,
               CASE WHEN count_if(currency IS NULL) / count(*) <= 0.1 THEN 'ok' ELSE 'fail' END AS status
        FROM IDENTIFIER(:silver_schema || '.products')
        UNION ALL
        SELECT 'transactions' AS table_name, 'null_share_customer_id' AS metric,
               round(count_if(customer_id IS NULL) / count(*), 4) AS value, '<= 0.10' AS threshold,
               CASE WHEN count_if(customer_id IS NULL) / count(*) <= 0.1 THEN 'ok' ELSE 'fail' END AS status
        FROM IDENTIFIER(:silver_schema || '.transactions')
        UNION ALL
        SELECT 'transactions' AS table_name, 'null_share_amount' AS metric,
               round(count_if(amount IS NULL) / count(*), 4) AS value, '<= 0.10' AS threshold,
               CASE WHEN count_if(amount IS NULL) / count(*) <= 0.1 THEN 'ok' ELSE 'fail' END AS status
        FROM IDENTIFIER(:silver_schema || '.transactions')
    )
)
SELECT r.run_id, r.run_at, m.layer, m.table_name, m.metric, m.value, m.threshold, m.status
FROM metrics m CROSS JOIN run r;

-- GATE: corta la corrida si alguna métrica de bronze/silver de esta corrida
-- quedó en 'fail' (la última corrida; los jobs corren de a una a la vez).
SELECT CASE
    WHEN count_if(status = 'fail') > 0 THEN raise_error(concat(
        'GATE DE CALIDAD FALLÓ: ',
        array_join(collect_list(CASE WHEN status = 'fail'
                                     THEN concat(layer, '.', table_name, '.', metric, ' = ', CAST(value AS STRING), ' (', threshold, ')') END), '; ')))
    ELSE concat('Gate de calidad OK: ', count(*), ' métricas, ', count_if(status = 'warn'), ' en warn')
END AS resultado
FROM IDENTIFIER(:gold_schema || '.pipeline_quality_metrics')
WHERE layer IN ('bronze', 'silver')
  AND run_at = (SELECT max(run_at) FROM IDENTIFIER(:gold_schema || '.pipeline_quality_metrics')
                WHERE layer IN ('bronze', 'silver'));
