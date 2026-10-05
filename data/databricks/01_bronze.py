# Databricks notebook source
# =====================================================================
# 01_bronze — Carga cruda de los CSV originales en Volumes a tablas
# bronze, SIN transformar ni castear (todo queda como STRING, igual
# a como venía siendo ingerido antes). El tipado real pasa en 02_silver.
#
# No depende de ninguna config externa: la lista de entidades está acá
# mismo, visible y editable.
#
# Cada entidad tiene un schema explícito (todas las columnas como
# STRING) y _rescued_data activado: si un CSV futuro trae una columna
# nueva que no está en la lista de abajo, o una fila malformada (más
# campos de los esperados, etc.), en vez de perderse en silencio o
# romper la carga, va a parar a la columna _rescued_data como JSON.
# Si ven filas con _rescued_data no-nulo, hay que revisar esa entidad:
# o cambió el formato del CSV fuente, o hay un problema de datos.
#
# Correr manualmente ("Run All") después de hacer git pull en el
# Git folder conectado al repo.
# =====================================================================

from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

LANDING_BASE = "dbfs:/Volumes/workspace/staging_latam_bank/landing"
# Schema destino como parámetro (catálogo.schema). En un Job, el parámetro
# bronze_schema del job llega acá como widget; a mano, se cambia en el
# widget de arriba del notebook. Default: el schema de prueba.
dbutils.widgets.text("bronze_schema", "workspace.bronze_latam_bank_test")
BRONZE_SCHEMA = dbutils.widgets.get("bronze_schema")

# Todas las entidades encontradas en el landing volume (confirmado
# 2026-10-04 vía %fs ls). Si agregan una carpeta nueva, hay que sumarla
# acá Y agregar su lista de columnas en ENTITY_COLUMNS más abajo.
ENTITIES = [
    "branches",
    "call_center_interactions",
    "campaign_sends",
    "complaints",
    "customers",
    "daily_exchange_rates",
    "marketing_campaigns",
    "products",
    "service_agents",
    "transactions",
]

# Columnas esperadas por entidad (confirmado 2026-10-04 vía DESCRIBE
# sobre las tablas ya cargadas). Todas como STRING a propósito -- el
# tipado real pasa en 02_silver. Si el CSV trae una columna que NO está
# acá listada, cae en _rescued_data en vez de romper o perderse.
ENTITY_COLUMNS = {
    "branches": [
        "branch_id", "branch_code", "branch_name", "branch_type", "branch_status",
        "address", "city", "state", "country", "postal_code", "latitude", "longitude",
        "phone", "email", "opening_time", "closing_time", "branch_opening_date",
        "has_atms", "atm_count", "has_teller_windows", "teller_window_count",
        "geographic_zone",
    ],
    "call_center_interactions": [
        "interaction_id", "interaction_date", "process_date", "customer_id", "agent_id",
        "channel", "interaction_type", "contact_reason", "reason_category",
        "mentioned_products", "duration_seconds", "wait_time_seconds", "was_resolved",
        "requires_followup", "was_escalated", "has_recording", "has_transcript",
        "detected_sentiment", "sentiment_score", "customer_detected_accent",
        "agent_used_accent",
    ],
    "campaign_sends": [
        "send_id", "campaign_id", "customer_id", "send_date", "process_date",
        "send_channel", "template_used", "subject", "send_status", "was_delivered",
        "was_opened", "open_date", "was_clicked", "click_date", "click_count",
        "had_conversion", "conversion_date", "conversion_value", "open_device",
        "open_country", "failure_reason", "send_cost",
    ],
    "complaints": [
        "complaint_id", "creation_date", "process_date", "customer_id", "case_type",
        "category", "subcategory", "reception_channel", "affected_product_id",
        "related_branch_id", "origin_interaction_id", "description", "claimed_amount",
        "currency", "priority", "status", "assigned_agent_id", "assignment_date",
        "first_response_date", "resolution_date", "closing_date", "sla_breached",
        "resolution_days", "resolution", "compensation_granted",
        "resolution_satisfaction", "is_repeat_complainer",
    ],
    "customers": [
        "customer_id", "first_name", "last_name", "email", "document_type",
        "document_number", "date_of_birth", "gender", "marital_status",
        "education_level", "occupation", "mobile_phone", "landline_phone", "address",
        "city", "state", "postal_code", "country", "segment", "customer_status",
        "credit_score", "estimated_monthly_income", "accepts_marketing",
        "registration_date", "registration_branch_id", "last_updated",
        "detected_accent",
    ],
    "daily_exchange_rates": [
        "source_currency", "target_currency", "date", "exchange_rate", "buy_rate",
        "sell_rate", "source",
    ],
    "marketing_campaigns": [
        "campaign_id", "campaign_name", "campaign_type", "campaign_objective",
        "campaign_status", "description", "start_date", "end_date", "budget",
        "expected_conversion_rate", "target_segment", "target_country",
        "promoted_product",
    ],
    "products": [
        "product_id", "product_number", "customer_id", "product_type",
        "product_status", "currency", "current_balance", "credit_limit",
        "interest_rate", "days_past_due", "opening_date", "expiration_date",
        "last_updated", "last_transaction_date", "opening_branch_id",
        "opening_channel", "has_linked_app",
    ],
    "service_agents": [
        "agent_id", "employee_code", "first_name", "last_name", "email", "phone",
        "agent_type", "agent_status", "assigned_branch_id", "hire_date",
        "experience_level", "specialty", "languages", "native_accent",
        "country_of_origin", "work_shift", "avg_csat", "total_monthly_interactions",
    ],
    "transactions": [
        "transaction_id", "transaction_date", "process_date", "product_id",
        "customer_id", "transaction_type", "transaction_category", "amount",
        "currency", "amount_usd", "channel", "branch_id", "merchant_name",
        "merchant_category", "transaction_country", "transaction_city",
        "transaction_status", "response_code", "is_fraud", "fraud_score",
        "latitude", "longitude",
    ],
}

# Tablas grandes con columna de fecha de proceso real -> se particionan,
# simulando un ambiente productivo. Las demás (dimensiones, más chicas,
# sin fecha de carga clara) quedan sin particionar. En bronze la columna
# sigue siendo STRING (a propósito), particionar por STRING funciona igual.
PARTITION_COLUMNS = {
    "transactions": "process_date",
    "campaign_sends": "process_date",
    "complaints": "process_date",
    "call_center_interactions": "process_date",
}

# COMMAND ----------

# Crear el schema bronze si no existe (no hace nada si ya existe)
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {BRONZE_SCHEMA}")

# COMMAND ----------

for entity in ENTITIES:
    source_path = f"{LANDING_BASE}/{entity}/"
    target_table = f"{BRONZE_SCHEMA}.{entity}"

    print(f"Leyendo {entity} desde {source_path} ...")

    expected_schema = StructType(
        [StructField(col, StringType(), True) for col in ENTITY_COLUMNS[entity]]
    )

    df = (
        spark.read
        .schema(expected_schema)
        .option("header", "true")
        .option("enforceSchema", "false")       # alinea por nombre de columna del header, no por posición
        .option("rescuedDataColumn", "_rescued_data")  # columnas/filas que no encajan van acá, no se pierden
        .option("multiLine", "true")             # por si alguna descripción tiene saltos de línea
        .option("escape", '"')
        .csv(source_path)
        .withColumn("_source_file_path", F.col("_metadata.file_path"))
        .withColumn("_bronze_ingested_at", F.current_timestamp())
    )

    row_count = df.count()
    rescued_count = df.filter(F.col("_rescued_data").isNotNull()).count()
    print(f"  -> {row_count} filas leídas ({rescued_count} con datos rescatados)")
    if rescued_count > 0:
        print(f"  -> ATENCIÓN: revisar _rescued_data en {entity}, puede haber un cambio de formato en el CSV fuente")

    writer = (
        df.write
        .mode("overwrite")
        .option("overwriteSchema", "true")
    )

    partition_col = PARTITION_COLUMNS.get(entity)
    if partition_col:
        writer = writer.partitionBy(partition_col)

    writer.saveAsTable(target_table)

    partition_note = f" (particionada por {partition_col})" if partition_col else ""
    print(f"  -> escrito en {target_table}{partition_note}")

print("Bronze completo.")

# COMMAND ----------

# Validación rápida: conteo de filas y de filas rescatadas por tabla
for entity in ENTITIES:
    df = spark.table(f"{BRONZE_SCHEMA}.{entity}")
    n = df.count()
    rescued = df.filter(F.col("_rescued_data").isNotNull()).count()
    print(f"{entity}: {n} filas, {rescued} rescatadas")
