---

description: "Task list for Automatic Capture of Datadog Failures"
---

# Tasks: Automatic Capture of Datadog Failures

**Input**: Design documents from `/specs/001-capture-datadog-failures/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Tests are REQUIRED for this feature based on the Evalforge constitution (integration-first with real Datadog/Gemini, cached for CI).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Single project backend: `src/` and `tests/` at repository root
- Ingestion service: `src/ingestion/`
- Shared utilities: `src/common/`
- API service: `src/api/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure for ingestion and tests.

- [x] T001 Create ingestion and common package structure in `src/ingestion/__init__.py` and `src/common/__init__.py`.
- [x] T002 Create test package structure in `tests/integration/__init__.py`, `tests/contract/__init__.py`, and `tests/unit/__init__.py`.
- [x] T003 [P] Declare ingestion dependencies (`datadog-api-client`, `google-cloud-firestore`, `google-cloud-secret-manager`, `tenacity`, `pytest`) in `pyproject.toml`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core research, models, and shared infrastructure that MUST be complete before any user story work begins.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Research & Clarifications (Phase 0 alignment)

- [x] T004 Resolve Datadog trace schema hypothesis by inspecting LLM Observability traces and updating `specs/001-capture-datadog-failures/research.md` to replace the trace-field [NEEDS CLARIFICATION] markers with confirmed fields.
 - [x] T005 [P] Validate failure classification signals (status codes, quality_score, eval flags) against Datadog docs/UI and update `specs/001-capture-datadog-failures/research.md` and `specs/001-capture-datadog-failures/spec.md` to resolve the classification-related [NEEDS CLARIFICATION] markers.
 - [x] T006 [P] Confirm Datadog rate limits and pagination semantics for the project’s tier and update `specs/001-capture-datadog-failures/plan.md` to resolve the Performance Goals and Constraints [NEEDS CLARIFICATION] entries.
 - [x] T007 [P] Enumerate all PII-like fields in Datadog LLM traces and update PII stripping rules in `specs/001-capture-datadog-failures/research.md` and `specs/001-capture-datadog-failures/data-model.md` to fully specify the sanitizer behavior.

### Shared Models & Infrastructure

 - [x] T008 Define `FailureCapture`, `SourceTraceReference`, and `ExportPackage` domain models in `src/ingestion/models.py` following `specs/001-capture-datadog-failures/data-model.md`.
 - [x] T009 Configure structured logging helpers (trace IDs, decision logs, error logs) in `src/common/logging.py` according to the Evalforge constitution.
 - [x] T010 Implement configuration loader in `src/common/config.py` to read Datadog, Firestore, and scheduler settings from environment variables defined in `specs/001-capture-datadog-failures/quickstart.md`.

**Checkpoint**: Research hypotheses resolved, core models and shared utilities ready — User Story implementation can now begin.

---

## Phase 3: User Story 1 - Auto-capture failure signals (Priority: P1) 🎯 MVP

**Goal**: Automatically capture Datadog LLM Observability failures into Firestore as normalized `FailureCapture` records without manual export.

**Independent Test**: Trigger a failed trace in a monitored Datadog environment and verify that a sanitized `FailureCapture` document appears in Firestore with full metadata within the agreed ingestion latency window.

### Tests for User Story 1 ⚠️

 - [x] T011 [P] [US1] Add contract test ensuring `FailureCapture` documents written to Firestore match the schema in `specs/001-capture-datadog-failures/contracts/ingestion-openapi.yaml` in `tests/contract/test_ingestion_payload_shape.py`.
 - [x] T012 [P] [US1] Add integration test that calls `/ingestion/run-once` and asserts new `FailureCapture` documents are created in Firestore with PII stripped in `tests/integration/test_ingestion_datadog_firehose.py`.

### Implementation for User Story 1

 - [x] T013 [P] [US1] Implement Datadog client helper to query recent LLM traces with filters and cursor-based pagination in `src/ingestion/datadog_client.py` using configuration from `src/common/config.py`.
 - [x] T014 [P] [US1] Implement PII stripping helper to remove configured PII fields and compute `user_hash` in `src/ingestion/pii_sanitizer.py` based on `specs/001-capture-datadog-failures/research.md`.
 - [x] T015 [US1] Implement ingestion orchestration to pull failures from Datadog, deduplicate by `trace_id`, and write `FailureCapture` docs to Firestore in `src/ingestion/main.py`.
 - [x] T016 [US1] Implement `/ingestion/run-once` HTTP handler matching `specs/001-capture-datadog-failures/contracts/ingestion-openapi.yaml` in `src/ingestion/main.py`.
 - [x] T017 [US1] Implement `/health` endpoint that reports connectivity to Datadog and Firestore and basic service status in `src/ingestion/main.py`.
 - [x] T018 [US1] Add structured logging and error handling (including retry/backoff outcomes) for each ingestion decision in `src/ingestion/main.py` and `src/ingestion/datadog_client.py`.
 - [x] T019 [US1] Ensure ingestion respects `TRACE_LOOKBACK_HOURS` and `QUALITY_THRESHOLD` configuration values via `src/common/config.py` and is wired into the Cloud Scheduler trigger path.

**Checkpoint**: User Story 1 fully functional — Datadog failures are automatically captured into Firestore and verifiable via tests.

---

## Phase 4: User Story 2 - Reviewable capture queue (Priority: P2)

**Goal**: Provide a normalized queue of captured failures with grouping, severity, and filters so reviewers can triage incidents without querying Datadog directly.

**Independent Test**: Seed Firestore with sample `FailureCapture` documents, call the queue endpoint, and verify the reviewer can filter by time range, severity, and agent and see grouped captures with recurrence counts.

### Tests for User Story 2 ⚠️

 - [x] T020 [P] [US2] Add integration test that exercises the capture queue listing API with filters (time range, severity, agent) in `tests/integration/test_failure_queue_api.py`.

### Implementation for User Story 2

 - [x] T021 [P] [US2] Implement Firestore query helper to read and filter `FailureCapture` documents with support for time range, severity, and agent filters in `src/api/capture_queue.py`.
 - [x] T022 [US2] Implement capture queue API endpoint to return grouped failures with recurrence counts and status fields in `src/api/main.py`.
 - [x] T023 [US2] Implement grouping and recurrence counting logic for related failures (same signature) in `src/api/capture_queue.py`.
 - [x] T024 [US2] Add pagination and error handling for the capture queue endpoint in `src/api/main.py`.

**Checkpoint**: User Story 1 and User Story 2 both independently testable — reviewers can browse the failure queue without leaving Evalforge.

---

## Phase 5: User Story 3 - Delivery to downstream improvement loop (Priority: P3)

**Goal**: Allow quality leads to export captured failures into downstream eval, guardrail, and runbook workflows via a consistent interface.

**Independent Test**: Mark a `FailureCapture` as ready, trigger export, and verify that an `ExportPackage` is created, downstream systems receive the payload, and export status is visible to reviewers.

### Tests for User Story 3 ⚠️

 - [x] T025 [P] [US3] Add integration test that exercises the export API to send a `FailureCapture` into downstream improvement queues and verifies export status updates in `tests/integration/test_export_failures_api.py`.

### Implementation for User Story 3

 - [x] T026 [P] [US3] Implement export helper to build and persist `ExportPackage` records for each exported failure in `src/api/exports.py`.
 - [x] T027 [US3] Implement export API endpoint to mark `FailureCapture` records as ready and trigger creation of `ExportPackage` payloads in `src/api/main.py`.
- [ ] T028 [US3] Update `FailureCapture` model to track export references and status fields in `src/ingestion/models.py` (export metadata and audit fields).
- [ ] T029 [US3] Implement integration hook that forwards `ExportPackage` payloads to downstream generator modules in `src/generators/export_bridge.py`.
- [ ] T030 [US3] Add audit logging for export actions (who exported, when, destination, status) in `src/common/logging.py`.

**Checkpoint**: All three user stories are independently functional — captured failures can be triaged and exported into improvement workflows.

---

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories, including documentation, performance, security, and UX.

- [ ] T031 [P] Add ingestion and queue documentation pages summarizing flows and configuration in `docs/ingestion.md` and `docs/failure_queue.md`.
- [ ] T032 [P] Add additional unit tests for PII edge cases and deduplication logic in `tests/unit/test_pii_sanitizer.py` and `tests/unit/test_deduplication_logic.py`.
- [ ] T033 Measure and optimize ingestion performance (latency and throughput) by profiling `src/ingestion/main.py` and `src/ingestion/datadog_client.py`.
- [ ] T034 Harden security and secret handling by reviewing uses of configuration and environment variables in `src/common/config.py` and `src/ingestion/main.py`.
- [ ] T035 Run through `specs/001-capture-datadog-failures/quickstart.md` end-to-end and fix any discrepancies in configuration or commands.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories until research hypotheses and shared infrastructure are in place.
- **User Stories (Phase 3, 4, 5)**: All depend on Foundational phase completion.
  - User Story 1 (P1) should be implemented first as the MVP.
  - User Story 2 (P2) can start after Foundational and US1 data shapes are stable.
  - User Story 3 (P3) can start after Foundational and US1 export fields exist; it should not break US1/US2 independence.
- **Polish (Final Phase)**: Depends on all desired user stories being complete.

### User Story Dependencies

- **User Story 1 (P1)**: Depends on Phase 2 models, logging, config, and resolved Datadog research; no dependencies on other user stories.
- **User Story 2 (P2)**: Depends on US1’s `FailureCapture` writes and Firestore schema; can be developed in parallel with late-stage US1 testing.
- **User Story 3 (P3)**: Depends on US1’s capture records and US2’s view of the queue; export should remain additive and not change capture semantics.

### Within Each User Story

- Tests (if included) MUST be written and fail before implementation.
- Models before services.
- Services before endpoints.
- Core implementation before cross-cutting integration.
- Each story should be independently demoable and testable.

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel.
- Research tasks T005–T007 can proceed in parallel once T004 is scoped.
- In US1, Datadog client, PII sanitizer, and tests (T011–T014) can proceed in parallel.
- In US2 and US3, helpers (`capture_queue.py`, `exports.py`) and integration tests can be worked on in parallel by different team members.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (research, models, logging, config).
3. Complete Phase 3: User Story 1 (ingestion into Firestore).
4. **STOP and VALIDATE**: Run US1 tests and verify Datadog failures appear as `FailureCapture` records.
5. Deploy/demo ingestion-only MVP.

### Incremental Delivery

1. Deliver US1 (automatic capture) as the first MVP.
2. Add US2 (reviewable queue) and validate triage experience via its tests and endpoints.
3. Add US3 (export to improvement loop) and validate end-to-end flow from incident to exported package.
4. Apply Phase N polishing (documentation, performance tuning, security, UX refinements).

### Parallel Team Strategy

- After Foundational phase, different team members can own each user story:
  - Developer A: US1 ingestion orchestration and reliability.
  - Developer B: US2 capture queue API and filters.
  - Developer C: US3 export flow and downstream integration.
- Coordination occurs via shared models (`src/ingestion/models.py`) and contracts (`specs/001-capture-datadog-failures/contracts/ingestion-openapi.yaml`).
