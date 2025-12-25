---

description: "Task list for feature implementation"
---

# Tasks: Failure Pattern Extraction

**Input**: Design documents from `specs/002-extract-failure-patterns/`  
**Prerequisites**: `plan.md` (required), `spec.md` (required for user stories), `research.md`, `data-model.md`, `contracts/`

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (`[US1]`, `[US2]`, `[US3]`)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure) ✅ COMPLETE

**Purpose**: Project initialization and basic structure

- [X] T001 [P] Create extraction package scaffold in `src/extraction/__init__.py`
- [X] T002 [P] Add `google-genai` dependency (Gemini access) in `pyproject.toml`
- [X] T003 [P] Document env vars (`GOOGLE_CLOUD_PROJECT`, `VERTEX_AI_LOCATION`, `GEMINI_MODEL`, `GEMINI_TEMPERATURE`, `GEMINI_MAX_OUTPUT_TOKENS`, `BATCH_SIZE`) in `.env.example`
- [X] T004 [P] Add Cloud Run Dockerfile for extraction service in `Dockerfile.extraction`
- [X] T005 [P] Align `evalforge_failure_patterns` schema (pattern_id, source_trace_id, title, failure_type, trigger_condition, summary, root_cause_hypothesis, evidence, recommended_actions, reproduction_context, severity, confidence, confidence_rationale, extracted_at) in `specs/002-extract-failure-patterns/data-model.md`
- [X] T006 [P] Align OpenAPI `FailurePattern` schema (same required fields/enums as T005) in `specs/002-extract-failure-patterns/contracts/extraction-openapi.yaml`

---

## Phase 2: Foundational (Blocking Prerequisites) ✅ COMPLETE

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T007 Create extraction settings loader + defaults (model `gemini-2.5-flash`, temperature 0.2, max output tokens 4096, batch size 50) in `src/extraction/config.py`
- [X] T008 [P] Define Pydantic request/response models in `src/extraction/models.py`
- [X] T009 [P] Define `FailurePattern` Pydantic schema model matching storage contract in `src/extraction/models.py`
- [X] T010 [P] Implement few-shot prompt template builder in `src/extraction/prompt_templates.py`
- [X] T011 [P] Implement trace serialization + truncation helper (>200KB → last 100KB) in `src/extraction/trace_utils.py`
- [X] T012 [P] Implement redaction helper for `evidence.excerpt` in `src/extraction/redaction.py`
- [X] T013 [P] Implement Gemini client wrapper using `google-genai` (model `gemini-2.5-flash`, temperature 0.2, max output tokens 4096, JSON-only response parsing via `response_mime_type`) in `src/extraction/gemini_client.py`
- [X] T014 Implement Firestore repository helpers (read unprocessed traces, write patterns, update processed) in `src/extraction/firestore_repository.py`
- [X] T015 Implement extraction FastAPI app skeleton + `/health` in `src/extraction/main.py`

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Batch extract failure patterns (Priority: P1) 🎯 MVP ✅ COMPLETE

**Goal**: Run scheduled/manual batch extraction that reads unprocessed traces, extracts one structured pattern per trace, persists it, and marks the trace processed.

**Independent Test**: Use 10 labeled sample failure traces; trigger an extraction run and verify ≥8/10 have correct `failure_type` + `trigger_condition` (primary contributing factor) per the rubric.

### Tests for User Story 1 ⚠️

- [X] T016 [P] [US1] Add labeled sample trace fixtures in `tests/data/extraction/sample_failure_spans.json`
- [X] T017 [P] [US1] Add unit-style test for run-once happy path (stub Gemini + fake Firestore) in `tests/unit/test_extraction_run_once.py`

### Implementation for User Story 1

- [X] T018 [P] [US1] Implement Firestore query for `processed=false` with batch limit in `src/extraction/firestore_repository.py`
- [X] T019 [P] [US1] Implement Firestore upsert for extracted patterns in `src/extraction/firestore_repository.py`
- [X] T020 [US1] Implement `POST /extraction/run-once` orchestration in `src/extraction/main.py`
- [X] T021 [US1] Mark source trace `processed=true` only after successful pattern write in `src/extraction/firestore_repository.py`
- [X] T022 [US1] Persist per-run summary record in `src/extraction/firestore_repository.py`
- [X] T023 [US1] Add structured per-trace and per-run logs (run_id, source_trace_id, outcome, timings, model config, prompt hash) in `src/extraction/main.py`
- [X] T024 [US1] Add AC1 evaluation script reading `tests/data/extraction/sample_failure_spans.json` and scoring (failure_type + trigger_condition) in `scripts/evaluate_failure_pattern_extraction.py`

**Checkpoint**: US1 complete — scheduled/manual runs produce stored patterns and mark inputs processed

---

## Phase 4: User Story 2 - Schema-validated storage for downstream use (Priority: P2) ✅ COMPLETE

**Goal**: Ensure only schema-valid extracted patterns are stored and retrievable by authorized internal users.

**Independent Test**: Run extraction on a small batch and confirm (1) schema-valid patterns are stored, (2) invalid outputs are rejected and recorded as validation errors, and (3) stored records match the contract schema exactly.

### Tests for User Story 2 ✅

- [X] T025 [P] [US2] Add unit tests for `FailurePattern` schema validation (required fields + enums + confidence range) in `tests/unit/test_failure_pattern_schema.py`
- [X] T026 [P] [US2] Add contract test asserting stored pattern payload matches OpenAPI schema in `tests/contract/test_failure_pattern_payload_shape.py`

### Implementation for User Story 2

- [X] T027 [US2] Validate Gemini output against `FailurePattern` model before any Firestore write in `src/extraction/main.py`
- [X] T028 [US2] Generate stable `pattern_id` and enforce idempotent writes by `source_trace_id` in `src/extraction/firestore_repository.py`
- [X] T029 [US2] Ensure extraction never writes non-conforming documents to `evalforge_failure_patterns` in `src/extraction/firestore_repository.py`
- [X] T030 [US2] Document internal-only access approach (Cloud Run invoker + Firestore IAM) in `specs/002-extract-failure-patterns/quickstart.md`

**Checkpoint**: US2 complete — output collection is 100% schema-valid and ready for downstream consumers

---

## Phase 5: User Story 3 - Resilient processing for malformed traces (Priority: P3) ✅ COMPLETE

**Goal**: Continue processing even with malformed traces, timeouts, invalid JSON, or transient Gemini failures; record errors and produce an accurate run summary.

**Independent Test**: Submit a batch with valid + malformed traces and confirm the run completes, valid traces produce stored patterns, and malformed traces are logged and recorded without halting the batch.

### Tests for User Story 3 ✅

- [X] T031 [P] [US3] Add unit tests for truncation and redaction behavior in `tests/unit/test_extraction_truncation_and_redaction.py`
- [X] T032 [P] [US3] Add unit-style test for mixed valid + malformed traces continuing the batch in `tests/unit/test_extraction_mixed_batch.py`

### Implementation for User Story 3

- [X] T033 [US3] Enforce per-trace time budget (<10s) and treat timeouts as per-trace errors in `src/extraction/main.py`
- [X] T034 [US3] Retry Gemini API failures 3x with exponential backoff in `src/extraction/gemini_client.py`
- [X] T035 [US3] Handle invalid JSON: log error, store `model_response_sha256` + short redacted `model_response_excerpt` in error record, and continue in `src/extraction/main.py`
- [X] T036 [US3] Handle malformed/incomplete traces (missing id/payload) by recording an error and continuing in `src/extraction/main.py`
- [X] T037 [US3] Persist per-trace error records (invalid_json, schema_validation, vertex_error, timeout) in `src/extraction/firestore_repository.py`
- [X] T038 [US3] Expand run summary fields (success/validation/error/timeout counts + trace references) in `src/extraction/models.py`

**Checkpoint**: US3 complete — batch runs are resilient and observable under imperfect inputs

---

## Phase 6: Polish & Cross-Cutting Concerns ✅ COMPLETE

**Purpose**: Improvements that affect multiple user stories

- [X] T039 [P] Add extraction service run instructions to `README.md`
- [X] T040 [P] Add a short validation section (local run + curl + expected Firestore writes) to `specs/002-extract-failure-patterns/quickstart.md`
- [X] T041 [P] Add a developer helper script for local run-once extraction in `scripts/run_extraction_once.sh`
- [X] T042 [P] Add Cloud Scheduler + Cloud Run invoker setup script for scheduled runs in `scripts/deploy_extraction_scheduler.sh`
- [X] T043 [P] Add live Gemini integration test (real endpoint) with `pytest` marker for enforcement in `tests/integration/test_extraction_live_gemini.py`
- [X] T044 [P] Add CI workflow to run live Gemini integration tests in `.github/workflows/live_gemini_integration_tests.yml`
- [X] T045 [P] Add confidence calibration spot-check instructions (20 samples) to `specs/002-extract-failure-patterns/quickstart.md`
- [X] T046 [P] Add PII audit checklist (20 samples, 0 raw sensitive user data) to `specs/002-extract-failure-patterns/quickstart.md`

**Checkpoint**: All phases complete — feature ready for production deployment

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational completion
  - US2 and US3 build on the US1 pipeline, but can be developed in parallel after the Foundational phase
- **Polish (Phase 6)**: Depends on desired user stories being complete

### User Story Dependencies

- **US1 (P1)**: Starts after Phase 2 — establishes the extraction pipeline
- **US2 (P2)**: Depends on US1 storage path — hardens schema validation + contract correctness
- **US3 (P3)**: Depends on US1 pipeline — adds resilience (timeouts, retries, malformed traces)

### Parallel Opportunities

- Phase 1: T001–T006 can run in parallel (different files)
- Phase 2: T008–T013 can run in parallel (different files)
- US1: T016, T017, T018, T019, and T024 can run in parallel once Phase 2 completes
- US2: T025 and T026 can run in parallel; T030 can run in parallel with T027–T029
- US3: T031 and T032 can run in parallel; T033–T037 can be split between service and repository work
- Phase 6: T039–T046 can run in parallel (docs/scripts/tests)

---

## Parallel Examples

### User Story 1

```bash
Task: "Add labeled sample trace fixtures in tests/data/extraction/sample_failure_spans.json"
Task: "Implement Firestore query for processed=false with batch limit in src/extraction/firestore_repository.py"
Task: "Implement few-shot prompt template builder in src/extraction/prompt_templates.py"
```

### User Story 2

```bash
Task: "Add unit tests for FailurePattern schema validation in tests/unit/test_failure_pattern_schema.py"
Task: "Add contract test asserting stored pattern payload matches OpenAPI schema in tests/contract/test_failure_pattern_payload_shape.py"
Task: "Document internal-only access approach in specs/002-extract-failure-patterns/quickstart.md"
```

### User Story 3

```bash
Task: "Add unit tests for truncation and redaction behavior in tests/unit/test_extraction_truncation_and_redaction.py"
Task: "Retry Gemini API failures 3x with exponential backoff in src/extraction/gemini_client.py"
Task: "Persist per-trace error records in src/extraction/firestore_repository.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup)
2. Complete Phase 2 (Foundational)
3. Complete Phase 3 (US1)
4. Validate: run extraction once and confirm patterns are written and inputs marked processed

### Incremental Delivery

1. US1 → working extraction loop
2. US2 → strict schema validation and contract stability
3. US3 → resilience + error recording for production-grade batch processing
