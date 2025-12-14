# Implementation Plan: Failure Pattern Extraction

**Branch**: `002-extract-failure-patterns` | **Date**: 2025-12-14 | **Spec**: `evalforge/specs/002-extract-failure-patterns/spec.md`
**Input**: Feature specification describing batch extraction of structured failure patterns from production traces.

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

This feature adds a Cloud Scheduler-triggered extraction service that reads unprocessed failure traces from Firestore (`evalforge_raw_traces`), calls Vertex AI Gemini (`gemini-2.5-flash`) to extract a structured failure pattern per trace, validates the output against a defined schema, persists the pattern in Firestore (`evalforge_failure_patterns`), and then marks the source trace as processed. Extraction is resilient (per-trace error isolation, retries, strict JSON validation), privacy-safe (only short redacted evidence excerpts are stored), and observable (run IDs + trace IDs in structured logs, timing, and per-trace outcomes).

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: Google Cloud client libraries (Firestore, Secret Manager), **Google Gen AI SDK (`google-genai`)** for Gemini access (note: `vertexai.generative_models` is deprecated as of June 2025), FastAPI (Cloud Run HTTP surface), `tenacity` (retry/backoff), Pydantic (schema validation)  
**Storage**: Firestore collections `evalforge_raw_traces` (input) and `evalforge_failure_patterns` (output), both using `FIRESTORE_COLLECTION_PREFIX`  
**Testing**: pytest with unit tests for schema validation + truncation/redaction, contract tests for Firestore document shapes, and live-marked integration tests for Gemini calls with cached golden responses for CI cost control  
**Target Platform**: Google Cloud Run (stateless service, invoked by Cloud Scheduler over HTTPS)  
**Project Type**: Single backend service within existing Python project (`src/extraction`)  
**Performance Goals**: Per-trace processing completes within 10 seconds (including model call + validation + storage) for ≥95% of traces in the 10-trace evaluation set; batch run processes up to `BATCH_SIZE` (default 50) sequentially to reduce rate-limit risk  
**Constraints**: Cloud Scheduler triggers every 30 minutes; per-trace time budget of 15 seconds enforced internally (to meet spec's 10-second target for ≥95% of traces; timeout → error recorded, batch continues). Trace payloads >200KB are truncated (keep last 100KB) before model call. Only short redacted evidence snippets may be stored. Idempotent per trace: repeated runs update the same pattern record and do not create duplicates.  
**Scale/Scope**: Initial run processes up to 50 unprocessed traces per scheduler tick; backlog clearance and parallelism can be tuned later once rate limits and costs are measured.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Observability-First Insight Trail**: Each run emits a `run_id` and logs per-trace decisions (`picked_up`, `skipped`, `pattern_stored`, `validation_failed`, `timed_out`) with `source_trace_id` and `pattern_id`. Model config (model name, temperature) and prompt hash are logged; raw PII is never logged.  
- **Human-Governed Fail-Safe Loops**: This feature only extracts and stores patterns; it does not auto-create or auto-approve evals/guardrails/runbooks. Any downstream creation remains pending until explicit human approval.  
- **Cost-Conscious Experimentation**: The service limits work per run (`BATCH_SIZE`, sequential processing), enforces token caps, and avoids reprocessing by using `processed` flags + idempotent writes. If a run would exceed an agreed budget, it exits early with a run summary indicating throttling.  
- **Reliability & Cognitive Ease**: Gemini calls retry up to 3 times with exponential backoff; invalid JSON is handled as a per-trace error with stored diagnostic metadata. `/health` reports last run time and backlog estimates for operational clarity.  
- **Demo-Ready Transparency & UX**: Stored patterns include reproduction context, severity, confidence, and a trace reference. A run summary is produced per execution to demo the “Incident → Insight” loop.  
- **Platform & Compliance Constraints**: Cloud Run only; Vertex AI/Gemini only; prompts/responses/snippets are redacted before persistence; secrets come from Secret Manager; all calls use HTTPS.  
- **Workflow & Quality Gates**: Add tests for schema validation and Firestore shapes; mark live Gemini tests with `pytest` markers and use cached goldens to cap CI cost.

All gates are satisfied by this plan. If cost/latency measurements show repeated overruns, the follow-up will be to reduce batch size, tighten truncation, or introduce a cheaper fallback mode.

## Project Structure

### Documentation (this feature)

```text
specs/002-extract-failure-patterns/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/
├── extraction/
│   ├── main.py
│   ├── models.py
│   ├── prompt_templates.py
│   └── gemini_client.py      # Uses google-genai SDK (not deprecated vertexai)
├── ingestion/
│   └── ...
├── api/
│   └── ...
└── common/
    └── ...

tests/
├── contract/
│   └── test_failure_pattern_payload_shape.py
├── integration/
│   └── test_extraction_service_api.py
└── unit/
    ├── test_failure_pattern_schema.py
    └── test_extraction_truncation_and_redaction.py
```

**Structure Decision**: Add a new `src/extraction` package for the Cloud Run extraction service, reuse `src/common` for config/logging, and keep tests in existing `tests/unit`, `tests/contract`, and `tests/integration` groupings.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
