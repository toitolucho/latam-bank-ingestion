# Architecture & Ingestion Strategy: Fact Tables vs. Dimension Tables

## 1. Executive Summary

This document evaluates the ingestion strategies for migrating LATAM Bank datasets from the AWS S3 datathon bucket (`factored-datathon-2026-s3-157725502942-us-east-2-an`) into Unity Catalog using the Databricks Asset Bundle (DAB).

It focuses specifically on the **Fact / High-Volume Event Tables** (`transactions`, `digital_events`, `campaign_sends`, `call_center_interactions`, `call_transcripts`, `complaints`, `satisfaction_surveys`), contrasting them against the already-active **Dimension Tables** (`branches`, `customers`, `products`, `service_agents`, `marketing_campaigns`, `daily_exchange_rates`).

---

## 2. Ingestion Options Comparison Matrix

| Evaluation Criteria | Option 1: Direct S3 Auto Loader | Option 2: SQL `COPY INTO` | Option 3 (Pattern B): S3 Copy ➔ UC Volume ➔ Auto Loader |
| :--- | :--- | :--- | :--- |
| **Mechanism** | `cloudFiles` directly on `s3://...` | Databricks SQL command with S3 credentials | Python (`boto3`) to `/Volumes/`, then DLT Auto Loader |
| **Serverless DLT Compatibility** | ❌ **Blocked** (Requires AWS IAM Role trust for UC External Location) | ⚠️ Partial (Runs in SQL Warehouse, not in DLT pipeline) | ✅ **100% Compatible** (Uses provided S3 Access Keys) |
| **Throughput & Parallelism** | ⭐⭐⭐ Maximum (Worker-level parallel streams) | ⭐⭐⭐ Maximum (Photon C++ accelerated) | ⭐⭐ High (Streaming chunks + multi-threaded download) |
| **Driver Disk Risk (`ENOSPC`)** | **Zero** (Distributed) | **Zero** (Distributed) | **Eliminated** if using streaming I/O (no `/tmp` buffering) |
| **Storage Overhead** | Single copy (Delta Lake only) | Single copy (Delta Lake only) | Temporary double copy (Volume + Delta Lake) |
| **Governance & Lineage** | Full Unity Catalog + DLT Lineage | Manual DDL / No DLT Lineage | Full Unity Catalog + DLT Lineage |
| **Best Used For** | Enterprise production with full AWS IAM admin rights | One-time ad-hoc batch loads | **Datathons / Free Trials with AWS Access Keys** |

---

## 3. Account & Environment Constraints

### 3.1 Databricks Free Trial Capabilities
* **Compute**: Running on **Databricks Serverless** (`serverless: true` and `serverless_default`). Compute starts in seconds and uses minimal DBU credits during pipeline runs.
* **Storage**: Unity Catalog Managed Storage and Volumes land in the workspace's underlying AWS S3 bucket (`__databricks_managed_storage_location`). Storage is virtually unlimited and inexpensive.
* **Verdict**: The free edition trial has **more than enough compute power and storage capacity** to ingest the entire hackathon dataset.

### 3.2 The Technical Blocker with Option 1 in Serverless
* **Why Option 1 cannot be used right now**:
  * Databricks Serverless Compute runs within Databricks' secure VPC control plane.
  * To access external S3 buckets directly, Serverless DLT **strictly requires a Unity Catalog Storage Credential + External Location**.
  * A UC AWS Storage Credential requires creating an **AWS IAM Role with a Trust Policy** pointing to Databricks' AWS Account ID.
  * The Datathon organizers provided **IAM User Access Keys** (`aws-access-key-id`, `aws-secret-access-key`), **not** an IAM Role ARN.
  * Serverless DLT intentionally ignores classic Hadoop S3A keys (`spark.hadoop.fs.s3a.access.key`).
* **Conclusion**: **Pattern B (S3 Copy to UC Volume ➔ Auto Loader) is the only viable option** under the provided hackathon credentials on Serverless compute.

---

## 4. Best Strategy Specifically for Fact Tables

Fact tables have distinct volume and velocity profiles compared to dimension tables:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        DATASET CLASSIFICATION                          │
├────────────────────────────────────────┬───────────────────────────────┤
│ DIMENSIONS (Low/Medium Volume)         │ FACTS (Massive/High Volume)   │
│ • branches                             │ • transactions                │
│ • customers                            │ • digital_events              │
│ • products                             │ • campaign_sends              │
│ • service_agents                       │ • call_center_interactions    │
│ • marketing_campaigns                  │ • call_transcripts            │
│ • daily_exchange_rates                 │ • complaints                  │
│                                        │ • satisfaction_surveys        │
│ ➔ Strategy: Pattern B + SCD Type 2     │ ➔ Strategy: Optimized B +     │
│    (Tracking historical changes)       │    Streaming Append (No SCD2) │
└────────────────────────────────────────┴───────────────────────────────┘
```

### Recommendation 1: Stream S3 Chunks Directly to Volume (Zero-Disk Buffering)
The standard `s3_copy.py` implementation used:
```python
handle, local_path = tempfile.mkstemp()
s3_client.download_file(bucket, key, local_path)
shutil.copyfile(local_path, target)
```
For multi-gigabyte fact files (e.g. `transactions.csv` or `digital_events.csv`), this exhausts the driver's local `/tmp` disk.  
**Optimization**: Stream binary chunks (e.g. 16MB buffers) directly from `s3_client.get_object()['Body']` into the `/Volumes/...` destination path. This keeps driver memory and disk usage near zero regardless of file size.

### Recommendation 2: Enable Multi-Threaded S3 Downloads
Use Python's `concurrent.futures.ThreadPoolExecutor(max_workers=8)` in `s3_copy.py` so that partitioned fact files or multiple tables download concurrently over high-bandwidth cloud networking rather than serially.

### Recommendation 3: Treat Fact Tables as Pure Append in Silver (Avoid SCD Type 2)
* **The Problem**: Dimension tables benefit from SCD Type 2 (`__START_AT`, `__END_AT`) because customer addresses or branch details change over time. However, **financial transactions and digital events are immutable historical facts**.
* **The Cost of SCD Type 2 on Facts**: Running `apply_changes` on millions of fact records computes historical state intervals across the entire table on every run, leading to high shuffle, memory pressure, and longer pipeline runtimes.
* **The Solution**: In `_latam_bank_transactions.yml` and `_latam_bank_digital_events.yml`:
  * Set `scd_type: 1` or configure them as **pure append streaming tables**.
  * Use **Liquid Clustering** or date-based clustering (`cluster_by: [transaction_date]`) to optimize analytical query performance without the overhead of historical interval tracking.

---

## 5. Phased Activation Plan

To ensure smooth ingestion within the free trial environment without timeouts:

1. **Phase 1: Ingest Dimension Tables (Completed & Validated)**
   * `branches`, `customers`, `products`, `service_agents`, `marketing_campaigns`, `daily_exchange_rates`.
   * Verified working via `databricks bundle run` in ~5 minutes.
2. **Phase 2: Optimize `s3_copy.py` (Streaming Buffer + Multi-threading)**
   * Deploy the streaming chunk update to prevent driver disk bottlenecks.
3. **Phase 3: Activate Medium Fact Tables**
   * Activate `complaints`, `satisfaction_surveys`, and `campaign_sends`.
   * Run and verify data quality in `workspace.silver_latam_bank`.
4. **Phase 4: Activate Large Fact Tables**
   * Activate `transactions`, `digital_events`, `call_center_interactions`, and `call_transcripts`.
   * Ensure fact configurations use append/clustering rather than expensive SCD2 interval calculation.

---

## 6. Summary Checklist for Fact Tables

| Stage | Optimal Configuration |
| :--- | :--- |
| **S3 Acquisition** | Pattern B with 16MB direct streaming buffer (no local `/tmp` files) |
| **Landing Volume** | `/Volumes/workspace/staging_latam_bank/landing/<fact_table>/` |
| **Auto Loader** | `cloudFiles.format = csv`, `schemaEvolutionMode = addNewColumns` |
| **Bronze Layer** | Append-only audit table with `_source_file_*` and ingestion timestamp |
| **Silver Layer** | Append or SCD Type 1 with clustering on transaction/event timestamp |
