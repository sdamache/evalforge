# Tasks: Runbook Draft Generator

**Input**: Design documents from `/specs/006-runbook-generation/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/
**Test Mode**: Minimal (LIVE tests only - no mocks)
**Code Reuse**: 80%+ from eval_tests module

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Module Structure)

**Purpose**: Create runbooks module directory structure mirroring eval_tests

- [ ] T001 Create runbooks module directory at src/generators/runbooks/
- [ ] T002 Create __init__.py with module exports in src/generators/runbooks/__init__.py

**Checkpoint**: Module structure ready for implementation

---

## Phase 2: Foundational (Core Models & Shared Components)

**Purpose**: Core models and utilities that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T003 [P] Copy models.py from eval_tests and adapt for RunbookDraft in src/generators/runbooks/models.py
  - Replace EvalTestDraft with RunbookDraft:
    - Add `rationale` field (plain-language reasoning citing source trace) for Demo-Ready Transparency
    - Add `markdown_content`, `symptoms`, `diagnosis_commands`, `mitigation_steps`, `escalation_criteria`
  - Replace EvalTestDraftSource with RunbookDraftSource (FR-007 lineage: trace_ids, pattern_ids, canonical sources)
  - Replace EvalTestRunSummary with RunbookRunSummary (FR-008 observability: run summaries with counts/timing)
  - Replace EvalTestError with RunbookError (FR-008 observability: per-suggestion error tracking)
  - Add get_runbook_draft_response_schema() function with rationale in required fields
  - Keep TriggeredBy, EditSource, error types unchanged

- [ ] T004 [P] Copy gemini_client.py from eval_tests and adapt for runbook schema in src/generators/runbooks/gemini_client.py
  - Change import from models to use get_runbook_draft_response_schema
  - Rename method generate_eval_test_draft to generate_runbook_draft
  - Update docstrings for runbook context

- [ ] T005 [P] Create prompt_templates.py with SRE runbook-specific prompts in src/generators/runbooks/prompt_templates.py
  - Implement build_runbook_generation_prompt() function
  - Include explicit Markdown section markers (Summary, Symptoms, Diagnosis, Mitigation, Root Cause Fix, Escalation)
  - Include failure-type-specific diagnostic command suggestions
  - Require minimum 2 specific commands in Diagnosis section
  - Generate `rationale` field explaining why runbook was created, citing source trace ID (Demo-Ready Transparency)

- [ ] T006 [P] Copy firestore_repository.py from eval_tests and adapt for runbooks in src/generators/runbooks/firestore_repository.py
  - Add runbook_runs_collection() and runbook_errors_collection() helper functions to src/common/firestore.py
  - Change query filter from type="eval" to type="runbook"
  - Change write target from suggestion_content.eval_test to suggestion_content.runbook_snippet
  - Rename methods: write_eval_test_draft → write_runbook_draft, etc.
  - Update collection references for runbook_runs and runbook_errors

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Batch Runbook Generation (Priority: P1) 🎯 MVP

**Goal**: Enable batch generation of runbook drafts for pending suggestions via POST /runbooks/run-once

**Independent Test**: Call POST /runbooks/run-once with test suggestions and verify runbook drafts appear in Firestore

### Implementation for User Story 1

- [ ] T007 [US1] Copy runbook_service.py from eval_test_service.py and adapt for runbooks in src/generators/runbooks/runbook_service.py
  - Change class name EvalTestService → RunbookService
  - Import from runbooks.models, runbooks.gemini_client, runbooks.prompt_templates, runbooks.firestore_repository
  - Change prompt building to use build_runbook_generation_prompt()
  - Update _compose_draft() to create RunbookDraft with markdown_content and structured fields
  - Update _template_needs_human_input() for runbook template fallback
  - Update _sanitize_inputs() to include runbook-relevant fields
  - Keep identical: batch processing, cost budgeting, timeout handling, error recording

- [ ] T008 [US1] Copy main.py from eval_tests and adapt endpoints for runbooks in src/generators/runbooks/main.py
  - Change endpoint prefix from /eval-tests to /runbooks
  - Import from runbooks module instead of eval_tests
  - Implement POST /runbooks/run-once endpoint
  - Update health endpoint to show pending runbook suggestions count
  - Change service initialization to use RunbookService

- [ ] T009 [US1] Add configuration for runbook generator in src/common/config.py
  - Add RunbookGeneratorSettings dataclass (mirroring EvalTestGeneratorSettings)
  - Add load_runbook_generator_settings() function
  - Add RUNBOOK_BATCH_SIZE, RUNBOOK_PER_SUGGESTION_TIMEOUT_SEC, RUNBOOK_COST_BUDGET_USD_PER_SUGGESTION env vars

**Checkpoint**: User Story 1 complete - batch generation functional

---

## Phase 4: User Story 2 - Single Runbook Generation (Priority: P2)

**Goal**: Enable on-demand generation for a specific suggestion via POST /runbooks/generate/{id}

**Independent Test**: Call POST /runbooks/generate/{id} and verify the specific suggestion is updated

### Implementation for User Story 2

- [ ] T010 [US2] Implement POST /runbooks/generate/{suggestionId} endpoint in src/generators/runbooks/main.py
  - Add generate_single_runbook() route handler
  - Support dryRun, forceOverwrite, triggeredBy parameters
  - Return 409 Conflict when edit_source="human" and forceOverwrite=false
  - Return 404 when suggestion not found

- [ ] T011 [US2] Implement generate_one() method in RunbookService in src/generators/runbooks/runbook_service.py
  - Add single-suggestion generation flow
  - Implement forceOverwrite logic to override human edits
  - Return appropriate error codes for conflict scenarios

**Checkpoint**: User Stories 1 AND 2 complete - batch and single generation functional

---

## Phase 5: User Story 3 - Runbook Retrieval (Priority: P3)

**Goal**: Enable retrieval of runbook drafts for review via GET /runbooks/{id}

**Independent Test**: Call GET /runbooks/{id} after generation and verify complete response structure

### Implementation for User Story 3

- [ ] T012 [US3] Implement GET /runbooks/{suggestionId} endpoint in src/generators/runbooks/main.py
  - Add get_runbook() route handler
  - Return RunbookArtifactResponse with suggestion_status, approval_metadata, and runbook
  - Return 404 when suggestion or runbook not found

- [ ] T013 [US3] Add get_runbook_artifact() method to FirestoreRepository in src/generators/runbooks/firestore_repository.py
  - Fetch suggestion and extract runbook_snippet
  - Include approval_metadata in response

**Checkpoint**: All user stories complete - full API functional

---

## Phase 6: Live Integration Test

**Purpose**: Single live smoke test covering all user stories (minimal test mode)

- [ ] T014 [P] Create live integration test in tests/integration/test_runbook_generator_live.py
  - Test requires RUN_LIVE_TESTS=1 environment variable
  - Create test runbook-type suggestion in Firestore with reproduction context
  - Test batch generation via POST /runbooks/run-once
  - Verify runbook draft is embedded on suggestion with all 6 Markdown sections
  - Test single generation via POST /runbooks/generate/{id}
  - Test retrieval via GET /runbooks/{id}
  - Test human edit protection (409 Conflict without forceOverwrite)
  - Test forceOverwrite=true regenerates human-edited runbook
  - Clean up test documents in finally block

**Checkpoint**: Live test validates real Gemini and Firestore integration

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final cleanup and validation

- [ ] T015 [P] Update CLAUDE.md with runbook generator documentation
- [ ] T016 Validate quickstart.md instructions work end-to-end
- [ ] T017 Run all live integration tests and verify passing

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-5)**: All depend on Foundational phase completion
  - US1 (batch) can start after Phase 2
  - US2 (single) depends on US1 completion (shares service methods)
  - US3 (retrieval) can start after Phase 2 (parallel with US1/US2)
- **Live Test (Phase 6)**: Depends on all user stories being complete
- **Polish (Phase 7)**: Depends on Phase 6 passing

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2)
- **User Story 2 (P2)**: Depends on US1 (extends RunbookService with generate_one)
- **User Story 3 (P3)**: Can start after Foundational (parallel with US1)

### Within Each Phase

- Models before services
- Services before endpoints
- All [P] tasks can run in parallel

### Parallel Opportunities

- T003, T004, T005, T006 can all run in parallel (Phase 2)
- T012, T013 can run in parallel with US1/US2 (Phase 5)

---

## Parallel Example: Foundational Phase

```bash
# Launch all foundational tasks together:
Task: "T003 - Copy models.py and adapt for RunbookDraft"
Task: "T004 - Copy gemini_client.py and adapt for runbook schema"
Task: "T005 - Create prompt_templates.py with SRE prompts"
Task: "T006 - Copy firestore_repository.py and adapt for runbooks"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T002)
2. Complete Phase 2: Foundational (T003-T006)
3. Complete Phase 3: User Story 1 (T007-T009)
4. **STOP and VALIDATE**: Test batch generation via curl
5. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test batch generation → MVP!
3. Add User Story 2 → Test single generation
4. Add User Story 3 → Test retrieval
5. Add Live Test → Validate integration
6. Polish → Final cleanup

---

## Summary

| Phase | Tasks | Purpose |
|-------|-------|---------|
| Phase 1: Setup | 2 | Module structure |
| Phase 2: Foundational | 4 | Models, client, prompts, repository |
| Phase 3: US1 Batch | 3 | Core batch generation |
| Phase 4: US2 Single | 2 | On-demand generation |
| Phase 5: US3 Retrieval | 2 | Read access for review |
| Phase 6: Live Test | 1 | Integration validation |
| Phase 7: Polish | 3 | Final cleanup |
| **Total** | **17** | |

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- **Test Mode: Minimal** - Only 1 live integration test, NO mocked unit tests
- **Code Reuse**: Most tasks are copy-and-adapt from eval_tests
- Commit after each task or logical group
- Stop at any checkpoint to validate independently
