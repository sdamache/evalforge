# Tasks: Approval Workflow API

**Input**: Design documents from `specs/008-approval-workflow-api/`
**Prerequisites**: `specs/008-approval-workflow-api/plan.md`, `specs/008-approval-workflow-api/spec.md`, `specs/008-approval-workflow-api/research.md`, `specs/008-approval-workflow-api/data-model.md`, `specs/008-approval-workflow-api/contracts/approval-api-openapi.yaml`

**Tests**: Minimal mode — **live integration tests only** (no mocks). Tests MUST be skipped unless `RUN_LIVE_TESTS=1`.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the approval workflow package structure and configuration.

- [x] T001 Create approval workflow package skeleton in `src/api/approval/` (`__init__.py`, `router.py`, `models.py`, `service.py`, `repository.py`, `webhook.py`, `exporters.py`)
- [x] T002 Add approval workflow settings to `src/common/config.py` (`APPROVAL_API_KEY`, `SLACK_WEBHOOK_URL`)
- [x] T003 [P] Document new env vars in `.env.example` (APPROVAL_API_KEY, SLACK_WEBHOOK_URL)
- [x] T004 [P] Create API key authentication middleware in `src/api/auth.py` (using `secrets.compare_digest` per research.md)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core building blocks shared by all user stories.

- [x] T005 Define Pydantic request/response models in `src/api/approval/models.py` (align to `specs/008-approval-workflow-api/data-model.md` and OpenAPI contract)
- [x] T006 [P] Implement Firestore repository in `src/api/approval/repository.py` (query suggestions with cursor-based pagination per research.md, read single suggestion, atomic status update with `@firestore.transactional`)
- [x] T007 [P] Implement Slack webhook sender in `src/api/approval/webhook.py` (fire-and-forget with 5s timeout, Block Kit format per research.md)
- [x] T008 Register approval router in `src/api/main.py` with API key authentication dependency

**Checkpoint**: Core infrastructure ready - user story implementation can begin.

---

## Phase 3: User Story 1 - One-Click Suggestion Approval (Priority: P1) 🎯 MVP

**Goal**: Enable platform leads to approve pending suggestions with a single API call, triggering atomic status transition and webhook notification.

**Independent Test**: Create a pending suggestion in Firestore, call POST /suggestions/{id}/approve, verify status is "approved" and version_history is updated.

### Live Integration Test (minimal mode)

- [x] T009 [P] [US1] Add live smoke test in `tests/integration/test_approval_workflow_live.py` that:
  creates a test Suggestion doc in Firestore (with cleanup), calls POST /suggestions/{id}/approve with valid API key, and asserts status transitions to "approved", version_history has new entry, and webhook is attempted (log check)

### Implementation

- [x] T010 [US1] Implement `approve_suggestion()` in `src/api/approval/service.py` (validate pending status, call repository atomic update, trigger webhook via BackgroundTasks)
- [x] T011 [US1] Implement `POST /suggestions/{suggestionId}/approve` endpoint in `src/api/approval/router.py` (per OpenAPI contract, returns ApprovalResponse)
- [x] T012 [US1] Add structured logging for approval actions in `src/api/approval/service.py` using `src/common/logging.py`

**Checkpoint**: Approval workflow functional and testable independently.

---

## Phase 4: User Story 2 - Suggestion Rejection with Reasoning (Priority: P1)

**Goal**: Enable platform leads to reject suggestions with a required reason, maintaining audit trail.

**Independent Test**: Create a pending suggestion, call POST /suggestions/{id}/reject with reason, verify status is "rejected" and reason is recorded in approval_metadata.

### Live Integration Test (minimal mode)

- [x] T013 [P] [US2] Extend `tests/integration/test_approval_workflow_live.py` with a live test that:
  creates a test Suggestion doc, calls POST /suggestions/{id}/reject with reason, and asserts status is "rejected", approval_metadata.reason matches input, and version_history has rejection entry

### Implementation

- [x] T014 [US2] Implement `reject_suggestion()` in `src/api/approval/service.py` (validate pending status, require reason field, call repository atomic update, trigger webhook)
- [x] T015 [US2] Implement `POST /suggestions/{suggestionId}/reject` endpoint in `src/api/approval/router.py` (per OpenAPI contract, requires RejectRequest with reason)
- [x] T016 [US2] Add 409 Conflict response for non-pending suggestions in both approve/reject endpoints

**Checkpoint**: Approve and reject workflows both functional.

---

## Phase 5: User Story 3 - Export Approved Suggestions (Priority: P2)

**Goal**: Generate CI-ready exports in DeepEval JSON, Pytest, and YAML formats for approved suggestions.

**Independent Test**: Approve a suggestion, call GET /suggestions/{id}/export?format=deepeval, verify valid JSON is returned matching DeepEval schema.

### Live Integration Test (minimal mode)

- [ ] T017 [P] [US3] Extend `tests/integration/test_approval_workflow_live.py` with a live test that:
  creates and approves a test Suggestion, calls GET /suggestions/{id}/export for each format (deepeval, pytest, yaml), validates JSON is parseable, Python is syntactically valid (`ast.parse`), YAML is loadable (`yaml.safe_load`)

### Implementation

- [ ] T018 [P] [US3] Implement DeepEval JSON exporter in `src/api/approval/exporters.py` (per DeepEval schema from research.md: input, actual_output, expected_output, context, retrieval_context)
- [ ] T019 [P] [US3] Implement Pytest exporter in `src/api/approval/exporters.py` (generate syntactically valid Python test code)
- [ ] T020 [P] [US3] Implement YAML exporter in `src/api/approval/exporters.py` (generate valid YAML configuration)
- [ ] T021 [US3] Implement `export_suggestion()` in `src/api/approval/service.py` (validate approved status, select exporter by format, validate output before returning)
- [ ] T022 [US3] Implement `GET /suggestions/{suggestionId}/export` endpoint in `src/api/approval/router.py` (per OpenAPI contract, 409 if not approved, 422 if content missing)

**Checkpoint**: Export functionality complete for all three formats.

---

## Phase 6: User Story 4 - Browse Suggestion Queue (Priority: P2)

**Goal**: Enable platform leads to browse and filter the suggestion queue with cursor-based pagination.

**Independent Test**: Create multiple suggestions with different statuses/types, call GET /suggestions with filters, verify correct filtering and pagination.

### Live Integration Test (minimal mode)

- [ ] T023 [P] [US4] Extend `tests/integration/test_approval_workflow_live.py` with a live test that:
  creates 3+ test Suggestions with different statuses, calls GET /suggestions?status=pending, verifies only pending returned; tests pagination by setting limit=1 and using next_cursor

### Implementation

- [ ] T024 [US4] Implement `list_suggestions()` in `src/api/approval/service.py` (apply filters, call repository with cursor-based pagination per research.md)
- [ ] T025 [US4] Implement `GET /suggestions` endpoint in `src/api/approval/router.py` (per OpenAPI contract, query params: status, type, limit, cursor)
- [ ] T026 [US4] Implement `GET /suggestions/{suggestionId}` endpoint in `src/api/approval/router.py` (return full SuggestionDetail including version_history)

**Checkpoint**: Queue browsing and filtering complete.

---

## Phase 7: User Story 5 - Webhook Notification Configuration (Priority: P3)

**Goal**: Send Slack notifications on approval/rejection events with proper formatting and error handling.

**Independent Test**: Approve a suggestion with SLACK_WEBHOOK_URL configured, verify notification is sent (check logs or mock webhook endpoint).

### Live Integration Test (minimal mode)

- [ ] T027 [P] [US5] Extend `tests/integration/test_approval_workflow_live.py` with a live test that:
  configures a test webhook URL (if available) or verifies webhook sending is logged correctly; tests `/webhooks/test` endpoint

### Implementation

- [ ] T028 [US5] Implement Block Kit payload builder in `src/api/approval/webhook.py` (header, section with suggestion details, context with timestamp per research.md)
- [ ] T029 [US5] Implement `POST /webhooks/test` endpoint in `src/api/approval/router.py` (sends test message to configured webhook)
- [ ] T030 [US5] Add webhook failure logging (do not block approval, log for manual retry)

**Checkpoint**: Webhook notifications complete.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T031 [P] Implement `GET /health` endpoint in `src/api/approval/router.py` (include pendingCount, lastApprovalAt)
- [ ] T032 [P] Update `README.md` with approval workflow service documentation (endpoints, env vars, example curl commands)
- [ ] T033 [P] Add short operator notes to `specs/008-approval-workflow-api/quickstart.md` for common failure modes (401 auth errors, 409 conflicts, webhook timeouts)
- [ ] T034 Run quickstart.md validation (test all curl examples work)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Start immediately
- **Foundational (Phase 2)**: Blocks all user story work
- **User Story 1 (P1)**: Depends on Phase 2
- **User Story 2 (P1)**: Depends on Phase 2, can run parallel to US1
- **User Story 3 (P2)**: Depends on US1 (needs approved suggestion)
- **User Story 4 (P2)**: Depends on Phase 2, can run parallel to US1/US2
- **User Story 5 (P3)**: Depends on Phase 2, can run parallel but integrates with US1/US2

### User Story Dependencies

| Story | Depends On | Can Parallel With |
|-------|------------|-------------------|
| US1 (Approve) | Foundational | US2, US4 |
| US2 (Reject) | Foundational | US1, US4 |
| US3 (Export) | US1 (needs approved suggestion) | - |
| US4 (Browse) | Foundational | US1, US2, US5 |
| US5 (Webhook) | Foundational | US1, US2, US4 |

### Parallel Opportunities

- Phase 1: T003, T004 can run in parallel
- Phase 2: T006, T007 can run in parallel
- All live tests marked [P] can be written in parallel with implementation
- Exporters (T018, T019, T020) can run in parallel

---

## Parallel Example: User Story 3 Exporters

```bash
# Launch all exporter implementations together:
Task: "Implement DeepEval JSON exporter in src/api/approval/exporters.py"
Task: "Implement Pytest exporter in src/api/approval/exporters.py"
Task: "Implement YAML exporter in src/api/approval/exporters.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1 (Approve)
4. Complete Phase 4: User Story 2 (Reject)
5. **STOP and VALIDATE**: Test approve/reject flow end-to-end
6. Deploy/demo if ready - core approval workflow is functional

### Incremental Delivery

1. Setup + Foundational → Infrastructure ready
2. Add US1 + US2 → Core approval workflow → Demo (MVP!)
3. Add US3 → Export capability → Demo
4. Add US4 → Queue browsing → Demo
5. Add US5 → Notifications → Demo (Full feature)

### Test Mode Reminder

**Minimal mode**: All tests are in `tests/integration/test_approval_workflow_live.py` and require:
```bash
RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_approval_workflow_live.py -v
```

No mocked tests. No `@patch`. No `unittest.mock`. Real Firestore only.

---

## Notes

- [P] tasks = different files, no dependencies
- [US#] label maps task to specific user story for traceability
- Each user story is independently testable once Foundational phase complete
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
