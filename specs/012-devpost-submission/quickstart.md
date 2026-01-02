# Quickstart: Local Demo Checklist (for README + Devpost)

**Branch**: `012-devpost-submission` | **Date**: 2025-12-30

This quickstart is optimized for a hackathon demo: bring the stack up, verify health, and trigger the “incident → insight” loop endpoints where credentials are available.

## Prerequisites

- Python 3.11
- Docker + Docker Compose
- Optional (for full end-to-end demo):
  - Datadog API + App keys for ingestion
  - Google Cloud credentials for Vertex AI/Gemini + embeddings

## Local Stack (recommended)

From repo root:

```bash
cp .env.example .env
# Edit .env with Datadog keys (optional) and any overrides you need

docker-compose up --build
```

### Expected local ports

- API: `http://localhost:8000`
- Ingestion: `http://localhost:8001`
- Extraction: `http://localhost:8002`
- Deduplication: `http://localhost:8003`
- Eval test generator: `http://localhost:8004`
- Firestore emulator: `http://localhost:8086`

### Health checks

```bash
curl -s http://localhost:8000/health | jq .
curl -s http://localhost:8000/approval/health | jq .
curl -s http://localhost:8001/health | jq .
curl -s http://localhost:8002/health | jq .
curl -s http://localhost:8003/health | jq .
curl -s http://localhost:8004/health | jq .
```

Notes:
- If Vertex AI credentials are missing, extraction/dedup/generators may report degraded dependency status but can still serve `/health`.
- If Datadog credentials are missing/invalid, `/ingestion/run-once` will fail (expected).

## Demo Flow (with credentials)

1) Ingest recent failures from Datadog into Firestore:

```bash
curl -X POST http://localhost:8001/ingestion/run-once \
  -H "Content-Type: application/json" \
  -d '{"traceLookbackHours": 24, "qualityThreshold": 0.3}'
```

2) Extract failure patterns (Gemini):

```bash
curl -X POST http://localhost:8002/extraction/run-once \
  -H "Content-Type: application/json" \
  -d '{"batchSize": 50, "triggeredBy": "manual"}'
```

3) Deduplicate patterns into suggestions (embeddings):

```bash
curl -X POST http://localhost:8003/dedup/run-once \
  -H "Content-Type: application/json" \
  -d '{"batchSize": 20, "triggeredBy": "manual"}'
```

4) Generate eval test drafts for `eval` suggestions:

```bash
curl -X POST http://localhost:8004/eval-tests/run-once \
  -H "Content-Type: application/json" \
  -d '{"batchSize": 20, "triggeredBy": "manual"}'
```

5) Review and approve via Approval API (requires API key header):

- Contract: `specs/008-approval-workflow-api/contracts/approval-api-openapi.yaml`
- Base path: `/approval`

Example list call:

```bash
curl -s "http://localhost:8000/approval/suggestions?status=pending&limit=10" \
  -H "X-API-Key: $APPROVAL_API_KEY" | jq .
```

## Demo Flow (no Datadog credentials)

If you only need something visual for screenshots (dashboard/backlog), you can seed test suggestions into the Firestore emulator:

```bash
export FIRESTORE_EMULATOR_HOST="localhost:8086"
export GOOGLE_CLOUD_PROJECT="local-demo"
python3 scripts/create_test_suggestions.py
```

This does not demonstrate ingestion/extraction/deduplication, but it can produce realistic “pending suggestions” for screenshots.

## API Reference

OpenAPI contracts (source-of-truth):

- Ingestion: `specs/001-capture-datadog-failures/contracts/ingestion-openapi.yaml`
- Extraction: `specs/002-extract-failure-patterns/contracts/extraction-openapi.yaml`
- Deduplication: `specs/003-suggestion-deduplication/contracts/deduplication-openapi.yaml`
- Eval generator: `specs/004-eval-test-case-generator/contracts/eval-generator-openapi.yaml`
- Approval: `specs/008-approval-workflow-api/contracts/approval-api-openapi.yaml`
