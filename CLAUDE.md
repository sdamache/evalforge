# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Evalforge (Incident-to-Insight Loop) transforms LLM production failures from Datadog into actionable outputs: eval test cases, guardrail rules, and runbook entries. It fetches LLM traces from Datadog, extracts failure patterns, and stores them in Firestore for downstream processing.

## GCP Configuration

**Project ID**: `konveyn2ai`
**Region**: `us-central1` (default)

```bash
# For infrastructure automation scripts
export GCP_PROJECT_ID="konveyn2ai"
```

## Build & Development Commands

```bash
# Environment setup
python -m venv evalforge_venv && source evalforge_venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # Then fill in Datadog + GCP credentials

# Run services
python -m src.ingestion.main              # Ingestion service (FastAPI) - fetches from Datadog, stores to Firestore
python -m src.api.main                    # Capture Queue API (FastAPI) - exposes failure queue and export endpoints
python -m src.generators.runbooks.main    # Runbook Generator (FastAPI) - generates SRE runbooks from suggestions
python -m src.generators.guardrails.main  # Guardrail generator service (FastAPI) - generates guardrail drafts
docker-compose up                         # Full stack with Firestore emulator

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
5. **Dashboard** (`src/dashboard/`): Publishes metrics to Datadog for visualization in App Builder dashboard
6. **Runbook Generator** (`src/generators/runbooks/`): Transforms runbook-type suggestions into SRE runbooks

### Runbook Generator (`src/generators/runbooks/`)
Generates operational SRE runbooks from failure patterns with 6 sections: Summary, Symptoms, Diagnosis, Mitigation, Root Cause Fix, Escalation.

**Endpoints:**
- `POST /runbooks/run-once` - Batch generation for pending runbook suggestions
- `POST /runbooks/generate/{suggestionId}` - Single suggestion generation
- `GET /runbooks/{suggestionId}` - Retrieve runbook with approval metadata
- `GET /health` - Health check with backlog count

**Key models** (`src/generators/runbooks/models.py`):
- `RunbookDraft`: Core runbook with markdown_content, symptoms[], diagnosis_commands[], mitigation_steps[], escalation_criteria
- `RunbookDraftSource`: Lineage tracking (suggestion_id, trace_ids, pattern_ids)
- `RunbookDraftGeneratorMeta`: Generation metadata (model, prompt_hash, response_sha256)

**Safety features:**
- Human edit protection (`edit_source: human` blocks overwrite unless `forceOverwrite=true`)
- Template fallback with `status: needs_human_input` when context is missing
- Cost budgeting ($0.10/suggestion default)

### Key Domain Models (`src/ingestion/models.py`)
- `FailureCapture`: Core entity storing sanitized trace with failure classification, severity, recurrence tracking, and export status
- `ExportPackage`: Represents an exported failure sent to downstream systems

### Dashboard Module (`src/dashboard/`)
- `metrics_publisher.py`: Cloud Function entry point for publishing metrics to Datadog
- `datadog_client.py`: Datadog API client wrapper for metrics submission
- `aggregator.py`: Firestore aggregation queries for suggestion counts
- `models.py`: MetricPayload, MetricSeries, SuggestionCounts dataclasses
- `config.py`: Dashboard-specific configuration (DashboardConfig)

### Guardrail Generator (`src/generators/guardrails/`)
Generates guardrail rule drafts from guardrail-type suggestions using Gemini:
- **main.py**: FastAPI service with endpoints: `/health`, `/guardrails/run-once`, `/guardrails/generate/{id}`, `/guardrails/{id}`
- **guardrail_service.py**: Orchestration with batch/single generation, template fallback, overwrite protection
- **guardrail_types.py**: Deterministic failure_type → guardrail_type mapping (7 types)
- **gemini_client.py**: Vertex AI Gemini integration with structured JSON output
- **yaml_export.py**: Datadog AI Guard compatible YAML export

Key concepts:
- **Failure Type Mapping**: hallucination→validation_rule, runaway_loop→rate_limit, pii_leak→redaction_rule
- **Template Fallback**: `needs_human_input` status when Gemini unavailable or context insufficient
- **Overwrite Protection**: edit_source flag (generated vs human) prevents overwriting human edits

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

**Runbook Generator Collections:**
- `{prefix}suggestions` - Suggestions with embedded runbooks at `suggestion_content.runbook_snippet`
- `{prefix}runbook_runs` - Batch run summaries for observability
- `{prefix}runbook_errors` - Per-suggestion error records for diagnostics

## Active Technologies
- Firestore `evalforge_suggestions` collection (read-only for this feature) (007-datadog-dashboard)
- Python 3.11 + Google Cloud client libraries (Firestore), Google Gen AI SDK (`google-genai`) for Gemini access, FastAPI (Cloud Run HTTP surface), `tenacity` (retry/backoff), Pydantic (schema validation), PyYAML (YAML export) (005-guardrail-generation)

**Core Stack** (shared across features):
- Python 3.11, FastAPI, google-cloud-firestore, pydantic, tenacity

**Feature-specific additions**:
- 003-suggestion-deduplication: google-cloud-aiplatform, numpy
- 006-runbook-generation: google-genai (Vertex AI Gemini for runbook generation)
- 007-datadog-dashboard: datadog-api-client, functions-framework
- 008-approval-workflow-api: requests (Slack webhooks), PyYAML (export)

**Firestore Collections**:
- `evalforge_failure_patterns` (input) → `evalforge_suggestions` (output)

## Recent Changes
- 005-guardrail-generation: Added guardrail generator service (src/generators/guardrails/) with Gemini-powered guardrail draft generation, YAML export for Datadog AI Guard
- 007-datadog-dashboard: Added Datadog dashboard integration with metrics publisher Cloud Function
- 006-runbook-generation: Added SRE runbook generator with Vertex AI Gemini 2.5 Flash
- 008-approval-workflow-api: Added requests (Slack webhooks), PyYAML (export formats)
- 003-suggestion-deduplication: Added google-cloud-aiplatform, numpy

## Dashboard Module Commands

```bash
# Deploy metrics publisher to Cloud Functions
GCP_PROJECT_ID=konveyn2ai ./scripts/deploy_metrics_publisher.sh

# Run dashboard integration tests (requires DATADOG_API_KEY in .env.local)
RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_metrics_publisher_live.py -v

# Run approval action tests (requires APPROVAL_API_URL in .env.local)
RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_approval_action_live.py -v

# Run smoke tests (requires both Datadog and Approval API credentials)
RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/smoke/test_dashboard_smoke.py -v
```

### Datadog Metrics Published
- `evalforge.suggestions.pending` - Count of pending suggestions
- `evalforge.suggestions.approved` - Count of approved suggestions
- `evalforge.suggestions.rejected` - Count of rejected suggestions
- `evalforge.suggestions.total` - Total suggestion count
- `evalforge.suggestions.by_type` - Count by type (tagged: type:eval|guardrail|runbook)
- `evalforge.suggestions.by_severity` - Count by severity (tagged: severity:low|medium|high|critical)
- `evalforge.coverage.improvement` - Coverage improvement percentage
