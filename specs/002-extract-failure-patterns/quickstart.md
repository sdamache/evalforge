# Quickstart: Failure Pattern Extraction

This guide explains how to run the batch extraction service that converts captured failure traces into structured failure patterns.

## Prerequisites

- Python 3.11
- Google Cloud project with:
  - Cloud Run
  - Firestore
  - Secret Manager
  - Cloud Scheduler
  - Vertex AI API enabled (for Gemini access)
- Ingestion service is already capturing failures into Firestore collection `evalforge_raw_traces`.

> **SDK Note**: This service uses the **`google-genai` SDK** for Gemini access. The legacy `vertexai.generative_models` module is deprecated (June 2025) and will be removed June 2026.

## Environment Configuration

Set environment variables for the extraction service:

```bash
# Firestore
FIRESTORE_COLLECTION_PREFIX=evalforge_
FIRESTORE_DATABASE_ID=(default)

# Gemini (via google-genai SDK)
GOOGLE_CLOUD_PROJECT=your-gcp-project      # Used by google-genai for auth
VERTEX_AI_LOCATION=us-central1
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TEMPERATURE=0.2
GEMINI_MAX_OUTPUT_TOKENS=4096              # Default cap; tune down if latency/cost requires

# Batch processing
BATCH_SIZE=50
```

## Local Development Flow

1. Create/activate the shared venv and install deps:

```bash
python -m venv evalforge_venv
source evalforge_venv/bin/activate
pip install -e ".[dev]"
```

2. Run the extraction service locally (FastAPI):

```bash
evalforge_venv/bin/uvicorn src.extraction.main:app --reload --port 8002
```

3. Trigger an extraction run:

```bash
curl -X POST "http://localhost:8002/extraction/run-once" \
  -H "Content-Type: application/json" \
  -d '{"batchSize":50,"triggeredBy":"manual"}'
```

4. Verify outputs:

- Firestore input collection: `evalforge_raw_traces` (documents transition from `processed=false` to `processed=true` after successful extraction)
- Firestore output collection: `evalforge_failure_patterns` (one document per `source_trace_id`)

## Validation

### Local Run Validation

Use the provided helper script for local testing:

```bash
# Run extraction once with default settings (5 traces)
./scripts/run_extraction_once.sh

# Custom batch size
BATCH_SIZE=10 ./scripts/run_extraction_once.sh

# Dry run (don't write results)
DRY_RUN=true ./scripts/run_extraction_once.sh

# Use Firestore emulator
USE_EMULATOR=true ./scripts/run_extraction_once.sh
```

**Expected output**:

```json
{
  "runId": "run_20241223_103045_abc123",
  "triggeredBy": "manual",
  "pickedUpCount": 5,
  "storedCount": 5,
  "errorCount": 0,
  "validationErrorCount": 0,
  "timeoutCount": 0,
  "durationSeconds": 12.34,
  "modelConfig": {
    "model": "gemini-2.5-flash",
    "temperature": 0.2,
    "maxOutputTokens": 4096
  }
}
```

### Verify Firestore Writes

After running extraction, check Firestore collections:

**1. Input collection (`evalforge_raw_traces`)**:

```bash
# Query processed traces
gcloud firestore query --collection-id=evalforge_raw_traces \
  --filter="processed=true" \
  --limit=5
```

Expected: Traces that were picked up should have `processed=true` and `processed_at` timestamp.

**2. Output collection (`evalforge_failure_patterns`)**:

```bash
# Query extracted patterns
gcloud firestore query --collection-id=evalforge_failure_patterns \
  --order-by=extracted_at DESC \
  --limit=5
```

Expected documents with structure:

```json
{
  "pattern_id": "pattern_abc123_def456",
  "source_trace_id": "abc123",
  "title": "Hallucination: Incorrect historical date",
  "failure_type": "hallucination",
  "trigger_condition": "Factual error in historical date response",
  "summary": "Model stated construction date of 1920 instead of 1889",
  "root_cause_hypothesis": "Training data contamination or retrieval error",
  "evidence": {
    "signals": ["status_code: 200", "latency_ms: 380"],
    "excerpt": "The Eiffel Tower was built in [REDACTED]..."
  },
  "recommended_actions": ["Add fact-checking layer", "Update training data"],
  "reproduction_context": {
    "input_pattern": "Questions about construction dates",
    "required_state": "No specific state required",
    "tools_involved": ["llm_call", "retrieval"]
  },
  "severity": "high",
  "confidence": 0.85,
  "confidence_rationale": "Clear factual error with sufficient context",
  "extracted_at": "2024-12-23T10:30:45.123456Z"
}
```

**3. Run summaries (`evalforge_extraction_runs`)**:

```bash
# Query recent runs
gcloud firestore query --collection-id=evalforge_extraction_runs \
  --order-by=timestamp DESC \
  --limit=3
```

Expected: One document per extraction run with counts, timings, and model config.

**4. Error records (`evalforge_extraction_errors`)** (if any errors occurred):

```bash
# Query recent errors
gcloud firestore query --collection-id=evalforge_extraction_errors \
  --order-by=timestamp DESC \
  --limit=5
```

Expected: Documents for any traces that failed with error type, raw response excerpt, and trace ID.

### Manual Cloud Run Invocation

After deployment, test the Cloud Run endpoint:

```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe evalforge-extraction \
  --region=us-central1 \
  --format="value(status.url)")

# Trigger extraction (requires authentication)
curl -X POST "${SERVICE_URL}/extraction/run-once" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"batchSize": 5, "triggeredBy": "manual"}'
```

### Scheduled Run Verification

Trigger the Cloud Scheduler job manually:

```bash
# Trigger scheduler job
gcloud scheduler jobs run evalforge-extraction-trigger \
  --location=us-central1

# View logs
gcloud logs tail --service=evalforge-extraction --limit=50
```

Expected log entries:

```
[INFO] Starting extraction run: run_20241223_103045_abc123
[INFO] Picked up 50 unprocessed traces for extraction
[INFO] Extracted pattern for trace abc123: hallucination
[INFO] Stored pattern pattern_abc123_def456 to Firestore
[INFO] Extraction run complete: 50 picked up, 48 stored, 2 errors
```

## Deployment Outline

1. Build and deploy the extraction service to Cloud Run.
2. Configure Cloud Scheduler to call the Cloud Run URL every 30 minutes:

```text
Cron: */30 * * * *
```

3. Confirm the service account has required IAM permissions (see **Access Control** section below).

## Access Control

The extraction service uses **internal-only access** with no public endpoints:

### Cloud Run Configuration

**No unauthenticated access**: The service is deployed with `--no-allow-unauthenticated`:

```bash
gcloud run deploy evalforge-extraction \
  --no-allow-unauthenticated \
  --service-account=evalforge-extraction-sa@PROJECT_ID.iam.gserviceaccount.com
```

**Invoker permission**: Only the service account can invoke the Cloud Run URL:

```bash
gcloud run services add-iam-policy-binding evalforge-extraction \
  --region=us-central1 \
  --member="serviceAccount:evalforge-extraction-sa@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

**Cloud Scheduler authentication**: Uses OIDC to authenticate as the service account:

```bash
gcloud scheduler jobs create http evalforge-extraction-trigger \
  --schedule="*/30 * * * *" \
  --uri="https://evalforge-extraction-HASH-uc.a.run.app/extraction/run-once" \
  --oidc-service-account-email="evalforge-extraction-sa@PROJECT_ID.iam.gserviceaccount.com"
```

### Firestore IAM Permissions

The service account requires:

| Permission | Purpose |
|-----------|---------|
| `roles/datastore.user` | Read/write Firestore documents |

Apply to the service account:

```bash
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:evalforge-extraction-sa@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
```

**Collections accessed**:
- Read + update: `evalforge_raw_traces` (marks `processed=true` after extraction)
- Write: `evalforge_failure_patterns` (stores extracted patterns)
- Write: `evalforge_extraction_runs` (stores run summaries)
- Write: `evalforge_extraction_errors` (stores per-trace errors)

### Vertex AI IAM Permissions

The service account requires:

| Permission | Purpose |
|-----------|---------|
| `roles/aiplatform.user` | Call Gemini API via Vertex AI |

Apply to the service account:

```bash
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:evalforge-extraction-sa@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

**APIs used**:
- `generativelanguage.googleapis.com` (google-genai SDK)
- Gemini model: `gemini-2.5-flash` in `VERTEX_AI_LOCATION`

### Security Notes

- **No public endpoints**: Service only responds to authenticated requests from Cloud Scheduler
- **No user credentials**: Service account credentials managed by Google Cloud
- **Least privilege**: Service account has only required permissions for Firestore and Vertex AI
- **Audit trail**: All requests logged with `run_id` and `source_trace_id` for traceability

## Operational NFRs (constitution-aligned)

- **Latency**: Per-trace processing must complete within 10 seconds (spec AC4 + constitution). Traces that exceed the budget are marked timed out and recorded as errors; the batch continues.
- **Reliability**: Gemini calls retry up to 3 times with exponential backoff; failures never halt the batch.
- **Observability**: Logs include `run_id`, `source_trace_id`, per-trace outcome, and timing.
- **Privacy/PII**: Stored `evidence.excerpt` is redacted and limited to short excerpts; no raw sensitive user data is persisted.
- **Structured Output**: Uses `response_mime_type: "application/json"` with `response_schema` to guarantee valid JSON from Gemini.
