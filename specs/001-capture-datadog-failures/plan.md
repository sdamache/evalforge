# Implementation Plan: Automatic Capture of Datadog Failures

**Branch**: `001-capture-datadog-failures` | **Date**: 2025-12-04 | **Spec**: `specs/001-capture-datadog-failures/spec.md`
**Input**: Feature specification describing automatic capture of Datadog LLM Observability failures into an actionable backlog.

## Summary

This feature introduces an ingestion service that regularly pulls LLM failure traces from Datadog, strips PII, and stores normalized records in Firestore for later triage into evals, guardrails, and runbooks. A time-based scheduler triggers a stateless Cloud Run service every 15 minutes to query Datadog using quality thresholds and evaluation flags, deduplicate by trace ID, and persist enriched failure captures for downstream review.

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: `datadog-api-client` (Python), Google Cloud client libraries (Firestore, Secret Manager), HTTP client, retry/backoff helper  
**Storage**: Firestore collection `evalforge_raw_traces` (with prefixed collection name via `FIRESTORE_COLLECTION_PREFIX`)  
**Testing**: pytest with integration tests against real Datadog and Vertex AI/Gemini where feasible, plus cached golden responses for CI cost control  
**Target Platform**: Google Cloud Run (stateless service, HTTPS ingress)
**Project Type**: Single backend service within existing Python project  
**Performance Goals**: Each scheduled run (15-minute cadence) must clear a 24h lookback within the pod’s execution window while staying below ~200 requests/minute average (headroom under the 300 req/min org limit). Use `page[limit]=100` on APM/LLM trace search to keep latency predictable and cap total calls per run at ~2.5k (25 minutes of budgeted capacity if fully saturated, still below limit with retries).  
**Constraints**: Datadog REST APIs expose rate-limit headers (`X-RateLimit-Limit/Period/Remaining/Reset/Name`) and return 429 when exceeded; default org bucket is ~300 requests/minute. Ingestion must read headers, back off using `Retry-After` when present, apply jittered exponential retry for 429/5xx, and stop pagination when `meta.page.after` is absent.  
**Scale/Scope**: Initial focus on a manageable subset of LLM agents (single Datadog service tag), expandable to more services after validating performance and cost

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Observability-First Insight Trail**: Plan logs Scheduler triggers, Datadog requests, filters applied, decisions per trace (include/exclude), and Firestore write results with trace IDs and hashed user IDs. All ingestion decisions must be traceable.
- **Human-Governed Fail-Safe Loops**: Ingestion only records failures; it does not auto-create or deploy evals, guardrails, or runbooks. Downstream export and approval remain human-driven.
- **Cost-Conscious Experimentation**: Datadog queries are scheduled every 15 minutes with a configurable lookback window and quality threshold. We will add basic metrics for request volume and estimated cost; heavy backfills require explicit approval.
- **Reliability & Cognitive Ease**: Datadog calls use retry with exponential backoff (up to 3 attempts) and emit clear error logs. Failures do not block other platform workflows; they only impact ingestion freshness.
- **Demo-Ready Transparency & UX**: Firestore records will include normalized metadata (failure type, quality score, timestamps) to support later dashboards and demos showing the Incident-to-Insight loop end-to-end.
- **Platform & Compliance Constraints**: Uses Cloud Run (stateless), Firestore, Datadog API, and Secret Manager only. No raw PII is stored; user identifiers are hashed before persistence.
- **Workflow & Quality Gates**: Integration tests will hit real Datadog endpoints with cached responses for CI, and latency/cost/observability considerations will be revisited after Phase 1 design.

All gates are satisfied by this plan; any new cost-heavy backfill or expansion beyond the initial agent scope will require an explicit follow-up review.

## Project Structure

### Documentation (this feature)

```text
specs/001-capture-datadog-failures/
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
├── ingestion/
│   ├── datadog_client.py
│   ├── models.py
│   ├── pii_sanitizer.py
│   └── main.py
├── common/
│   ├── config.py
│   └── logging.py
└── ...

tests/
├── integration/
│   └── test_ingestion_datadog_firehose.py
├── contract/
│   └── test_ingestion_payload_shape.py
└── unit/
    └── test_pii_sanitizer.py
```

**Structure Decision**: Single backend service within `src/ingestion` plus shared helpers in `src/common`, with tests under `tests/` grouped by unit, contract, and integration.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
