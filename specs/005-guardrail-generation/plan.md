# Implementation Plan: Guardrail Suggestion Engine

**Branch**: `005-guardrail-generation` | **Date**: 2025-12-30 | **Spec**: `specs/005-guardrail-generation/spec.md`
**Input**: Feature specification from `specs/005-guardrail-generation/spec.md`

## Summary

Add a generator service that turns **guardrail-type suggestions** into **structured JSON guardrail rule drafts** using Vertex AI Gemini, storing the result on the existing Suggestion document (`suggestion_content.guardrail`). The service runs in scheduled/manual batch mode, maps failure types to guardrail types using a deterministic mapping (hallucination→validation_rule, runaway_loop→rate_limit, etc.), selects a canonical source trace/pattern using the **highest-confidence** pattern (tie-breaker: most recent), and generates actionable guardrail configurations with concrete thresholds and justifications. Records auditable generation events and run summaries without leaking PII.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: Google Cloud client libraries (Firestore), Google Gen AI SDK (`google-genai`) for Gemini access, FastAPI (Cloud Run HTTP surface), `tenacity` (retry/backoff), Pydantic (schema validation), PyYAML (YAML export)
**Storage**:
- Firestore collection `{FIRESTORE_COLLECTION_PREFIX}suggestions` (read + update `suggestion_content.guardrail`)
- Firestore collection `{FIRESTORE_COLLECTION_PREFIX}failure_patterns` (read canonical source confidence + reproduction context)
- Firestore collections `{FIRESTORE_COLLECTION_PREFIX}guardrail_runs` and `{FIRESTORE_COLLECTION_PREFIX}guardrail_errors` (write run summaries + per-suggestion error records)
**Selection Query**: Default batch selection filters `Suggestion.type == "guardrail"` (and typically `Suggestion.status == "pending"`) using existing composite indexes from Issue #3 (e.g., `status + type + created_at`).
**Testing**: pytest **live integration tests only** (minimal mode) in `tests/integration/` guarded by `RUN_LIVE_TESTS=1` (real Gemini + real Firestore). **No mocks.**
**Target Platform**: Google Cloud Run (stateless service, invoked by Cloud Scheduler over HTTPS)
**Project Type**: Single backend service within existing Python project (`src/generators`)
**Performance Goals**: 95% of per-suggestion generations complete within 30 seconds; batch run processes up to `GUARDRAIL_BATCH_SIZE` suggestions per invocation without exceeding quotas
**Cost Budget**: Primary budget is **per suggestion** (average <$0.10). Record token/cost estimates when available; enforce a per-run budget (default: `GUARDRAIL_BATCH_SIZE * GUARDRAIL_COST_BUDGET_USD_PER_SUGGESTION`) and fall back to a template-based `needs_human_input` draft (no Gemini call) when budget is exceeded.
**Constraints**: Firestore document size limit (keep drafts compact); strict PII redaction/truncation on any stored text; idempotent per suggestion (updates overwrite prior generated draft only under safe rules); retry at least 3 times with exponential backoff on transient Gemini errors; generator MUST NOT modify `Suggestion.status` / `Suggestion.approval_metadata`
**Scale/Scope**: Hackathon-scale backlog (~100–1000 suggestions). Prefer sequential processing per run to avoid LLM quota spikes; batch size and token caps are tunable.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Observability-First Insight Trail**: Emit `run_id`, `suggestion_id`, `canonical_trace_id`, `canonical_pattern_id`, `failure_type`, `guardrail_type`, and `prompt_hash` in structured logs; persist run summaries and per-suggestion errors keyed by `run_id` for traceability.
- **Human-Governed Fail-Safe Loops**: Generation creates drafts only; **approval remains human-controlled** (suggestion status is the gate for "approved for deployment"). Regeneration does not silently overwrite human edits (requires explicit `forceOverwrite`).
- **Cost-Conscious Experimentation**: Cap `max_output_tokens`, keep drafts compact, bound batch size, track per-suggestion token/cost estimates when available, and enforce a per-run budget (default derived from batch size and per-suggestion budget). When budget would be exceeded, fall back to a deterministic template draft (`needs_human_input`) rather than making additional Gemini calls.
- **Reliability & Cognitive Ease**: Retry Gemini calls (3 attempts) with exponential backoff, isolate failures per suggestion, and provide actionable error messages for retry. Guardrails include plain-language justification explaining what they block and why.
- **Demo-Ready Transparency & UX**: Drafts include plain-language justification, concrete configuration values (thresholds, limits), and lineage (all source traces), plus a canonical source to explain why the guardrail exists.
- **Platform & Compliance Constraints**: Cloud Run only; Vertex AI/Gemini only; strip/redact PII before persistence; use Secret Manager/ADC for credentials; HTTPS only.
- **Workflow & Quality Gates**: Minimal mode uses **live** integration tests only (`RUN_LIVE_TESTS=1`) to validate real Gemini + Firestore behavior.

**Gate Result**: PASSED - No violations.

## Project Structure

### Documentation (this feature)

```text
specs/005-guardrail-generation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── guardrail-generator-openapi.yaml
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
src/
├── generators/
│   ├── export_bridge.py
│   ├── eval_tests/              # Existing (004) - reference implementation
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── prompt_templates.py
│   │   ├── gemini_client.py
│   │   ├── firestore_repository.py
│   │   └── eval_test_service.py
│   └── guardrails/              # NEW (005) - copy & adapt from eval_tests
│       ├── __init__.py
│       ├── main.py                  # FastAPI service (/health, /guardrails/*)
│       ├── models.py                # GuardrailDraft + run/error models (Pydantic)
│       ├── prompt_templates.py      # Guardrail-specific prompt builder
│       ├── guardrail_types.py       # GUARDRAIL_MAPPING dict
│       ├── gemini_client.py         # Thin wrapper with guardrail response_schema
│       ├── firestore_repository.py  # Suggestion + pattern reads; guardrail + run/error writes
│       ├── guardrail_service.py     # Core batch orchestration with failure-type mapping
│       └── yaml_export.py           # Datadog AI Guard YAML export utility (US3)
└── common/
    ├── config.py
    ├── firestore.py
    ├── pii.py
    └── logging.py

tests/
└── integration/
    └── test_guardrail_generator_live.py  # Live Gemini + Firestore smoke tests (RUN_LIVE_TESTS=1)
```

**Structure Decision**: Implement a new generator service under `src/generators/guardrails/` following the exact structure of `src/generators/eval_tests/` to maintain consistency and enable code reuse while keeping guardrail-specific logic separate.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| - | - | - |

## Deferred Decisions

| Decision | Reason Deferred | Impact if Deferred |
|----------|-----------------|-------------------|
| Deploying guardrails to Datadog AI Guard | Out of scope for this feature | Downstream integration can be added after schema stabilizes |
| Guardrail conflict detection | Out of scope for hackathon | Rules are assumed independent; conflicts detected manually during review |
| Full reviewer editing UI | Hackathon scope favors minimal surface | Manual editing can happen via Firestore/admin tooling for demo |

## Code Reuse Strategy

### Directly Reusable (No Changes)

| Module | Path | Usage |
|--------|------|-------|
| GeminiConfig | `src/common/config.py` | Configuration for Gemini calls |
| FirestoreConfig | `src/common/config.py` | Firestore connection settings |
| PII utilities | `src/common/pii.py` | `redact_and_truncate()` for sanitization |
| Firestore helpers | `src/common/firestore.py` | Collection name functions, client factory |
| Logging | `src/common/logging.py` | Structured logging utilities |

### Reusable with Minor Adaptation (Copy & Modify)

| Source Module | Guardrail Version | Changes Required |
|---------------|-------------------|------------------|
| `eval_tests/models.py` | `guardrails/models.py` | Replace EvalTestDraft with GuardrailDraft; keep TriggeredBy, EditSource, error types, RunSummary pattern |
| `eval_tests/gemini_client.py` | `guardrails/gemini_client.py` | Change response_schema to guardrail schema; same retry/hashing logic |
| `eval_tests/firestore_repository.py` | `guardrails/firestore_repository.py` | Query `type=="guardrail"`; write to `suggestion_content.guardrail`; collections: `guardrail_runs`, `guardrail_errors` |
| `eval_tests/eval_test_service.py` | `guardrails/guardrail_service.py` | Use guardrail prompt template; add failure-type-to-guardrail-type mapping; same orchestration logic |
| `eval_tests/main.py` | `guardrails/main.py` | Change endpoint prefix to `/guardrails`; identical FastAPI structure |

### Guardrail-Specific (New Code)

| Module | Purpose |
|--------|---------|
| `guardrails/prompt_templates.py` | Guardrail-specific prompt with failure type mapping and JSON output templates |
| `guardrails/guardrail_types.py` | `GUARDRAIL_MAPPING` dict for failure_type → guardrail_type conversion |
| `guardrails/yaml_export.py` | Datadog AI Guard compatible YAML export utility for deployment tooling |

## Failure Type to Guardrail Type Mapping

| Failure Type | Guardrail Type | Description | Example Configuration |
|--------------|----------------|-------------|----------------------|
| hallucination | validation_rule | Check facts against knowledge base | `{"check_type": "pre_response", "condition": "verify_against_kb"}` |
| toxicity | content_filter | Block offensive outputs | `{"filter_type": "output", "threshold": 0.7, "action": "block"}` |
| runaway_loop | rate_limit | Max N calls per session | `{"max_calls": 10, "window_seconds": 60, "action": "block_and_alert"}` |
| pii_leak | redaction_rule | Strip sensitive patterns | `{"patterns": ["email", "phone", "ssn"], "action": "redact"}` |
| wrong_tool | scope_limit | Restrict tool availability | `{"allowed_tools": ["safe_tool"], "action": "block"}` |
| stale_data | freshness_check | Verify data recency | `{"max_age_hours": 24, "action": "warn"}` |
| prompt_injection | input_sanitization | Block malicious prompts | `{"patterns": ["ignore previous"], "action": "block"}` |
