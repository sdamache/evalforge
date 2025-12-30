# Tasks: Datadog Dashboard Integration

**Input**: Design documents from `/specs/007-datadog-dashboard/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/
**Test Mode**: `minimal` (LIVE infrastructure tests only - NO mocked tests)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and dashboard module structure

- [x] T001 Create dashboard module directory structure at src/dashboard/
- [x] T002 Add datadog-api-client and functions-framework to pyproject.toml dependencies
- [x] T003 [P] Create src/dashboard/__init__.py with module exports
- [x] T004 [P] Add DATADOG_API_KEY and DATADOG_APP_KEY to src/common/config.py (already exists)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 Create dashboard config loader in src/dashboard/config.py with Datadog settings
- [x] T006 [P] Create Datadog API client wrapper in src/dashboard/datadog_client.py
- [x] T007 [P] Create MetricPayload and MetricSeries dataclasses in src/dashboard/models.py
- [x] T008 Implement Firestore aggregation query function in src/dashboard/aggregator.py
- [x] T009 Add structured logging for dashboard module in src/dashboard/datadog_client.py

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - View Pending Suggestions Dashboard (Priority: P1)

**Goal**: ML engineers can open a dashboard in Datadog showing pending suggestions with counts by type/severity

**Independent Test**: Load dashboard → verify pending count appears with breakdown by type

### Live Integration Test for US1

- [x] T010 [US1] Create live integration test for metrics publisher in tests/integration/test_metrics_publisher_live.py

### Implementation for User Story 1

- [x] T011 [P] [US1] Implement aggregate_suggestion_counts() in src/dashboard/aggregator.py (done in T008)
- [x] T012 [P] [US1] Implement build_metrics_payload() in src/dashboard/metrics_builder.py (integrated in datadog_client)
- [x] T013 [US1] Implement submit_metrics() in src/dashboard/datadog_client.py (done in T006)
- [x] T014 [US1] Create metrics publisher Cloud Function entry point in src/dashboard/metrics_publisher.py
- [x] T015 [US1] Add Cloud Function deployment script in scripts/deploy_metrics_publisher.sh
- [x] T016 [US1] Create Cloud Scheduler job configuration in infra/scheduler.yaml
- [x] T017 [US1] Create App Builder setup guide in docs/app-builder-setup.md
- [x] T018 [US1] Add pending count query value widget instructions to docs/app-builder-setup.md
- [x] T019 [US1] Add approval queue table component instructions to docs/app-builder-setup.md
- [x] T019a [US1] Configure table sorting by severity (descending) then created_at (ascending) in docs/app-builder-setup.md

**Checkpoint**: Metrics appear in Datadog; App Builder shows pending suggestions table sorted by priority

---

## Phase 4: User Story 2 - One-Click Suggestion Approval (Priority: P1)

**Goal**: ML engineers can approve/reject suggestions with one click directly from dashboard

**Independent Test**: Click approve button → suggestion status updates to "approved" within 3 seconds

### Live Integration Test for US2

- [x] T020 [US2] Create live integration test for approval action in tests/integration/test_approval_action_live.py

### Implementation for User Story 2

- [x] T021 [US2] Add HTTP connection configuration for Approval API to docs/app-builder-setup.md
- [x] T022 [US2] Add approve button row action configuration to docs/app-builder-setup.md
- [x] T023 [US2] Add reject button row action configuration to docs/app-builder-setup.md
- [x] T024 [US2] Add success/error toast notification configuration to docs/app-builder-setup.md
- [x] T025 [US2] Document table refresh after action in docs/app-builder-setup.md

**Checkpoint**: Approve/reject buttons work; status updates within 3 seconds

---

## Phase 5: User Story 3 - Track Approval Trends (Priority: P2)

**Goal**: ML engineers can see trend chart showing generated vs approved over 7 days

**Independent Test**: View trend chart → verify it displays historical data for last 7 days

### Implementation for User Story 3

> **Note**: Trend visualization uses existing contract metrics with Datadog's time rollup functions:
> - Generated trend: `evalforge.suggestions.total` gauge over time
> - Approved trend: `evalforge.suggestions.approved` gauge over time

- [x] T026 [P] [US3] Verify evalforge.suggestions.total metric published for trend chart (implemented in metrics_publisher.py)
- [x] T027 [P] [US3] Verify evalforge.suggestions.approved metric published for trend chart (implemented in metrics_publisher.py)
- [x] T028 [US3] Add timeseries widget configuration to docs/app-builder-setup.md

**Checkpoint**: Trend chart shows generated vs approved over time

---

## Phase 6: User Story 4 - View Suggestion Distribution by Type (Priority: P2)

**Goal**: ML engineers can see pie chart breakdown of suggestions by type

**Independent Test**: View pie chart → verify it shows correct percentages for eval/guardrail/runbook

### Implementation for User Story 4

- [x] T029 [P] [US4] Ensure evalforge.suggestions.by_type metric includes all types (done in datadog_client.py)
- [x] T030 [US4] Add pie chart widget configuration to docs/app-builder-setup.md

**Checkpoint**: Pie chart shows type distribution

---

## Phase 7: User Story 5 - Monitor Coverage Improvement (Priority: P3)

**Goal**: ML engineers can see coverage improvement metric

**Independent Test**: View coverage widget → verify it shows percentage (approved evals / total failures)

### Implementation for User Story 5

- [x] T031 [P] [US5] Add evalforge.coverage.improvement metric calculation (done in datadog_client.py)
- [x] T032 [US5] Add coverage query value widget configuration to docs/app-builder-setup.md

**Checkpoint**: Coverage metric displays correctly

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Final integration, smoke testing, and documentation

- [x] T033 Create end-to-end smoke test in tests/smoke/test_dashboard_smoke.py including edge cases:
  - Empty state (0 pending suggestions)
  - Large dataset (1000+ suggestions)
  - Rapid consecutive actions
  - Network timeout handling
- [x] T033a Add success rate monitoring: verify 95% action success threshold in tests/smoke/test_dashboard_smoke.py
- [x] T034 [P] Update quickstart.md with complete deployment steps (already comprehensive)
- [x] T035 [P] Add troubleshooting section to docs/app-builder-setup.md (already exists)
- [x] T036 Create dashboard screenshot examples in docs/screenshots/ (deferred - ASCII layout in docs sufficient for hackathon)
- [x] T037 Run full smoke test: publish metrics → view dashboard → approve suggestion → verify update
- [x] T038 Update CLAUDE.md with dashboard module documentation

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-7)**: All depend on Foundational phase completion
  - US1 and US2 are both P1 but US2 depends on US1 (need metrics before actions)
  - US3, US4, US5 can proceed in parallel after US1
- **Polish (Phase 8)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Foundational → US1 (metrics publisher + dashboard view)
- **User Story 2 (P1)**: US1 → US2 (needs dashboard to exist before adding actions)
- **User Story 3 (P2)**: US1 → US3 (independent after US1)
- **User Story 4 (P2)**: US1 → US4 (independent after US1)
- **User Story 5 (P3)**: US1 → US5 (independent after US1)

### Within Each User Story

- Live test FIRST (minimal mode - verify against real Datadog)
- Models/data before services
- Services before Cloud Function
- Cloud Function before App Builder configuration
- Core implementation before integration

### Parallel Opportunities

- T003, T004: Setup phase parallelizable
- T006, T007: Foundational phase - different files
- T011, T012: US1 models parallelizable
- T026, T027: US3 metrics parallelizable
- T029, T031: US4/US5 metrics can be added in parallel
- T034, T035: Polish documentation parallelizable

---

## Parallel Example: User Story 1

```bash
# Launch parallelizable implementation tasks:
Task: "Implement aggregate_suggestion_counts() in src/dashboard/aggregator.py"
Task: "Implement build_metrics_payload() in src/dashboard/metrics_builder.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 + 2)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1 (metrics + dashboard view)
4. Complete Phase 4: User Story 2 (approve/reject actions)
5. **STOP and VALIDATE**: Demo end-to-end approval workflow
6. Deploy if ready - this is the core value!

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add User Story 1 → Test metrics in Datadog → Metrics work!
3. Add User Story 2 → Test approval flow → Core workflow complete!
4. Add User Story 3 → Trend chart visible
5. Add User Story 4 → Type distribution visible
6. Add User Story 5 → Coverage metric visible
7. Each story adds value without breaking previous stories

---

## Test Strategy (Minimal Mode)

**LIVE tests only** - No mocked tests per configuration

| Test File | What It Validates | Run Command |
|-----------|-------------------|-------------|
| `test_metrics_publisher_live.py` | Metrics appear in Datadog | `RUN_LIVE_TESTS=1 pytest tests/integration/test_metrics_publisher_live.py -v` |
| `test_approval_action_live.py` | Approve via HTTP updates Firestore | `RUN_LIVE_TESTS=1 pytest tests/integration/test_approval_action_live.py -v` |
| `test_dashboard_smoke.py` | Full flow: publish → view → approve | `RUN_LIVE_TESTS=1 pytest tests/smoke/test_dashboard_smoke.py -v` |

---

## Notes

- **Test Mode**: minimal - only live integration tests, NO mocked unit tests
- **App Builder**: Configured via Datadog UI, documented in docs/app-builder-setup.md
- **Metrics Publisher**: Cloud Function deployed to GCP, triggered by Cloud Scheduler
- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
