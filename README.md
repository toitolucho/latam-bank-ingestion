# latam-bank-ingestion

Config-driven Databricks Asset Bundle (DAB) to ingest LATAM Bank datasets from AWS S3 into Unity Catalog (Staging, Bronze & Silver SCD Type 2).

---

## 1. Bundle Configuration

| Input | Value | Used in |
|---|---|---|
| Bundle name | `latam-bank-ingestion` | `databricks.yml` |
| Bundle folder | `d:\Projects\Data Hackaton\latam-bank-ingestion` | local workspace |
| Workspace URL | `https://dbc-c48d6b98-036d.cloud.databricks.com` | `databricks.yml` |
| CLI profile name | `datathon-dev` | `databricks.yml`, CLI commands |
| Catalog | `workspace` | Unity Catalog catalog |
| SOR token | `latam_bank` | schemas `staging_latam_bank`, `bronze_latam_bank`, `silver_latam_bank` |
| Secret scope name | `aws-datathon` | YAML `s3_copy.secret_scope` |
| Secret key names | `aws-access-key-id`, `aws-secret-access-key` | YAML `s3_copy` auth block |
| S3 Bucket | `factored-datathon-2026-s3-157725502942-us-east-2-an` | S3 source |
| S3 Region | `us-east-2` | S3 client region |
| S3 Prefix | `data/` | S3 key prefix |
| First table | `branches` | `configs/sources/latam_bank_branches.yml` |

---

## 2. Ingestion Architecture (Pattern B — Option 2)

```text
s3://factored-datathon-2026-s3-157725502942-us-east-2-an/data/*.csv
  │  s3_copy task (Python, boto3, keys from secret scope 'aws-datathon')
  ▼
staging volume   /Volumes/workspace/staging_latam_bank/landing/<table>/
  │  file_loader pipeline (Auto Loader): CSV → rows, all STRING + file metadata
  ▼
staging table    workspace.staging_latam_bank.<table>
  │  staging_to_silver pipeline (bronze.py): append copy + _bronze_ingested_at
  ▼
bronze table     workspace.bronze_latam_bank.<table>
  │  staging_to_silver pipeline (silver.py): SCD Type 2 (when scd_2_key_list is populated)
  ▼
silver table     workspace.silver_latam_bank.<table>
```

---

## 3. Folder Tree

```text
latam-bank-ingestion/
├── .gitignore
├── README.md
├── databricks.yml
├── configs/
│   └── sources/
│       ├── _template.yml
│       └── latam_bank_branches.yml
├── resources/
│   ├── jobs/
│   │   └── latam_bank_files_to_silver.yml
│   └── pipelines/
│       ├── file_loader.pipeline.yml
│       └── staging_to_silver.pipeline.yml
└── src/
    ├── file_copy/
    │   ├── __init__.py
    │   └── s3_copy.py
    ├── python/
    │   └── run_s3_copy.py
    ├── pipelines/
    │   ├── file_loader/
    │   │   ├── axos_framework.py
    │   │   └── acquisition_file_pipeline.py
    │   └── staging_to_silver/
    │       ├── bronze.py
    │       └── silver.py
    └── utilities/
        └── schema_parser.py
```

---

## 4. Commands to Validate, Deploy, and Run

From the bundle directory (`d:\Projects\Data Hackaton\latam-bank-ingestion`):

```powershell
# 1. Validate bundle configuration
databricks bundle validate -t dev_sandbox --profile datathon-dev

# 2. Deploy bundle to workspace
databricks bundle deploy -t dev_sandbox --profile datathon-dev

# 3. Run the ingestion job
databricks bundle run latam_bank_files_to_silver -t dev_sandbox --profile datathon-dev
```
