# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Evalforge (Incident-to-Insight Loop) transforms LLM production failures from Datadog into actionable outputs: eval test cases, guardrail rules, and runbook entries. It fetches LLM traces from Datadog, extracts failure patterns, and stores them in Firestore for downstream processing.

## Build & Development Commands

```bash
# Environment setup
python -m venv evalforge_venv && source evalforge_venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # Then fill in Datadog + GCP credentials

# Run services
python -m src.ingestion.main    # Ingestion service (FastAPI) - fetches from Datadog, stores to Firestore
python -m src.api.main          # Capture Queue API (FastAPI) - exposes failure queue and export endpoints
docker-compose up               # Full stack with Firestore emulator

# Generate synthetic test traces
python3 scripts/generate_llm_trace_samples.py --count 5
```

## Testing

```bash
# Unit tests (no credentials needed - uses mocks)
PYTHONPATH=src python -m pytest tests/unit -v

# Contract tests (verify data shapes)
PYTHONPATH=src python -m pytest tests/contract -v

# Integration tests against live services (requires credentials in .env)
RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration -v

# Single test
PYTHONPATH=src python -m pytest tests/unit/test_datadog_client.py::test_fetch_recent_failures_handles_rate_limit -v
```

Tests use `responses` library to mock HTTP calls and `monkeypatch` for environment variables.

## Architecture

### Data Flow
1. **Ingestion** (`src/ingestion/`): Polls Datadog LLM Observability Export API for error spans
2. **Sanitization** (`pii_sanitizer.py`): Strips PII fields, hashes user IDs, redacts prompts/outputs
3. **Storage**: Writes `FailureCapture` documents to Firestore `{prefix}raw_traces` collection
4. **API** (`src/api/`): Exposes `/capture-queue` for browsing and `/exports` for downstream systems

### Key Domain Models (`src/ingestion/models.py`)
- `FailureCapture`: Core entity storing sanitized trace with failure classification, severity, recurrence tracking, and export status
- `ExportPackage`: Represents an exported failure sent to downstream systems

### Configuration (`src/common/config.py`)
All settings loaded from environment variables via `load_settings()`. Key configs:
- `DATADOG_API_KEY`, `DATADOG_APP_KEY`, `DATADOG_SITE` - Datadog credentials
- `TRACE_LOOKBACK_HOURS`, `QUALITY_THRESHOLD` - Ingestion tuning
- `FIRESTORE_COLLECTION_PREFIX`, `GOOGLE_CLOUD_PROJECT` - Storage config
- `PII_SALT` - For hashing user identifiers

### Failure Classification (`datadog_client.py:_derive_failure_type_and_severity`)
Classifies spans by priority: guardrail_failure > prompt_injection > toxicity > hallucination > infrastructure_error > client_error > quality_degradation > llm_error

## Coding Conventions

- Type hints everywhere; avoid type definitions `from __future__ import annotations`
- Dataclasses for domain models with `to_dict()` for Firestore serialization
- Structured logging via `src/common/logging` with `log_error()`, `log_decision()`, `log_audit()`
- Retry with tenacity for external API calls; specific exception types (`RateLimitError`, `CredentialError`)
- FastAPI routers in `api/` expose REST endpoints; ingestion service also uses FastAPI for `/health` and `/ingestion/run-once`

## Firestore Collections

Documents keyed by `trace_id` in `{FIRESTORE_COLLECTION_PREFIX}raw_traces`:
- Deduplication: re-observed traces increment `recurrence_count` and append to `status_history`
- Pagination uses `start_after(DocumentSnapshot)` pattern, returning document ID as cursor
