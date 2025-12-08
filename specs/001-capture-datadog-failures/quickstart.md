# Quickstart: Automatic Capture of Datadog Failures

This guide explains how to run the Datadog ingestion service that captures LLM failures into Firestore for downstream evals, guardrails, and runbooks.

## Prerequisites

- Python 3.11
- Access to Datadog with LLM Observability enabled
- Google Cloud project with:
  - Cloud Run
  - Firestore
  - Secret Manager
  - Cloud Scheduler

## Environment Configuration

1. Create the following secrets in Google Secret Manager:
   - `datadog-api-key`
   - `datadog-app-key`

2. Set environment variables for the ingestion service:

```bash
DATADOG_API_KEY=projects/PROJECT_ID/secrets/datadog-api-key/versions/latest
DATADOG_APP_KEY=projects/PROJECT_ID/secrets/datadog-app-key/versions/latest
DATADOG_SITE=datadoghq.com
TRACE_LOOKBACK_HOURS=24
QUALITY_THRESHOLD=0.5
FIRESTORE_COLLECTION_PREFIX=evalforge_
INGESTION_LATENCY_MINUTES=5  # scheduler cadence
# Optional: tune backoff if Datadog rate limits are aggressive
DATADOG_RATE_LIMIT_MAX_SLEEP=10
```

## Local Development Flow

1. Create/activate the shared venv and install deps:

```bash
python -m venv evalforge_venv
source evalforge_venv/bin/activate
pip install -e ".[dev]"
```

2. Run the ingestion service API locally (FastAPI):

```bash
evalforge_venv/bin/uvicorn src.ingestion.main:app --reload --port 8000
```

3. Trigger a one-off ingestion run using the configured scheduler or a manual HTTP call to the `/ingestion/run-once` endpoint.

```bash
curl -X POST "http://localhost:8000/ingestion/run-once" \
  -H "Content-Type: application/json" \
  -d '{"traceLookbackHours":12,"qualityThreshold":0.4}'
```

4. Run the capture queue + export API locally:

```bash
evalforge_venv/bin/uvicorn src.api.main:app --reload --port 8001
```

Example calls:

- Queue: `curl "http://localhost:8001/capture-queue?severity=high&agent=llm-agent&pageSize=25"`
- Export: `curl -X POST "http://localhost:8001/exports" -H "Content-Type: application/json" -d '{"failureId":"trace-123","destination":"eval_backlog"}'`

### Operational NFRs (constitution-aligned)

- **Latency SLO**: ingestion completes within `INGESTION_LATENCY_MINUTES` (default 5) for the configured lookback window.
- **Observability**: `/health` reports last sync, backlog size, rate-limit state, and empty/backfill coverage hints; structured logs emit `datadog_query*`, `ingestion_metrics`, and errors.
- **Privacy/PII**: prompts/responses redacted; `user.id` is hashed to `user_hash`; secrets must come from Secret Manager.
- **Cost bounds**: Datadog queries use small page sizes (100) with bounded retries/backoff (1–10s) on 429s; prefer narrow filters (service/quality threshold) when possible.

## Deployment Outline

1. Build and deploy the ingestion service to Cloud Run.
2. Configure Cloud Scheduler to call the Cloud Run URL every 5 minutes (override via `INGESTION_LATENCY_MINUTES`):

```text
Cron: */5 * * * *
```

3. Verify failures are written to the Firestore collection `evalforge_raw_traces` with PII stripped and `user_hash` populated.
