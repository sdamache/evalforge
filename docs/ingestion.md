# Ingestion Flow

## Purpose
Automatically pull Datadog LLM Observability failures into Firestore as normalized `FailureCapture` records with PII stripped and trace linkage preserved.

## Configuration
- `DATADOG_API_KEY` / `DATADOG_APP_KEY`: Secret Manager refs for Datadog auth.
- `DATADOG_SITE`: Datadog site (e.g., `datadoghq.com`).
- `TRACE_LOOKBACK_HOURS`: Lookback window for each run (default 24).
- `QUALITY_THRESHOLD`: Minimum `llm_obs.quality_score` before marking as failure.
- `FIRESTORE_COLLECTION_PREFIX`: Prefix for Firestore collections (e.g., `evalforge_`).
- `PII_SALT`: Salt for hashing user identifiers.

## Signals Considered
- HTTP failures: `http.status_code` >= 400.
- Quality degradation: `llm_obs.quality_score < QUALITY_THRESHOLD`.
- Evaluation flags: `llm_obs.evaluations.hallucination`, `prompt_injection`, `toxicity_score >= 0.7`.
- Guardrails: `llm_obs.guardrails.failed=true`.

## Sanitization
- Strips PII fields: `user.email/name/phone/address/ip`, `client.ip`, `session_id`, auth/cookie headers, `pii:*` and `user.*` tags (except `user.id`).
- Hashes `user.id` to `user_hash` using `PII_SALT`.
- Redacts free-text prompts/responses (`input`, `output`, `prompt`, `response`) unless explicitly whitelisted.

## Orchestration
1. `/ingestion/run-once` (FastAPI) resolves effective `lookback`/`quality_threshold` from request or env.
2. `datadog_client.fetch_recent_failures` queries spans with failure filters, retry/backoff (tenacity), and structured logs.
3. Deduplicate by `trace_id`, sanitize payload, compute `user_hash`.
4. Persist `FailureCapture` to Firestore collection `{FIRESTORE_COLLECTION_PREFIX}raw_traces`.
5. Decision and error logs include `trace_id`, actions, outcomes.

## Running Locally
```bash
export DATADOG_API_KEY=projects/PROJECT/secrets/datadog-api-key/versions/latest
export DATADOG_APP_KEY=projects/PROJECT/secrets/datadog-app-key/versions/latest
export FIRESTORE_COLLECTION_PREFIX=evalforge_
evalforge_venv/bin/python -m src.ingestion.main
# Trigger once
curl -X POST http://localhost:8000/ingestion/run-once
```

## Health
- `/health` validates config, instantiates Datadog + Firestore clients, returns `{"status":"ok"}` or 500.

## Collections
- Raw captures: `{FIRESTORE_COLLECTION_PREFIX}raw_traces`
- Exports: `{FIRESTORE_COLLECTION_PREFIX}exports`
