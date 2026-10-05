# LATAM Bank — Databricks Ingestion & Medallion Data Platform (DAB)

Config-driven **Databricks Asset Bundle (DAB)** unifying AWS S3 ingestion, Delta Live Tables (DLT), and the full Medallion architecture (**Bronze**, **Silver with DQ gates**, and **Gold Credit Engine**) for the Factored AI & Data Hackathon 2026.

---

## 1. Quick Links for the Team

* **Databricks Workspace**: [https://dbc-c48d6b98-036d.cloud.databricks.com/?o=2631262910045932](https://dbc-c48d6b98-036d.cloud.databricks.com/?o=2631262910045932)
* **Catalog Explorer (Gold Layer)**: [workspace.gold_latam_bank](https://dbc-c48d6b98-036d.cloud.databricks.com/explore/data/workspace/gold_latam_bank?o=2631262910045932)
* **Catalog Explorer (Silver Layer)**: [workspace.silver_latam_bank](https://dbc-c48d6b98-036d.cloud.databricks.com/explore/data/workspace/silver_latam_bank?o=2631262910045932)
* **Catalog Explorer (Bronze Layer)**: [workspace.bronze_latam_bank](https://dbc-c48d6b98-036d.cloud.databricks.com/explore/data/workspace/bronze_latam_bank?o=2631262910045932)
* **Landing Volume**: [workspace.staging_latam_bank.landing](https://dbc-c48d6b98-036d.cloud.databricks.com/explore/data/volumes/workspace/staging_latam_bank/landing?o=2631262910045932)
* **Serving Export Volume**: [workspace.gold_latam_bank.exports](https://dbc-c48d6b98-036d.cloud.databricks.com/explore/data/volumes/workspace/gold_latam_bank/exports?o=2631262910045932)
* **SQL Editor**: [Databricks SQL Editor](https://dbc-c48d6b98-036d.cloud.databricks.com/sql/editor?o=2631262910045932)

> **Team Access**: All team members (`luis.molina-yampa@unosquare.com`, `vanessa.baez@unosquare.com`, `andres.rivero@unosquare.com`, `sergio.aguirre@unosquare.com`) have **Workspace Admin** roles, `ALL_PRIVILEGES` across all schemas/volumes, and `MANAGE` permissions on the `aws-datathon` secret scope.

---

## 2. End-to-End Medallion Architecture

```text
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
  │          • Reference tables: catalog, term grid, policy params/bands, segment adjustments
  ▼
Silver Tables: workspace.silver_latam_bank.<entity>
  │
  │  Task 3: silver_quality_checks (02_silver_quality_checks.sql)
  │          • Key duplicates, null thresholds, schema changes -> pipeline_quality_metrics
  ▼
Gold Engine: (gold/*.sql on Databricks SQL Warehouse)
  │          • customer_credit_profile: 20% DTI capacity, band rates, hard reason codes R01-R08
  │          • customer_credit_offer_options: 1.8M alternatives across products & terms
  │          • customer summaries: products, complaints, 90d cashflow, case context
  │          • fn_monthly_installment, fn_max_principal, credit_offers
  ▼
Gold Tables: workspace.gold_latam_bank.*
  │
  │  Task 4: gold_quality_checks (90_quality_checks.sql) & gold_export_for_serving (95_export_for_serving.py)
  ▼
Serving Export Volume: /Volumes/workspace/gold_latam_bank/exports/ (~30 MB Parquet)
```

---

## 3. Repository Structure

```text
latam-bank-ingestion/
├── configs/
│   └── sources/                    # Table configs (active: 9, muted: 4)
├── data/
│   ├── databricks/                 # Databricks Medallion Scripts & Notebooks
│   │   ├── 01_bronze.py            # Serverless PySpark bronze loader
│   │   ├── 02_silver.sql           # SQL warehouse silver typing & dedup
│   │   ├── 02_silver_quality_checks.sql # Silver DQ gate -> pipeline_quality_metrics
│   │   ├── load_silver_reference.sql    # Loads ref_* tables into Silver
│   │   ├── gold/                   # Gold SQLs (profile, options, summaries, UDFs)
│   │   │   ├── 00_deploy_objects.sql
│   │   │   ├── 10_customer_credit_profile.sql
│   │   │   ├── 20_customer_credit_offer_options.sql
│   │   │   ├── 30_customer_products_summary.sql
│   │   │   ├── 31_customer_complaints_summary.sql
│   │   │   ├── 32_customer_cashflow_summary.sql
│   │   │   ├── 33_customer_case_context.sql
│   │   │   ├── 90_quality_checks.sql
│   │   │   └── 95_export_for_serving.py
│   │   ├── resources/              # Bundle job definitions
│   │   └── tests/                  # Fixture update assertions
│   ├── reference/                  # CSV reference tables (catalog, grid, params)
│   └── scripts/                    # Reference loader, SQL runner, gold exporter
├── docs/                           # Data & Ingestion Architecture Documentation
│   ├── INGESTION_STRATEGY_FACT_TABLES.md # Fact tables & S3 streaming architecture
│   ├── CREDIT_RULES.md             # Policy version 0.4 business specification
│   └── DATA.md                     # Dataset findings, distributions & analysis
├── resources/                      # Root bundle definitions (jobs, pipelines)
│   ├── jobs/                       # latam_bank_files_to_silver.yml
│   └── pipelines/                  # Lakeflow DLT pipelines
├── src/                            # Ingestion framework & utilities
│   ├── file_copy/s3_copy.py        # 16 MB chunked streaming to Volume
│   ├── pipelines/                  # DLT pipeline code (file_loader, bronze, silver)
│   └── python/run_s3_copy.py       # Entrypoint for S3 copy task
├── databricks.yml                  # Unified Databricks Asset Bundle definition
└── .gitignore                      # Safeguards secrets, caches, and dumps
```

---

## 4. Databricks Workflows (Deploy & Run)

### 4.1 Authenticate CLI
```powershell
databricks auth login --host "https://dbc-c48d6b98-036d.cloud.databricks.com" --profile datathon-dev
```

### 4.2 Validate Bundle
```powershell
databricks bundle validate -t dev_sandbox --profile datathon-dev
```

### 4.3 Deploy to Workspace
```powershell
databricks bundle deploy -t dev_sandbox --profile datathon-dev
```

### 4.4 Run Pipelines

* **Run Full Medallion Pipeline** (S3 copy $\rightarrow$ Bronze $\rightarrow$ Silver $\rightarrow$ Gold $\rightarrow$ Export):
  ```powershell
  databricks bundle run latam_bank_medallion -t dev_sandbox --profile datathon-dev
  ```
  *(Or execute directly in the Databricks UI under **Jobs** $\rightarrow$ `[dev <your_name>] latam_bank_medallion`)*.

* **Run Fast Credit Policy Refresh** (~1 min):
  ```powershell
  databricks bundle run credit_policy_refresh -t dev_sandbox --profile datathon-dev
  ```

* **Run Lakeflow DLT Pipeline** (Declarative SCD Type 2 on Dimensions):
  ```powershell
  databricks bundle run latam_bank_files_to_silver -t dev_sandbox --profile datathon-dev
  ```

* **Run Data Update Correctness Test** (Fixture regression validation):
  ```powershell
  databricks bundle run data_update_fixture_test -t dev_sandbox --profile datathon-dev
  ```
