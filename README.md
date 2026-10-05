# LATAM Bank — Intelligent Credit Assistant & Unified Data Platform

Unified repository for the **Factored AI & Data Hackathon 2026**: combining config-driven AWS S3 ingestion, Databricks Medallion architecture (Bronze, Silver, Gold), and a production-grade conversational AI assistant with deterministic credit policy execution.

---

## 1. Quick Links for the Team

* **Databricks Workspace**: [https://dbc-c48d6b98-036d.cloud.databricks.com/?o=2631262910045932](https://dbc-c48d6b98-036d.cloud.databricks.com/?o=2631262910045932)
* **Catalog Explorer (Gold Layer)**: [workspace.gold_latam_bank](https://dbc-c48d6b98-036d.cloud.databricks.com/explore/data/workspace/gold_latam_bank?o=2631262910045932)
* **Catalog Explorer (Silver Layer)**: [workspace.silver_latam_bank](https://dbc-c48d6b98-036d.cloud.databricks.com/explore/data/workspace/silver_latam_bank?o=2631262910045932)
* **Catalog Explorer (Bronze Layer)**: [workspace.bronze_latam_bank](https://dbc-c48d6b98-036d.cloud.databricks.com/explore/data/workspace/bronze_latam_bank?o=2631262910045932)
* **Landing Volume**: [workspace.staging_latam_bank.landing](https://dbc-c48d6b98-036d.cloud.databricks.com/explore/data/volumes/workspace/staging_latam_bank/landing?o=2631262910045932)
* **Serving Export Volume**: [workspace.gold_latam_bank.exports](https://dbc-c48d6b98-036d.cloud.databricks.com/explore/data/volumes/workspace/gold_latam_bank/exports?o=2631262910045932)
* **GitHub Repository**: [https://github.com/toitolucho/latam-bank-ingestion](https://github.com/toitolucho/latam-bank-ingestion)

> **Team Access**: Team members (luis.molina-yampa@unosquare.com, anessa.baez@unosquare.com, ndres.rivero@unosquare.com, sergio.aguirre@unosquare.com) have **Workspace Admin** roles, ALL_PRIVILEGES across all schemas/volumes, and MANAGE permissions on the ws-datathon secret scope.

---

## 2. End-to-End Architecture & Data Flow

`	ext
AWS S3 Bucket (s3://factored-datathon-2026-s3-157725502942-us-east-2-an/data/)
  │
  │  Task 0: s3_copy (boto3, 16 MB chunked streaming, secret scope 'aws-datathon')
  ▼
Landing Volume: /Volumes/workspace/staging_latam_bank/landing/<entity>/
  │
  │  Task 1: bronze_load (PySpark serverless notebook 01_bronze.py)
  │          • Explicit schemas, all STRING, _rescued_data for schema evolution
  ▼
Bronze Tables: workspace.bronze_latam_bank.<entity>
  │
  │  Task 2: silver_typed_dedup (SQL warehouse 02_silver.sql & load_silver_reference.sql)
  │          • Typed, deduplicated (ROW_NUMBER() = 1), partitioned by process_date
  │          • Joins synthetic reference tables (catalog, term grid, policy params/bands)
  ▼
Silver Tables: workspace.silver_latam_bank.<entity>
  │
  │  Task 3: silver_quality_checks (02_silver_quality_checks.sql)
  │          • Duplicates, null thresholds, schema checks -> pipeline_quality_metrics
  ▼
Gold Engine: (gold/*.sql on Databricks SQL Warehouse)
  │          • customer_credit_profile: 20% DTI capacity, band rates, hard reason codes R01-R08
  │          • customer_credit_offer_options: 1.8M alternatives across products & terms
  │          • customer summaries: products, complaints, 90d cashflow, case context
  │          • fn_monthly_installment, fn_max_principal, credit_offers
  ▼
Gold Tables:   workspace.gold_latam_bank.*
  │
  │  Task 4: gold_quality_checks (90_quality_checks.sql) & gold_export_for_serving (95_export_for_serving.py)
  ▼
Serving Volume: /Volumes/workspace/gold_latam_bank/exports/ (~30 MB Parquet)
  │
  │  Local Download: python data/scripts/export_gold.py --profile datathon-dev
  ▼
FastAPI AI Backend (Agent, State Machine, Security Questions, Policy Engine)
  │
  ▼
Web Chat UI (Vanilla HTML/CSS/JS + Nginx Proxy at http://localhost:8080)
`

---

## 3. Repository Structure

`	ext
latam-bank-ingestion/
├── backend/                        # FastAPI conversational AI service
│   ├── app/                        # Agent, orchestrator, tools, policy, routes
│   ├── data/fixture/               # Synthetic test fixture parquets (offline testing)
│   ├── eval/                       # NLU benchmark suite
│   ├── tests/                      # 155 unit & integration tests
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                       # Web chat interface
│   ├── assets/
│   ├── nginx/                      # Reverse proxy configuration
│   ├── index.html, styles.css, app.js
│   └── Dockerfile
├── configs/sources/                # Ingestion table configs (branches, customers, transactions...)
├── data/
│   ├── databricks/                 # Databricks Medallion & Credit Gold
│   │   ├── 01_bronze.py            # Serverless PySpark bronze loader
│   │   ├── 02_silver.sql           # SQL warehouse silver typing & dedup
│   │   ├── 02_silver_quality_checks.sql # Silver quality gate
│   │   ├── load_silver_reference.sql    # Reference data loader
│   │   ├── gold/                   # Gold SQLs (profile, options, summaries)
│   │   ├── resources/              # Bundle jobs (latam_bank_medallion.job.yml, etc.)
│   │   └── tests/                  # Fixture update assertions
│   ├── policy/                     # Python reference credit policy engine & tests
│   ├── reference/                  # CSV reference tables (catalog, grid, params)
│   └── scripts/                    # Reference loading, SQL runner, parity checker
├── analysis/                       # EDA notebooks & fraud baseline models
├── docs/                           # Centralized documentation
│   ├── INGESTION_STRATEGY_FACT_TABLES.md # Fact tables & S3 streaming architecture
│   ├── ARCHITECTURE.md             # System architecture & decision records
│   ├── CREDIT_RULES.md             # Business credit policy 0.4 specification
│   ├── DATA.md                     # Dataset analysis & quality report
│   ├── EVALUATION.md               # Model & conversational metrics
│   ├── RUNBOOK.md                  # Run & verify operations guide
│   └── ENGINE_ALIGNMENT.md         # Python vs SQL parity tracker
├── resources/                      # Root bundle definitions (jobs, pipelines)
├── src/                            # Ingestion framework & utilities (s3_copy, DLT)
├── databricks.yml                  # Unified Databricks Asset Bundle definition
├── docker-compose.yml              # Local containerized demo
└── .env.example
`

---

## 4. How to Run Locally (Docker Demo)

The web chat and backend can run 100% locally with zero cloud dependencies using the bundled synthetic fixtures:

`ash
# 1. Clone repository
git clone https://github.com/toitolucho/latam-bank-ingestion.git
cd latam-bank-ingestion

# 2. Build and launch containers
docker compose up --build
`
Open **[http://localhost:8080](http://localhost:8080)** in your browser.
* Test credentials and sample customers: [backend/DATOS_DE_PRUEBA.md](backend/DATOS_DE_PRUEBA.md).
* To use Claude LLM instead of rule-based NLU: copy ackend/.env.example to ackend/.env and set CHAT_LLM_PROVIDER=anthropic and ANTHROPIC_API_KEY.

---

## 5. Databricks Workflows (Deploy & Run)

### 5.1 Authenticate CLI
`ash
databricks auth login --host "https://dbc-c48d6b98-036d.cloud.databricks.com" --profile datathon-dev
`

### 5.2 Validate Bundle
`ash
databricks bundle validate -t dev_sandbox --profile datathon-dev
`

### 5.3 Deploy to Databricks
`ash
databricks bundle deploy -t dev_sandbox --profile datathon-dev
`

### 5.4 Execute Pipeline Jobs
* **Run Full End-to-End Medallion Pipeline** (S3 copy $\rightarrow$ Bronze $\rightarrow$ Silver $\rightarrow$ Gold $\rightarrow$ Export):
  `ash
  databricks bundle run latam_bank_medallion -t dev_sandbox --profile datathon-dev --var="warehouse_id=<sql-warehouse-id>"
  `
* **Run DLT Ingestion Pipeline** (Continuous/SCD2 Lakeflow):
  `ash
  databricks bundle run latam_bank_files_to_silver -t dev_sandbox --profile datathon-dev
  `
* **Run Fast Credit Policy Refresh** (~1 min):
  `ash
  databricks bundle run credit_policy_refresh -t dev_sandbox --profile datathon-dev --var="warehouse_id=<sql-warehouse-id>"
  `

---

## 6. Downloading Gold Exports for Serving

Once latam_bank_medallion completes, download the exported Parquet files to feed the backend:

`ash
python data/scripts/export_gold.py --profile datathon-dev --out .local/gold
`
The backend automatically detects .local/gold/ and uses live exported data instead of synthetic fixtures.
