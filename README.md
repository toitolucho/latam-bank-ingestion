# LATAM Bank — Databricks Ingestion Bundle (DAB)

Config-driven Databricks Asset Bundle (DAB) to ingest LATAM Bank datasets from AWS S3 into Unity Catalog following Medallion Architecture (**Staging**, **Bronze**, and **Silver SCD Type 2**).

---

## 1. Quick Links for the Team

* **Databricks Workspace**: [https://dbc-c48d6b98-036d.cloud.databricks.com/?o=2631262910045932](https://dbc-c48d6b98-036d.cloud.databricks.com/?o=2631262910045932)
* **Catalog Explorer (Silver Layer)**: [workspace.silver_latam_bank](https://dbc-c48d6b98-036d.cloud.databricks.com/explore/data/workspace/silver_latam_bank?o=2631262910045932)
* **Catalog Explorer (Bronze Layer)**: [workspace.bronze_latam_bank](https://dbc-c48d6b98-036d.cloud.databricks.com/explore/data/workspace/bronze_latam_bank?o=2631262910045932)
* **Landing Volume**: [workspace.staging_latam_bank.landing](https://dbc-c48d6b98-036d.cloud.databricks.com/explore/data/volumes/workspace/staging_latam_bank/landing?o=2631262910045932)
* **SQL Editor**: [Databricks SQL Editor](https://dbc-c48d6b98-036d.cloud.databricks.com/sql/editor?o=2631262910045932)
* **GitHub Repository**: [https://github.com/toitolucho/latam-bank-ingestion](https://github.com/toitolucho/latam-bank-ingestion)

> **Team Access**: All team members (`luis.molina-yampa@unosquare.com`, `vanessa.baez@unosquare.com`, `andres.rivero@unosquare.com`, `sergio.aguirre@unosquare.com`) have **Workspace Admin** roles, `ALL_PRIVILEGES` across all schemas/volumes, and `MANAGE` permissions on the `aws-datathon` secret scope.

---

## 2. Architecture & Data Flow

> 📖 **Deep Dive**: See [docs/INGESTION_STRATEGY_FACT_TABLES.md](docs/INGESTION_STRATEGY_FACT_TABLES.md) for the architecture analysis comparing S3 ingestion options, free-tier limits, and specific performance recommendations for massive fact tables.

```text
AWS S3 Bucket (s3://factored-datathon-2026-s3-157725502942-us-east-2-an/data/)
  │
  │  Task 1: s3_copy (Python, boto3, credentials read via dbutils.secrets from 'aws-datathon')
  ▼
Staging Volume: /Volumes/workspace/staging_latam_bank/landing/<source_table>/
  │
  │  Task 2: file_loader_to_staging (Delta Live Tables / Auto Loader streaming table)
  │          • Reads CSVs, sets columns to STRING, adds file provenance (_source_file_*, _staging_ingested_at)
  ▼
Staging Table: workspace.staging_latam_bank.<source_table>
  │
  │  Task 3: staging_to_silver (Delta Live Tables / Lakeflow pipeline)
  │          ├── bronze.py: Pure append audit layer, sanitizes column names, stamps _bronze_ingested_at
  ▼
Bronze Table:  workspace.bronze_latam_bank.<source_table>
  │          └── silver.py: Slowly Changing Dimension (SCD Type 2) via apply_changes
  │                         Tracks history, sets __START_AT and __END_AT, enforces Data Quality rules
  ▼
Silver Table:  workspace.silver_latam_bank.<source_table>
Quarantine:    workspace.silver_latam_bank.<source_table>_qtn (rows failing Data Quality rules)
```

---

## 3. Team Member Local Setup (How to Deploy by Yourself)

Every team member can deploy and run their own isolated copy of the ingestion pipeline in development mode without interfering with others.

### Step 3.1: Install Prerequisites

1. **Git**: [git-scm.com](https://git-scm.com/)
2. **Python 3.10+**: [python.org](https://python.org/)
3. **Databricks CLI** (version `0.2xx` or `1.x`):
   * **Windows (PowerShell)**:
     ```powershell
     winget install --id Databricks.DatabricksCLI -e
     ```
   * **Mac / Linux**:
     ```bash
     brew tap databricks/tap
     brew install databricks
     ```
   Verify installation:
   ```bash
   databricks --version
   ```

### Step 3.2: Clone the Repository

```bash
git clone https://github.com/toitolucho/latam-bank-ingestion.git
cd latam-bank-ingestion
```

### Step 3.3: Authenticate Databricks CLI

Authenticate your CLI to our shared workspace using the profile name `datathon-dev`:

```bash
databricks auth login --host "https://dbc-c48d6b98-036d.cloud.databricks.com" --profile datathon-dev
```
A browser tab will open automatically. Sign in with your `@unosquare.com` email and click **Authorize**.

Verify your login:
```bash
databricks current-user me --profile datathon-dev
```

---

## 4. Development Workflow: Validate, Deploy & Run

Because the bundle is configured with `mode: development` (`dev_sandbox` target):
* Jobs in Databricks are automatically prefixed with your username: `[dev <your_name>] latam_bank_files_to_silver`.
* Workspace files deploy to your own user directory: `/Users/<your_email>/.bundle/latam-bank-ingestion/dev_sandbox/`.
* **Team members can deploy safely at any time without overwriting each other.**

### Step 4.1: Validate Configuration
Before deploying, validate the bundle YAML definitions:
```bash
databricks bundle validate -t dev_sandbox --profile datathon-dev
```
*(Should output `Validation OK!`)*

### Step 4.2: Deploy to Workspace
Upload your code files and create/update your dev workflows:
```bash
databricks bundle deploy -t dev_sandbox --profile datathon-dev
```

### Step 4.3: Trigger Job Execution
Run the ingestion pipeline:
```bash
databricks bundle run latam_bank_files_to_silver -t dev_sandbox --profile datathon-dev
```
You can monitor the real-time execution in the Databricks UI under **Jobs & Pipelines** (or **Workflows**) $\rightarrow$ `[dev <your_name>] latam_bank_files_to_silver`.

---

## 5. Adding or Activating Tables

The bundle is **100% config-driven**: every `.yml` file in `configs/sources/` defines one table.

### Rules:
* Files starting with an underscore (`_`) are **muted/ignored** by the ingestion engine (e.g. `_template.yml`).
* Files without an underscore are **active** and will be processed.

### How to Activate an Existing Table:
To activate one of the prepared tables, rename the file to remove the leading `_`:
```bash
# Example: activate customers
mv configs/sources/_latam_bank_customers.yml configs/sources/latam_bank_customers.yml
```
Then run `databricks bundle deploy` and `databricks bundle run`.

### Table Inventory Status:

| Table Name | File | Status | Layer Targets |
|---|---|---|---|
| `branches` | `latam_bank_branches.yml` | **Active** | Staging $\rightarrow$ Bronze $\rightarrow$ Silver SCD2 |
| `customers` | `latam_bank_customers.yml` | **Active** | Staging $\rightarrow$ Bronze $\rightarrow$ Silver SCD2 |
| `products` | `latam_bank_products.yml` | **Active** | Staging $\rightarrow$ Bronze $\rightarrow$ Silver SCD2 |
| `service_agents` | `latam_bank_service_agents.yml` | **Active** | Staging $\rightarrow$ Bronze $\rightarrow$ Silver SCD2 |
| `marketing_campaigns` | `latam_bank_marketing_campaigns.yml` | **Active** | Staging $\rightarrow$ Bronze $\rightarrow$ Silver SCD2 |
| `daily_exchange_rates` | `latam_bank_daily_exchange_rates.yml` | **Active** | Staging $\rightarrow$ Bronze $\rightarrow$ Silver SCD2 |
| `transactions` | `_latam_bank_transactions.yml` | Staged (Muted) | Staging $\rightarrow$ Bronze $\rightarrow$ Silver SCD2 |
| `complaints` | `_latam_bank_complaints.yml` | Staged (Muted) | Staging $\rightarrow$ Bronze $\rightarrow$ Silver SCD2 |
| `call_center_interactions` | `_latam_bank_call_center_interactions.yml` | Staged (Muted) | Staging $\rightarrow$ Bronze $\rightarrow$ Silver SCD2 |
| `call_transcripts` | `_latam_bank_call_transcripts.yml` | Staged (Muted) | Staging $\rightarrow$ Bronze $\rightarrow$ Silver SCD2 |
| `campaign_sends` | `_latam_bank_campaign_sends.yml` | Staged (Muted) | Staging $\rightarrow$ Bronze $\rightarrow$ Silver SCD2 |
| `digital_events` | `_latam_bank_digital_events.yml` | Staged (Muted) | Staging $\rightarrow$ Bronze $\rightarrow$ Silver SCD2 |
| `satisfaction_surveys` | `_latam_bank_satisfaction_surveys.yml` | Staged (Muted) | Staging $\rightarrow$ Bronze $\rightarrow$ Silver SCD2 |

---

## 6. Verification SQL Queries

Open the **SQL Editor** in Databricks and run these queries to inspect data across layers:

```sql
-- 1. Check raw landing volume files
LIST '/Volumes/workspace/staging_latam_bank/landing/branches/';

-- 2. Check Bronze row counts (immutable audit log)
SELECT 'branches' AS table_name, COUNT(*) AS bronze_rows FROM workspace.bronze_latam_bank.branches
UNION ALL
SELECT 'customers', COUNT(*) FROM workspace.bronze_latam_bank.customers;

-- 3. Check Silver SCD Type 2 active current records
SELECT branch_id, branch_name, city, country, __START_AT, __END_AT
FROM workspace.silver_latam_bank.branches
WHERE __END_AT IS NULL
LIMIT 10;

-- 4. Check if any rows failed Data Quality rules (Quarantine table)
SELECT * FROM workspace.silver_latam_bank.branches_qtn;
```

---

## 7. Troubleshooting & Gotchas

* **`Silver table missing after first run`**:  
  When adding a new table for the very first time, the Silver pipeline compiles *before* the Bronze table is created by the upstream task. Simply run `databricks bundle run` a second time — Silver will detect the newly created Bronze table and build the SCD Type 2 table.
* **`Refresh token is invalid`**:  
  Your local CLI session expired. Re-authenticate with:
  ```bash
  databricks auth login --host "https://dbc-c48d6b98-036d.cloud.databricks.com" --profile datathon-dev
  ```
* **Clean Sandbox Deployment**:  
  To delete your sandbox job and pipelines from Databricks (tables remain intact):
  ```bash
  databricks bundle destroy -t dev_sandbox --profile datathon-dev
  ```
