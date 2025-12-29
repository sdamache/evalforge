# Quickstart: Eval Test Case Generator

**Branch**: `004-eval-test-case-generator` | **Date**: 2025-12-29

This guide explains how to run the eval test generator service that turns eval-type suggestions into framework-agnostic JSON eval test drafts.

## Prerequisites

- Python 3.11+
- GCP project with Vertex AI API enabled (Gemini)
- Firestore (emulator or real project)
- Existing suggestions in Firestore `{FIRESTORE_COLLECTION_PREFIX}suggestions` (from Issue #3)

## Environment Configuration

```bash
# Firestore
FIRESTORE_COLLECTION_PREFIX=evalforge_
FIRESTORE_DATABASE_ID=(default)
GOOGLE_CLOUD_PROJECT=your-gcp-project

# Vertex AI / Gemini (google-genai SDK)
VERTEX_AI_LOCATION=us-central1
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TEMPERATURE=0.2
GEMINI_MAX_OUTPUT_TOKENS=2048

# Generator tuning
EVAL_TEST_BATCH_SIZE=20
EVAL_TEST_PER_SUGGESTION_TIMEOUT_SEC=30
EVAL_TEST_COST_BUDGET_USD_PER_SUGGESTION=0.10
# Optional: overrides derived per-run budget (batch_size * per-suggestion budget)
EVAL_TEST_RUN_COST_BUDGET_USD=2.00
```

## Local Development Flow

1. Create/activate the venv and install deps:

```bash
python -m venv evalforge_venv
source evalforge_venv/bin/activate
pip install -e ".[dev]"
```

2. Run the generator service locally (FastAPI):

```bash
evalforge_venv/bin/uvicorn src.generators.eval_tests.main:app --reload --port 8004
```

3. Trigger a batch generation run:

```bash
curl -X POST "http://localhost:8004/eval-tests/run-once" \
  -H "Content-Type: application/json" \
  -d '{"batchSize":20,"triggeredBy":"manual"}'
```

4. Generate a single suggestion (regenerate) with overwrite control:

```bash
curl -X POST "http://localhost:8004/eval-tests/generate/sugg_abc123" \
  -H "Content-Type: application/json" \
  -d '{"forceOverwrite": false, "triggeredBy":"manual"}'
```

5. Fetch the current draft:

```bash
curl "http://localhost:8004/eval-tests/sugg_abc123"
```

This endpoint returns the eval test draft plus suggestion approval metadata (`suggestion_status` and optional `approval_metadata.timestamp`) so downstream tooling can gate usage.

## Storage Effects

- Suggestion updated at: `{FIRESTORE_COLLECTION_PREFIX}suggestions/{suggestion_id}`
  - Field: `suggestion_content.eval_test` (framework-agnostic JSON)
- Run summaries written to: `{FIRESTORE_COLLECTION_PREFIX}eval_test_runs`
- Error records written to: `{FIRESTORE_COLLECTION_PREFIX}eval_test_errors`

## Testing (minimal mode: live only)

Run live integration tests (requires real Gemini + Firestore):

```bash
RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_eval_test_generator_live.py -v
```

> These tests must make real Gemini calls; they are skipped unless `RUN_LIVE_TESTS=1` is set.

## Operational NFRs (constitution-aligned)

- **Latency**: 95% of generations complete within 30 seconds per suggestion; timeouts are recorded and do not block other suggestions.
- **Reliability**: Gemini calls retry with exponential backoff (3 attempts); failures are isolated per suggestion.
- **Observability**: Logs include `run_id`, `suggestion_id`, canonical source IDs, and prompt/response hashes.
- **Privacy/PII**: Any stored text is redacted + truncated; no raw user PII is persisted.
