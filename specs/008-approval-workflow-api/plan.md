# Implementation Plan: Approval Workflow API

**Branch**: `008-approval-workflow-api` | **Date**: 2025-12-29 | **Spec**: `specs/008-approval-workflow-api/spec.md`
**Input**: Feature specification from `specs/008-approval-workflow-api/spec.md`

## Summary

Add a **human-in-the-loop approval workflow API** to the existing Capture Queue API that enables platform leads to approve or reject suggestions with one click, trigger Slack webhook notifications on status changes, and export approved artifacts in multiple CI-ready formats (DeepEval JSON, Pytest, YAML). The service extends `src/api/` with new routers for `/suggestions/*` endpoints, uses atomic Firestore transactions for status transitions, and maintains a complete audit trail via `version_history`.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: FastAPI (async endpoints), google-cloud-firestore, `requests` (Slack webhooks), Pydantic (schema validation), PyYAML (YAML export)
**Storage**:
- Firestore collection `{FIRESTORE_COLLECTION_PREFIX}suggestions` (read + update status, approval_metadata, version_history)
- Existing Suggestion schema from Issue #3 (deduplication)
**Testing**: pytest **live integration tests only** (minimal mode) in `tests/integration/` guarded by `RUN_LIVE_TESTS=1` (real Firestore). **No mocks.**
**Target Platform**: Google Cloud Run (stateless service, existing API deployment)
**Project Type**: Extension of existing backend API (`src/api/`)
**Performance Goals**: 95% of approval/rejection requests complete within 3 seconds; export requests return valid files within 3 seconds; webhooks fire within 5 seconds of status change
**Constraints**: API key authentication (header-based); atomic status transitions (no partial updates); webhook failures must not block approval; all status changes audited in version_history
**Scale/Scope**: Hackathon-scale (~100-1000 suggestions). Single approver model, no multi-reviewer workflows.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Observability-First Insight Trail**: All approval/rejection actions logged with `suggestion_id`, `actor`, `action`, `timestamp`. Status transitions recorded in `version_history` array. Webhook delivery outcomes logged.
- **Human-Governed Fail-Safe Loops**: Core feature - explicit human approval required before suggestions become actionable. Status transitions are one-way (pending→approved/rejected). Export only available for approved suggestions.
- **Cost-Conscious Experimentation**: No LLM calls in this feature - pure API/storage operations. Firestore reads/writes are within free tier for hackathon scale.
- **Reliability & Cognitive Ease**: Webhook failures logged but do not block approval (fire-and-forget with retry logging). Clear error responses with actionable messages. Health check includes last approval timestamp.
- **Demo-Ready Transparency & UX**: One-click approve/reject actions. Export returns ready-to-use files. Slack notifications provide immediate visibility.
- **Platform & Compliance Constraints**: Cloud Run only; Firestore storage; API key from environment (Secret Manager in prod); HTTPS only; no PII in webhook payloads.
- **Workflow & Quality Gates**: Minimal mode uses **live** integration tests only (`RUN_LIVE_TESTS=1`) to validate real Firestore behavior.

**Gate Result**: PASSED - No violations.

## Project Structure

### Documentation (this feature)

```text
specs/008-approval-workflow-api/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── approval-api-openapi.yaml
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
src/
├── api/
│   ├── __init__.py
│   ├── main.py                  # Existing FastAPI app - add approval router
│   ├── capture_queue.py         # Existing
│   ├── exports.py               # Existing
│   ├── approval/                # NEW: Approval workflow module
│   │   ├── __init__.py
│   │   ├── router.py            # FastAPI router for /suggestions/* endpoints
│   │   ├── models.py            # Pydantic request/response models
│   │   ├── service.py           # Business logic (approve, reject, export)
│   │   ├── repository.py        # Firestore operations (atomic updates)
│   │   ├── webhook.py           # Slack notification sender
│   │   └── exporters.py         # Format exporters (DeepEval, Pytest, YAML)
│   └── auth.py                  # NEW: API key authentication middleware
└── common/
    ├── config.py                # Add APPROVAL_API_KEY, SLACK_WEBHOOK_URL
    ├── firestore.py             # Existing
    └── logging.py               # Existing

tests/
└── integration/
    └── test_approval_workflow_live.py  # NEW: Live Firestore smoke tests (RUN_LIVE_TESTS=1)
```

**Structure Decision**: Extend existing `src/api/` with a new `approval/` submodule to keep approval workflow logic decoupled while reusing shared config/logging/Firestore helpers. Add `auth.py` for API key middleware used by approval endpoints.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| - | - | - |

## Deferred Decisions

| Decision | Reason Deferred | Impact if Deferred |
|----------|-----------------|-------------------|
| OAuth/OIDC authentication | Out of scope for hackathon | API key auth sufficient for demo; upgrade path clear |
| Bulk approval/rejection | Not in spec scope | Can be added later without schema changes |
| Webhook retry queue | Complexity for hackathon | Fire-and-forget with logging acceptable; failures logged for manual retry |
| Export to GitHub/CI | Out of scope | Export returns file content; integration is downstream concern |
| Interactive Slack Approvals | Requires full Slack App (not just webhook) | Current: one-way notifications only. Future: approve/reject via Slack buttons. Requires Slack App manifest, OAuth, Slack Events API endpoint to receive button clicks |
