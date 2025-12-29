# Tasks: Suggestion Storage and Deduplication

**Input**: Design documents from `/specs/003-suggestion-deduplication/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Test Mode**: minimal (LIVE infrastructure tests only - NO mocked tests)

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and deduplication module structure

- [x] T001 Create deduplication module directory structure at src/deduplication/
- [x] T002 Create src/deduplication/__init__.py with module exports
- [x] T003 [P] Add deduplication config settings to src/common/config.py (SIMILARITY_THRESHOLD, EMBEDDING_MODEL, DEDUP_BATCH_SIZE)
- [x] T004 [P] Add suggestions_collection() helper to src/common/firestore.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 Create Suggestion and StatusHistoryEntry Pydantic models in src/deduplication/models.py per data-model.md
- [x] T006 Create SuggestionType, SuggestionStatus enums in src/deduplication/models.py (reuse Severity, FailureType from extraction)
- [x] T007 [P] Implement cosine_similarity() and find_best_match() functions in src/deduplication/similarity.py per research.md
- [x] T008 Implement EmbeddingClient class with get_embedding(), get_embeddings_batch(), and in-memory cache lookup in src/deduplication/embedding_client.py (FR-007: cache embeddings to avoid redundant computation)
- [x] T009 Add exponential backoff retry logic (tenacity) to EmbeddingClient for rate limit handling (FR-017, FR-018)
- [x] T010 Create SuggestionRepository class with CRUD operations in src/deduplication/firestore_repository.py
- [x] T011 Implement get_pending_patterns() query in src/deduplication/firestore_repository.py (patterns with processed=false)
- [x] T012 Implement mark_pattern_processed() update in src/deduplication/firestore_repository.py

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Pattern Deduplication on Ingestion (Priority: P1) 🎯 MVP

**Goal**: Automatically check if similar suggestion exists and merge (>85% similarity) or create new suggestion with pending status

**Independent Test**: Submit 10 similar failure patterns, verify 1-2 suggestions created (not 10)

### Live Integration Test for User Story 1

- [x] T013 [US1] Create live integration test in tests/integration/test_deduplication_live.py that hits real Vertex AI and Firestore

### Implementation for User Story 1

- [x] T014 [US1] Implement DeduplicationService class in src/deduplication/deduplication_service.py with process_batch() method
- [x] T015 [US1] Implement _generate_embedding_text() helper to combine failure_type + trigger_condition in src/deduplication/deduplication_service.py
- [x] T016 [US1] Implement _find_or_create_suggestion() logic in src/deduplication/deduplication_service.py (FR-001, FR-002, FR-003)
- [x] T017 [US1] Implement merge_into_suggestion() in SuggestionRepository for adding trace to existing suggestion (FR-012)
- [x] T018 [US1] Implement create_suggestion() in SuggestionRepository for new suggestions with pending status
- [x] T019 [US1] Add structured logging for merge decisions (pattern_id, suggestion_id, similarity_score, outcome) per FR-013
- [x] T020 [US1] Add processing metrics logging (patterns_processed, merge_rate, avg_similarity, duration) per FR-014
- [x] T021 [US1] Create FastAPI service in src/deduplication/main.py with /health endpoint
- [x] T022 [US1] Add POST /dedup/run-once endpoint in src/deduplication/main.py per OpenAPI contract
- [x] T023 [US1] Implement DeduplicationRunSummary response model per contracts/deduplication-openapi.yaml

**Checkpoint**: User Story 1 complete - deduplication of patterns into suggestions works end-to-end

---

## Phase 4: User Story 2 - Suggestion Lineage Tracking (Priority: P2)

**Goal**: Display all contributing trace IDs with timestamps when viewing suggestion details

**Independent Test**: Create suggestion from 5 traces, query suggestion, verify all 5 trace IDs visible with timestamps

### Live Integration Test for User Story 2

- [x] T024 [US2] Add lineage tracking test to tests/integration/test_deduplication_live.py (verify source_traces populated correctly)

### Implementation for User Story 2

- [x] T025 [P] [US2] Create SourceTraceEntry model in src/deduplication/models.py per data-model.md
- [x] T026 [US2] Ensure merge_into_suggestion() appends to source_traces array with timestamp and similarity_score
- [x] T027 [US2] Add GET /suggestions/{suggestionId} endpoint in src/deduplication/main.py to return full lineage
- [x] T028 [US2] Add GET /suggestions endpoint with pagination in src/deduplication/main.py per OpenAPI contract

**Checkpoint**: User Story 2 complete - lineage visible for all suggestions

---

## Phase 5: User Story 3 - Audit Trail for Status Changes (Priority: P2)

**Goal**: Record every status transition (pending→approved, pending→rejected) with timestamp, actor, and notes

**Independent Test**: Change suggestion status multiple times, verify each transition recorded with full audit data

### Live Integration Test for User Story 3

- [x] T029 [US3] Add audit trail test to tests/integration/test_deduplication_live.py (verify version_history populated)

### Implementation for User Story 3

- [x] T030 [P] [US3] Ensure StatusHistoryEntry model has previous_status, new_status, actor, timestamp, notes fields
- [x] T031 [US3] Implement update_suggestion_status() in SuggestionRepository that appends to version_history (FR-005)
- [x] T032 [US3] Add PATCH /suggestions/{suggestionId}/status endpoint for approval/rejection in src/deduplication/main.py
- [x] T033 [US3] Validate status transitions (only pending→approved or pending→rejected allowed) per FR-011

**Checkpoint**: User Story 3 complete - full audit trail for all status changes

---

## Phase 6: User Story 4 - Efficient Dashboard Queries (Priority: P3)

**Goal**: Support efficient querying by status, type, severity with <2 second response for 1000+ suggestions

**Independent Test**: Populate 1000+ suggestions, measure query response time, verify <2 seconds

### Live Integration Test for User Story 4

- [ ] T034 [US4] Add query performance test to tests/integration/test_deduplication_live.py (verify <2s with 100+ suggestions)

### Implementation for User Story 4

- [ ] T035 [US4] Add query filters to GET /suggestions endpoint (status, type, severity parameters) per OpenAPI contract
- [ ] T036 [US4] Implement list_suggestions() with filters in SuggestionRepository using composite queries
- [ ] T037 [US4] Create Firestore composite indexes file at firestore.indexes.json per data-model.md
- [ ] T038 [US4] Add cursor-based pagination to list_suggestions() for efficient large result handling

**Checkpoint**: User Story 4 complete - dashboard queries perform at scale

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T039 [P] Add contract schema validation test in tests/contract/test_deduplication_contracts.py
- [ ] T040 [P] Validate Suggestion model serialization matches OpenAPI schema in tests/contract/test_deduplication_contracts.py
- [ ] T041 Update quickstart.md with actual test commands and verification steps
- [ ] T042 Add deduplication service to docker-compose.yml
- [ ] T043 Run full test suite and fix any issues: RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_deduplication_live.py -v

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-6)**: All depend on Foundational phase completion
  - User stories can proceed in priority order (P1 → P2 → P2 → P3)
  - Or in parallel if team capacity allows
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational - No dependencies on other stories - **MVP**
- **User Story 2 (P2)**: Can start after Foundational - Builds on US1 merge logic but independently testable
- **User Story 3 (P2)**: Can start after Foundational - Independent of US1/US2
- **User Story 4 (P3)**: Can start after Foundational - Needs data from US1 but query logic is independent

### Within Each User Story

- Live integration test written alongside implementation (not strict TDD due to minimal mode)
- Models before services
- Services before endpoints
- Core implementation before integration
- Story complete before moving to next priority

### Parallel Opportunities

- Setup tasks T003, T004 can run in parallel
- Foundational tasks T007 can run in parallel with other Phase 2 tasks
- Once Foundational completes, US3 can run in parallel with US1/US2 (independent logic)
- All contract tests in Phase 7 can run in parallel

---

## Parallel Example: Phase 2 Foundational

```bash
# After T006 completes, these can run in parallel:
Task: "T007 [P] Implement cosine_similarity() in src/deduplication/similarity.py"
Task: "T008 Implement EmbeddingClient in src/deduplication/embedding_client.py"
```

## Parallel Example: Contract Tests

```bash
# All contract tests can run together:
Task: "T039 [P] Add contract schema validation in tests/contract/test_deduplication_contracts.py"
Task: "T040 [P] Validate Suggestion model serialization in tests/contract/test_deduplication_contracts.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Run live integration test
5. Deploy/demo if ready - **Core deduplication works!**

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test with live Vertex AI + Firestore → Deploy/Demo (MVP!)
3. Add User Story 2 → Lineage visible → Deploy/Demo
4. Add User Story 3 → Audit trails complete → Deploy/Demo
5. Add User Story 4 → Dashboard-ready → Deploy/Demo

### Test Mode: Minimal

**IMPORTANT**: This feature uses minimal test mode per constitution:
- Only LIVE integration tests that hit real Vertex AI and Firestore
- NO mocked tests (@patch, @mock, unittest.mock)
- NO unit tests in tests/unit/
- Contract tests validate schema only, no service mocking
- Run with: `RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/ -v`

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- All tests hit REAL services (Vertex AI, Firestore) - no mocks
- **Manual Validation Metrics**: SC-005 (5x faster review) and SC-006 (>99% merge accuracy) require spot-check validation after implementation, not automated tests

---

## Summary

| Phase | Tasks | Purpose |
|-------|-------|---------|
| Phase 1: Setup | T001-T004 (4) | Module structure and config |
| Phase 2: Foundational | T005-T012 (8) | Core models, embedding, repository |
| Phase 3: User Story 1 | T013-T023 (11) | Pattern deduplication (MVP) |
| Phase 4: User Story 2 | T024-T028 (5) | Lineage tracking |
| Phase 5: User Story 3 | T029-T033 (5) | Audit trails |
| Phase 6: User Story 4 | T034-T038 (5) | Dashboard queries |
| Phase 7: Polish | T039-T043 (5) | Contract tests, validation |
| **Total** | **43 tasks** | |
