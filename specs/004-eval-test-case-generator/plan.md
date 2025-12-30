# Implementation Plan: Eval Test Case Generator

**Branch**: `004-eval-test-case-generator` | **Date**: 2025-12-29 | **Spec**: `specs/004-eval-test-case-generator/spec.md`
**Input**: Feature specification from `specs/004-eval-test-case-generator/spec.md`

## Summary

Add a generator service that turns **eval-type suggestions** into **framework-agnostic JSON eval test drafts** using Vertex AI Gemini, storing the result on the existing Suggestion document (`suggestion_content.eval_test`). The service runs in scheduled/manual batch mode, selects a canonical source trace/pattern using the **highest-confidence** pattern (tie-breaker: most recent), emits rubric-first pass/fail criteria (with optional golden output when deterministic), and records auditable generation events and run summaries without leaking PII.

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: Google Cloud client libraries (Firestore), Google Gen AI SDK (`google-genai`) for Gemini access, FastAPI (Cloud Run HTTP surface), `tenacity` (retry/backoff), Pydantic (schema validation)  
**Storage**:
- Firestore collection `{FIRESTORE_COLLECTION_PREFIX}suggestions` (read + update `suggestion_content.eval_test`)
- Firestore collection `{FIRESTORE_COLLECTION_PREFIX}failure_patterns` (read canonical source confidence + reproduction context)
- Firestore collections `{FIRESTORE_COLLECTION_PREFIX}eval_test_runs` and `{FIRESTORE_COLLECTION_PREFIX}eval_test_errors` (write run summaries + per-suggestion error records)
**Selection Query**: Default batch selection filters `Suggestion.type == "eval"` (and typically `Suggestion.status == "pending"`) using existing composite indexes from Issue #3 (e.g., `status + type + created_at`).
**Testing**: pytest **live integration tests only** (minimal mode) in `tests/integration/` guarded by `RUN_LIVE_TESTS=1` (real Gemini + real Firestore). **No mocks.**  
**Target Platform**: Google Cloud Run (stateless service, invoked by Cloud Scheduler over HTTPS)  
**Project Type**: Single backend service within existing Python project (`src/generators`)  
**Performance Goals**: 95% of per-suggestion generations complete within 30 seconds; batch run processes up to `EVAL_TEST_BATCH_SIZE` suggestions per invocation without exceeding quotas  
**Cost Budget**: Primary budget is **per suggestion** (average <$0.10). Record token/cost estimates when available; enforce a per-run budget (default: `EVAL_TEST_BATCH_SIZE * EVAL_TEST_COST_BUDGET_USD_PER_SUGGESTION`) and fall back to a template-based `needs_human_input` draft (no Gemini call) when budget is exceeded.  
**Constraints**: Firestore document size limit (keep drafts compact); strict PII redaction/truncation on any stored text; idempotent per suggestion (updates overwrite prior generated draft only under safe rules); retry at least 3 times with exponential backoff on transient Gemini errors; generator MUST NOT modify `Suggestion.status` / `Suggestion.approval_metadata`  
**Scale/Scope**: Hackathon-scale backlog (~100–1000 suggestions). Prefer sequential processing per run to avoid LLM quota spikes; batch size and token caps are tunable.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Observability-First Insight Trail**: Emit `run_id`, `suggestion_id`, `canonical_trace_id`, `canonical_pattern_id`, and `prompt_hash` in structured logs; persist run summaries and per-suggestion errors keyed by `run_id` for traceability.
- **Human-Governed Fail-Safe Loops**: Generation creates drafts only; **approval remains human-controlled** (suggestion status is the gate for “approved for CI”). Regeneration does not silently overwrite human edits (requires explicit `forceOverwrite`).
- **Cost-Conscious Experimentation**: Cap `max_output_tokens`, keep drafts compact, bound batch size, track per-suggestion token/cost estimates when available, and enforce a per-run budget (default derived from batch size and per-suggestion budget). When budget would be exceeded, fall back to a deterministic template draft (`needs_human_input`) rather than making additional Gemini calls.
- **Reliability & Cognitive Ease**: Retry Gemini calls (3 attempts) with exponential backoff, isolate failures per suggestion, and provide actionable error messages for retry.
- **Demo-Ready Transparency & UX**: Drafts include plain-language rationale and lineage (all source traces), plus a canonical source to explain why the test exists.
- **Platform & Compliance Constraints**: Cloud Run only; Vertex AI/Gemini only; strip/redact PII before persistence; use Secret Manager/ADC for credentials; HTTPS only.
- **Workflow & Quality Gates**: Minimal mode uses **live** integration tests only (`RUN_LIVE_TESTS=1`) to validate real Gemini + Firestore behavior.

**Gate Result**: PASSED - No violations.

## Project Structure

### Documentation (this feature)

```text
specs/004-eval-test-case-generator/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── eval-generator-openapi.yaml
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
src/
├── generators/
│   ├── export_bridge.py
│   └── eval_tests/
│       ├── __init__.py
│       ├── main.py                 # FastAPI service (/health, /eval-tests/*)
│       ├── models.py               # EvalTestDraft + run/error models (Pydantic)
│       ├── prompt_templates.py     # Prompt builder for Gemini generation
│       ├── gemini_client.py        # Thin wrapper around google-genai w/ response_schema
│       ├── firestore_repository.py # Suggestion + pattern reads; eval_test + run/error writes
│       └── eval_test_service.py    # Core batch orchestration and overwrite rules
└── common/
    ├── config.py
    ├── firestore.py
    ├── pii.py
    └── logging.py

tests/
└── integration/
    └── test_eval_test_generator_live.py  # Live Gemini + Firestore smoke tests (RUN_LIVE_TESTS=1)
```

**Structure Decision**: Implement a new generator service under `src/generators/eval_tests/` to keep artifact generation decoupled from ingestion/extraction/deduplication while reusing shared config/logging/PII helpers.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| - | - | - |

## Deferred Decisions

| Decision | Reason Deferred | Impact if Deferred |
|----------|-----------------|-------------------|
| Exporting eval tests to a repo/CI harness | Out of scope for this feature | Downstream wiring can be added after schema stabilizes |
| Full reviewer editing UI | Hackathon scope favors minimal surface | Manual editing can happen via Firestore/admin tooling for demo |
