# State Ledger Walkthrough — What Gets Written to SQLite / DynamoDB

> [!NOTE]
> SQLite (local mode) and DynamoDB (production) store **identical data**. The only difference is the backend. This document uses the SQLite table names — DynamoDB uses the same fields as item attributes.

---

## Tables / Collections at a Glance

| Table (SQLite) | DynamoDB Table | Primary Key | Purpose |
|---|---|---|---|
| `runs` | `CatalogueSyncRuns` | `run_id` | One record per sync run — tracks overall pipeline phase, totals, and timestamps |
| `batches` | `CatalogueSyncBatches` | `(run_id, batch_id)` | One record per WMS batch — tracks per-batch state, attempts, accepted SKUs, and rejections |
| `dead_letters` | `CatalogueSyncDLQ` | `id` (SQLite auto-inc) / `run_id + sk` (DynamoDB) | One record per rejected or quarantined SKU with original payload and rejection reason |

---

## Scenario A — Normal Fresh Run (No Resume)

### Step 1 · Run starts → `runs` table INSERT

```python
# app/core/coordinator.py line 77
state.create_run(run)
```

A single row is **inserted** into `runs` (or `CatalogueSyncRuns`):

| Field | Value | Notes |
|---|---|---|
| `run_id` | `run_20261014_174432_a1b2c3d4` | Timestamp + UUID prefix |
| `status` | `INITIALIZING` | Initial state |
| `total_products` | `0` | Not yet known |
| `total_batches` | `0` | Not yet known |
| `accepted_count` | `0` | Default |
| `rejected_count` | `0` | Default |
| `ambiguous_count` | `0` | Default |
| `export_path` | `""` | Empty string initially |
| `created_at` | `2026-10-14T17:44:32Z` | UTC timestamp |
| `updated_at` | `2026-10-14T17:44:32Z` | Initial creation timestamp |
| `completed_at` | `NULL` | Not done yet |
| `error_message` | `""` | Clean state |

---

### Step 2 · Phase 1 begins → `runs` UPDATE (EXTRACTING)

```python
# app/core/coordinator.py line 87
state.update_run(run)
```

| Field | New Value | Changed? |
|---|---|---|
| `status` | `EXTRACTING` | ✅ Updated |
| `updated_at` | `<timestamp_now>` | ✅ Updated |
| *(all other fields)* | unchanged | — |

---

### Step 3 · Phase 1 done, CSV exported → `runs` UPDATE (STAGING)

```python
# app/core/coordinator.py line 105
state.update_run(run)
```

| Field | New Value | Changed? |
|---|---|---|
| `status` | `STAGING` | ✅ Updated |
| `total_products` | `12000` (example) | ✅ Updated with actual PIM count |
| `export_path` | `exports/2026-10-14/catalogue_run_....csv` | ✅ S3 key or local file path |
| `updated_at` | `<timestamp_now>` | ✅ Updated |

---

### Step 4 · Phase 2 — For each batch manifest → `batches` INSERT (×N)

```python
# app/core/coordinator.py line 141
state.create_batch(record)
```

One row is **inserted per batch** (e.g., 12,000 products ÷ 100 batch size = 120 rows):

| Field | Value | Notes |
|---|---|---|
| `run_id` | `run_20261014_174432_a1b2c3d4` | Associated run ID |
| `batch_id` | `batch_00001` … `batch_00120` | Zero-padded batch index |
| `status` | `PENDING` | Waiting for worker dispatch |
| `attempt_count` | `0` | Initial attempt count |
| `batch_size` | `100` | Sliced product count |
| `accepted_skus` | `[]` | Empty JSON list |
| `rejected_skus` | `[]` | Empty JSON list |
| `created_at` | `<timestamp_now>` | Manifest registration time |
| `updated_at` | `<timestamp_now>` | Same as creation |
| `error_message` | `""` | Clean state |

---

### Step 5 · Phase 2 done → `runs` UPDATE (INGESTING)

```python
# app/core/coordinator.py line 148
state.update_run(run)
```

| Field | New Value | Changed? |
|---|---|---|
| `status` | `INGESTING` | ✅ Updated |
| `total_batches` | `120` | ✅ Total batches registered |
| `updated_at` | `<timestamp_now>` | ✅ Updated |

---

### Step 6 · Phase 3 — Before dispatching to WMS → `batches` UPDATE (IN_FLIGHT)

```python
# app/services/warehouse_sync.py line 115
state.update_batch(batch_record)
```

Emitted **immediately before** making the HTTP call to WMS to track active execution:

| Field | New Value | Changed? |
|---|---|---|
| `status` | `IN_FLIGHT` | ✅ Updated |
| `attempt_count` | `1` | ✅ Incremented |
| `updated_at` | `<timestamp_now>` | ✅ Updated |

---

### Step 7a · Batch fully accepted by WMS → `batches` UPDATE (ACCEPTED)

```python
# app/services/warehouse_sync.py line 189
state.update_batch(batch_record)
```

| Field | New Value | Changed? |
|---|---|---|
| `status` | `ACCEPTED` | ✅ Updated |
| `accepted_skus` | `["P001", "P002", ...]` | ✅ Populated with accepted SKU list |
| `rejected_skus` | `[]` | Clean |
| `updated_at` | `<timestamp_now>` | ✅ Updated |

*(No entries added to `dead_letters`)*

---

### Step 7b · Batch partially accepted by WMS → `batches` UPDATE + `dead_letters` INSERTs

```python
# app/services/warehouse_sync.py line 156
state.add_dead_letter(...)  # One per rejected SKU

# app/services/warehouse_sync.py line 189
state.update_batch(batch_record)
```

**`batches` row update:**

| Field | New Value | Changed? |
|---|---|---|
| `status` | `PARTIAL_ACCEPTED` | ✅ Updated |
| `accepted_skus` | `["P001", "P003"]` | ✅ Accepted SKUs |
| `rejected_skus` | `[{"sku": "P002", "reason": "Invalid barcode"}]` | ✅ List of rejection objects |
| `updated_at` | `<timestamp_now>` | ✅ Updated |

**`dead_letters` row insertion (one row per rejected SKU):**

| Field | Value | Notes |
|---|---|---|
| `run_id` | `run_20261014_174432_a1b2c3d4` | Correlating run ID |
| `batch_id` | `batch_00003` | Origin batch |
| `sku` | `P002` | Rejected SKU |
| `reason` | `Invalid barcode` | Exact downstream rejection reason |
| `original_payload` | `{"sku": "P002", "description": ...}` | Full payload for inspection/replay |
| `created_at` | `<timestamp_now>` | Incident timestamp |

---

### Step 7c · Batch encounters post-send read timeout → `batches` UPDATE + `dead_letters` INSERTs

```python
# app/services/warehouse_sync.py line 136 - 147
batch_record.status = BatchStatus.AMBIGUOUS_TIMEOUT
# Quarantines each product in the batch to dead letters
# app/services/warehouse_sync.py line 149
state.update_batch(batch_record)
```

**`batches` row update:**

| Field | New Value | Notes |
|---|---|---|
| `status` | `AMBIGUOUS_TIMEOUT` | Quarantined; will not be blindly retried |
| `error_message` | `AMBIGUOUS_TIMEOUT: WMS outcome unknown` | |
| `accepted_skus` | `[]` | Unknown status |
| `rejected_skus` | `[]` | |
| `updated_at` | `<timestamp_now>` | |

**`dead_letters` row insertions:**
- Every product in that batch (e.g., all 100 SKUs) is logged into `dead_letters` with `reason = "AMBIGUOUS_TIMEOUT: WMS outcome unknown"`.

---

### Step 7d · Batch encounters network connection error → `batches` UPDATE (FAILED_RETRYABLE)

```python
# app/services/warehouse_sync.py line 124 - 126
batch_record.status = BatchStatus.FAILED_RETRYABLE
batch_record.error_message = str(exc)
state.update_batch(batch_record)
```

| Field | New Value | Notes |
|---|---|---|
| `status` | `FAILED_RETRYABLE` | Safe to retry on resume |
| `error_message` | `[Errno 111] Connection refused` | Logged exception detail |
| `updated_at` | `<timestamp_now>` | |

---

### Step 8 · Run completion → `runs` UPDATE (Final state)

```python
# app/core/coordinator.py line 209
state.update_run(run)
```

| Field | New Value | Notes |
|---|---|---|
| `status` | `COMPLETED` or `COMPLETED_WITH_REJECTIONS` or `FAILED` | Final run status |
| `accepted_count` | `11950` | Total accepted across all batches |
| `rejected_count` | `30` | Total rejected SKUs |
| `ambiguous_count` | `1` | Count of ambiguous batches quarantined |
| `completed_at` | `2026-10-14T18:02:11Z` | Finish UTC timestamp |
| `updated_at` | `<timestamp_now>` | |

---

## Scenario B — Resume Run Execution (`--resume-run-id=<id>`)

When resumed using `python -m app.main --resume-run-id=run_20261014_174432_a1b2c3d4`:

```python
# app/core/coordinator.py line 68
existing_run = state.get_run(run_id)
```

### 1. Run Record Lookup
- Does **NOT** issue an `INSERT INTO runs`.
- Loads the existing run record and inspects `status` and `export_path`.

### 2. Phase 1 Check (Extraction)
- If `export_path` is already populated in `runs`:
  - **Skips Phase 1 entirely** — no PIM API calls, no S3 re-upload, no DB writes.

### 3. Phase 2 Check (Staging / Manifest)
- For every batch parsed from the local CSV:
  ```python
  existing_batch = state.get_batch(run_id, batch_id)
  ```
  - If batch **already exists in `batches`**: Skipped, no new INSERT.
  - If batch is **missing**: Inserted with status `PENDING`.

### 4. Phase 3 Check (Batch Dispatch & Non-Duplication Guard)
Inside each worker thread:
```python
# app/services/warehouse_sync.py line 100 - 110
current = state.get_batch(run_id, batch_id)
if current and current.status in (BatchStatus.ACCEPTED, BatchStatus.PARTIAL_ACCEPTED):
    summary.record_skipped()
    return
```

| Existing Batch Status | Action on Resume | What gets written |
|---|---|---|
| `ACCEPTED` | **SKIPPED** | Zero DB writes, zero WMS calls |
| `PARTIAL_ACCEPTED` | **SKIPPED** | Zero DB writes, zero WMS calls (rejected SKUs remain in DLQ) |
| `AMBIGUOUS_TIMEOUT` | **SKIPPED** | Quarantined to prevent duplicate warehouse orders |
| `PENDING` | **DISPATCHED** | Moves `IN_FLIGHT` → `ACCEPTED` / `FAILED` |
| `FAILED_RETRYABLE` | **DISPATCHED** | Moves `IN_FLIGHT` → `ACCEPTED` / `FAILED` |
| `IN_FLIGHT` (crashed mid-run) | **DISPATCHED** | Moves `IN_FLIGHT` → `ACCEPTED` / `FAILED` |

### 5. Run Finalization on Resume
Once remaining batches finish:
- `runs` row is **UPDATED** with updated counts (`accepted_count`, `rejected_count`, `ambiguous_count`) and `completed_at`.

---

## Total DB Operations Summary (12,000 Products / 120 Batches)

| Phase | Event | SQLite / DynamoDB Operation | Operations Count |
|---|---|---|---|
| Initialization | Create Run record | `runs` INSERT / PutItem | 1 |
| Phase 1 | Start Extraction | `runs` UPDATE / PutItem | 1 |
| Phase 1 | Extraction Completed | `runs` UPDATE / PutItem | 1 |
| Phase 2 | Register 120 Batches | `batches` INSERT / PutItem | 120 |
| Phase 2 | Staging Completed | `runs` UPDATE / PutItem | 1 |
| Phase 3 | In-Flight Checkpoint (per batch) | `batches` UPDATE / PutItem | 120 |
| Phase 3 | Result Commit (per batch) | `batches` UPDATE / PutItem | 120 |
| Phase 3 | Rejections / DLQ (if any) | `dead_letters` INSERT / PutItem | 0 – N |
| Completion | Finalize Run Record | `runs` UPDATE / PutItem | 1 |
| **Total (clean run, 0 failures)** | | | **366 writes** |
