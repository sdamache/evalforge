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
GEMINI_MAX_OUTPUT_TOKENS=4096              # Sufficient for detailed pattern extraction

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

## Deployment Outline

1. Build and deploy the extraction service to Cloud Run.
2. Configure Cloud Scheduler to call the Cloud Run URL every 30 minutes:

```text
Cron: */30 * * * *
```

3. Confirm the service account has:

- Permission to read/update Firestore `evalforge_raw_traces`
- Permission to write Firestore `evalforge_failure_patterns`
- Permission to call Vertex AI Gemini in `VERTEX_AI_LOCATION`

## Operational NFRs (constitution-aligned)

- **Latency**: Per-trace processing targets ≤10 seconds for ≥95% of traces (spec AC4). Internally, a 15-second timeout budget is used to accommodate Gemini latency variance while still meeting the target.
- **Reliability**: Gemini calls retry up to 3 times with exponential backoff; failures never halt the batch.
- **Observability**: Logs include `run_id`, `source_trace_id`, per-trace outcome, and timing.
- **Privacy/PII**: Stored `evidence.excerpt` is redacted and limited to short excerpts; no raw sensitive user data is persisted.
- **Structured Output**: Uses `response_mime_type: "application/json"` with `response_schema` to guarantee valid JSON from Gemini.
