# Architecture and Ingestion Strategy: High-Volume Fact Tables

## 1. Executive Summary

This report evaluates data ingestion architectures for transferring LATAM Bank datasets from the AWS S3 source bucket (`factored-datathon-2026-s3-157725502942-us-east-2-an`) into Unity Catalog using the Databricks Asset Bundle (DAB) framework.

The analysis specifically addresses the technical requirements of **High-Volume Fact and Event Tables** (`transactions`, `digital_events`, `campaign_sends`, `call_center_interactions`, `call_transcripts`, `complaints`, `satisfaction_surveys`), contrasting their operational profile against the existing **Dimension Tables** (`branches`, `customers`, `products`, `service_agents`, `marketing_campaigns`, `daily_exchange_rates`).

---

## 2. Technical Comparison of Ingestion Architectures

Three primary architectures were evaluated for ingesting large datasets into Databricks:

| Evaluation Dimension | Option 1: Direct S3 Auto Loader | Option 2: SQL COPY INTO | Option 3 (Pattern B): S3 Copy to Volume and Auto Loader |
| :--- | :--- | :--- | :--- |
| **Mechanism** | Auto Loader (`cloudFiles`) directly against `s3://` URIs | Photon-accelerated SQL command | Python (`boto3`) to Unity Catalog Volume, then Auto Loader |
| **Serverless DLT Compatibility** | Incompatible without IAM Role | Partial (Requires SQL Warehouse execution) | Fully Compatible with IAM User Access Keys |
| **Throughput Capacity** | High (Distributed parallel workers) | High (C++ native engine) | High (Configurable via multi-threading and streaming I/O) |
| **Driver Storage Risk** | None (Fully distributed) | None (Fully distributed) | Eliminated using direct memory streaming (no local disk buffering) |
| **Storage Multiplicity** | Single (Delta Lake storage only) | Single (Delta Lake storage only) | Transient duplicate (Volume staging plus Delta Lake) |
| **Data Lineage and Governance** | Native Unity Catalog and DLT pipeline | Manual SQL definition / Out of DLT flow | Native Unity Catalog and DLT pipeline |
| **Applicability** | Enterprise environments with full AWS IAM control | Ad-hoc one-off batch ingestion | Environments restricted to IAM User Access Keys |

---

## 3. Platform Constraints and Authentication Analysis

### 3.1 Databricks Free Trial Compute and Storage Capacity
* **Compute Resources**: The workspace utilizes Databricks Serverless Compute (`serverless: true` for Delta Live Tables pipelines and `serverless_default` for job tasks). Compute provisioning occurs on-demand within seconds and consumes negligible Databricks Units (DBU) for dataset ingestion.
* **Storage Allocation**: Managed tables and Unity Catalog Volumes reside within the workspace root S3 bucket (`__databricks_managed_storage_location`). Storage capacity is scalable and introduces no functional capacity barriers for the hackathon volume.
* **Assessment**: Compute capacity and storage limits in the free edition trial are fully sufficient to ingest and process all tables.

### 3.2 Serverless Delta Live Tables Authentication Constraint
* **Option 1 Restriction**:
  * Databricks Serverless compute runs inside the Databricks-managed cloud network.
  * Direct access from Serverless DLT to external AWS S3 buckets requires a Unity Catalog **Storage Credential** coupled with an **External Location**.
  * Unity Catalog Storage Credentials on AWS mandate an **AWS IAM Role ARN** configured with a Trust Relationship authorizing the Databricks AWS Account.
  * The dataset source credentials provided by the organizers consist of **IAM User Access Keys** (`aws-access-key-id`, `aws-secret-access-key`) managed in Secret Scope `aws-datathon`.
  * Serverless DLT intentionally disallows legacy Hadoop-level configurations (`spark.hadoop.fs.s3a.access.key`).
* **Operational Implication**: Direct S3 streaming via Option 1 cannot authenticate under the provided credential model. **Pattern B (S3 Copy to Volume, followed by Auto Loader) is the technically valid and compliant design pattern.**

---

## 4. Architectural Analysis for Fact Tables vs. Dimension Tables

Datasets within the LATAM Bank domain exhibit distinct analytical characteristics and processing requirements:

```text
+-------------------------------------------------------------------------+
|                        DATASET CLASSIFICATION                           |
+------------------------------------+------------------------------------+
| DIMENSION TABLES (Low/Medium Scale)| FACT TABLES (High/Massive Scale)   |
| - branches                         | - transactions                     |
| - customers                        | - digital_events                   |
| - products                         | - campaign_sends                   |
| - service_agents                   | - call_center_interactions         |
| - marketing_campaigns              | - call_transcripts                 |
| - daily_exchange_rates             | - complaints                       |
|                                    | - satisfaction_surveys             |
| Recommended Pattern:               | Recommended Pattern:               |
| Pattern B with SCD Type 2 tracking | Optimized Pattern B with Streaming |
| (__START_AT, __END_AT intervals)   | Append (No SCD Type 2 calculation) |
+------------------------------------+------------------------------------+
```

### 4.1 Ingestion Layer: Streaming Transfer to Unity Catalog Volumes
In the initial implementation of `s3_copy.py`, files were retrieved via `tempfile.mkstemp()`, downloaded locally to the driver `/tmp` partition, and transferred using `shutil.copyfile()`.

For multi-gigabyte fact tables (such as `transactions` and `digital_events`), local driver staging risks file system exhaustion (`No space left on device`).

**Required Technical Design**:
* Direct binary stream consumption from `s3_client.get_object()['Body']` into the target volume path (`/Volumes/workspace/staging_latam_bank/landing/<table_name>/`) using a chunked buffer (e.g., 16 MB).
* File system disk consumption on the driver node is reduced to near zero.
* Integration of Python `concurrent.futures.ThreadPoolExecutor` to handle concurrent downloads across multiple tables and partitioned file lists.

### 4.2 Silver Layer: Append-Only Processing (Eliminating SCD Type 2 on Facts)
* **Operational Overhead of SCD Type 2**:
  SCD Type 2 processing relies on Delta Live Tables `apply_changes` to compute validity intervals (`__START_AT`, `__END_AT`) and update flag statuses. While appropriate for slowly changing dimensions where historical attribute changes must be preserved, running this operation across millions of append-only fact records forces intensive shuffle, state store memory bloat, and prolonged pipeline execution times.
* **Design Recommendation for Fact Tables**:
  * Configure Silver models for fact tables as **Append-Only streaming tables** or **SCD Type 1 with deduplication**.
  * Apply **Liquid Clustering** or date-based clustering (`cluster_by: [transaction_date]`) on high-cardinality timestamp fields to maximize query execution performance across analytical workloads.

---

## 5. Technical Recommendations for Fact Tables

1. **Ingestion Component (`s3_copy.py`)**:
   * Implement stream-to-volume write operations to prevent local disk exhaustion.
   * Enable parallel worker threads for multi-file downloads.
2. **Auto Loader Configuration (`acquisition_file_pipeline.py`)**:
   * Retain `cloudFiles.format = csv` and `cloudFiles.schemaEvolutionMode = addNewColumns`.
   * Preserve raw string typing in Staging to ensure deterministic landing without schema failure.
3. **Bronze Transformation (`bronze.py`)**:
   * Enforce append-only ingestion with schema validation and technical metadata tracking (`_source_file_path`, `_bronze_ingested_at`).
4. **Silver Transformation (`silver.py`)**:
   * Bypass SCD Type 2 logic for fact tables; persist as immutable event records.
   * Implement liquid clustering on temporal dimensions.

---

## 6. Phased Rollout Plan

| Phase | Scope | Objective | Status |
| :--- | :--- | :--- | :--- |
| **Phase 1** | Dimension Tables | Ingest `branches`, `customers`, `products`, `service_agents`, `marketing_campaigns`, `daily_exchange_rates` with SCD Type 2. | Completed |
| **Phase 2** | Ingestion Engine Optimization | Refactor `s3_copy.py` with chunked memory streaming and thread-pool execution. | Ready for deployment |
| **Phase 3** | Medium-Volume Fact Tables | Activate `complaints`, `satisfaction_surveys`, and `campaign_sends`. Validate data quality expectations. | Pending Phase 2 |
| **Phase 4** | High-Volume Fact Tables | Activate `transactions`, `digital_events`, `call_center_interactions`, and `call_transcripts` using append-only Silver tables. | Pending Phase 3 |

---

## 7. Governance and Quality Assurance

* **Data Quality Constraints**: Fact tables must enforce primary key non-null expectations via dataset configurations (e.g., `transaction_id IS NOT NULL`).
* **Quarantine Management**: Rows failing data quality rules are routed to dedicated quarantine tables (`workspace.silver_latam_bank.<table_name>_qtn`) for audit and reconciliation without failing pipeline execution.
* **Audit Trail**: Technical lineage columns (`_source_file_path`, `_source_file_size`, `_source_file_modified`, `_staging_ingested_at`, `_bronze_ingested_at`) must remain attached across all layers for compliance.
