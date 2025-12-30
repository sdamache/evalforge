# Implementation Plan: Datadog Dashboard Integration

**Branch**: `007-datadog-dashboard` | **Date**: 2025-12-29 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/007-datadog-dashboard/spec.md`
**Test Mode**: `minimal` (LIVE infrastructure tests only - no mocked tests)

## Summary

Build an interactive Datadog dashboard for ML engineers to view and approve/reject EvalForge improvement suggestions. The dashboard uses **Datadog App Builder** (recommended) or **Iframe Widget** (fallback) to display pending suggestions with one-click approve/reject actions. A **metrics publisher** service pushes aggregated Firestore data to Datadog's Metrics API for dashboard widgets.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**:
- `datadog-api-client` (Datadog Metrics API)
- `google-cloud-firestore` (read suggestions)
- `functions-framework` (Cloud Functions)
- FastAPI (if building iframe fallback UI)

**Storage**: Firestore `evalforge_suggestions` collection (read-only for this feature)
**Testing**: pytest with `RUN_LIVE_TESTS=1` for live Datadog API tests (NO mocked tests)
**Target Platform**:
- Metrics Publisher: Google Cloud Functions (Python 3.11)
- App Builder App: Datadog UI (no code deployment)
- Iframe Fallback: Cloud Run (if needed)

**Project Type**: Single (metrics publisher service)
**Performance Goals**:
- Dashboard load: <2 seconds
- Approve/reject action: < 3 seconds
- Metrics refresh: every 60 seconds

**Constraints**:
- Must use Datadog App Builder or Iframe Widget (UI Extensions deprecated March 2025)
- Metrics publisher must run every 60 seconds via Cloud Scheduler
- HTTP request actions for approve/reject (not deep links)

**Scale/Scope**:
- Up to 1000 pending suggestions
- Single Datadog organization

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| **Observability-First Insight Trail** | PASS | Metrics publisher emits structured logs; all suggestions link to source trace_ids |
| **Human-Governed Fail-Safe Loops** | PASS | Core purpose: approve/reject UI requires explicit human action before artifacts deploy |
| **Cost-Conscious Experimentation** | PASS | Cloud Function runs 60s intervals (~$0.01/day); no per-action LLM calls |
| **Reliability & Cognitive Ease** | PASS | Dashboard <2s load; one-click actions; severity-sorted queue |
| **Demo-Ready Transparency & UX** | PASS | App Builder provides native Datadog experience; shows reasoning via linked patterns |
| **Platform Constraints** | PASS | Cloud Functions on GCP (stateless like Cloud Run; acceptable for scheduled jobs per constitution intent); Datadog live API; no mock data |
| **Workflow & Quality Gates** | PASS | Live integration tests only; no mocked tests per minimal mode |

**Gate Result**: PASS - No violations. Proceed with implementation.

## Project Structure

### Documentation (this feature)

```text
specs/007-datadog-dashboard/
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # Datadog integration options analysis (complete)
├── data-model.md        # Metrics and entities
├── quickstart.md        # Setup and deployment guide
├── contracts/           # API contracts
│   └── metrics-api.yaml # Datadog metrics format
└── tasks.md             # Implementation tasks (created by /speckit.tasks)
```

### Source Code (repository root)

```text
src/
├── dashboard/                    # NEW: Dashboard integration module
│   ├── __init__.py
│   ├── metrics_publisher.py      # Cloud Function: push metrics to Datadog
│   ├── datadog_client.py         # Datadog API wrapper (reuse pattern from ingestion)
│   └── config.py                 # Dashboard-specific configuration
│
├── api/                          # EXISTING: Approval API (Issue #8)
│   └── suggestions.py            # Already has GET /suggestions, POST /approve
│
└── common/                       # EXISTING: Shared utilities
    ├── config.py                 # Add DATADOG_API_KEY, DATADOG_APP_KEY
    └── logging.py                # Structured logging

tests/
├── integration/                  # LIVE tests only (minimal mode)
│   ├── test_metrics_publisher_live.py  # Live Datadog metrics API tests
│   └── test_approval_action_live.py    # Live approval workflow tests
│
└── smoke/                        # End-to-end validation
    └── test_dashboard_smoke.py   # Full flow: publish → view → approve

# App Builder Configuration (no code - configured in Datadog UI)
docs/
└── app-builder-setup.md          # Step-by-step App Builder configuration guide
```

**Structure Decision**: Single project extending existing `src/` with new `dashboard/` module. Metrics publisher is a standalone Cloud Function. App Builder app is configured via Datadog UI (no code deployment).

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATADOG DASHBOARD                             │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ App Builder App (or Iframe Widget)                             │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐│  │
│  │  │ Pending: 12 │  │ Pie Chart   │  │ Approval Queue Table    ││  │
│  │  │ Approved: 45│  │ by Type     │  │ ID | Type | [✓] [✗]    ││  │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────┘│  │
│  └───────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │ HTTP Request Actions
                                    ▼
┌───────────────────────────────────────────────────────────────────┐
│                    APPROVAL API (Issue #8)                         │
│  POST /suggestions/{id}/approve                                    │
│  POST /suggestions/{id}/reject                                     │
│  GET  /suggestions?status=pending                                  │
└───────────────────────────────────┬───────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────┐
│                         FIRESTORE                                  │
│  Collection: evalforge_suggestions                                 │
│  Documents: {suggestion_id, type, status, severity, created_at}    │
└───────────────────────────────────┬───────────────────────────────┘
                                    │
                                    ▲
┌───────────────────────────────────┴───────────────────────────────┐
│                    METRICS PUBLISHER                               │
│  Cloud Function (every 60s via Cloud Scheduler)                    │
│  - Count pending/approved/rejected                                 │
│  - Group by type, severity                                         │
│  - Push to Datadog Metrics API                                     │
└───────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────┐
│                    DATADOG METRICS API                             │
│  POST https://api.datadoghq.com/api/v2/series                      │
│  Metrics: evalforge.suggestions.pending                            │
│           evalforge.suggestions.by_type{type:eval}                 │
│           evalforge.suggestions.by_severity{severity:high}         │
└───────────────────────────────────────────────────────────────────┘
```

## Implementation Phases

### Phase 1: Metrics Publisher (Core Infrastructure)

1. Create `src/dashboard/metrics_publisher.py` Cloud Function
2. Read aggregated counts from Firestore
3. Push metrics to Datadog Metrics API using `datadog-api-client`
4. Deploy to Cloud Functions with Cloud Scheduler trigger (every 60s)
5. **Live Test**: Verify metrics appear in Datadog Metrics Explorer

### Phase 2: App Builder App (Primary Dashboard)

1. Create App Builder app in Datadog UI
2. Add HTTP connection to Approval API with Token Auth
3. Create table component with suggestion data
4. Add approve/reject row action buttons
5. Configure button click → HTTP POST actions
6. Embed app in dashboard as App Widget
7. Add metrics widgets (query values, pie chart, line chart)
8. **Live Test**: End-to-end approve flow

### Phase 3: Iframe Widget (Fallback - Optional)

*Only if App Builder proves insufficient*

1. Create minimal React approval UI
2. Deploy to Cloud Run
3. Embed via Iframe Widget
4. **Live Test**: Approve action via iframe

## Deferred Decisions

| Decision | Why Deferred | When to Revisit |
|----------|--------------|-----------------|
| Iframe vs App Builder | Try App Builder first; iframe only if needed | After Phase 2 |
| Advanced filtering | Out of scope for hackathon | Post-demo |
| Dashboard API automation | Manual setup faster for demo | Production rollout |

## Test Strategy (Minimal Mode)

**LIVE tests only** - No mocked tests per test mode configuration.

| Test | Location | What It Validates |
|------|----------|-------------------|
| `test_metrics_publisher_live.py` | `tests/integration/` | Metrics appear in Datadog within 120s |
| `test_approval_action_live.py` | `tests/integration/` | Approve via HTTP updates Firestore status |
| `test_dashboard_smoke.py` | `tests/smoke/` | Full flow: publish → view → approve |

**Run with**: `RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/ -v`

## Dependencies (Verified)

| Dependency | Status | Notes |
|------------|--------|-------|
| Issue #8 Approval Workflow API | COMPLETE | PR #22 merged |
| Firestore `evalforge_suggestions` | READY | Populated by upstream services |
| Datadog API credentials | REQUIRED | Add to Secret Manager |
| Cloud Scheduler | REQUIRED | For metrics publisher trigger |

## Next Steps

1. Run `/speckit.tasks` to generate detailed implementation tasks
2. Implement metrics publisher (Phase 1)
3. Configure App Builder app (Phase 2)
4. Run live integration tests
5. Demo end-to-end flow
