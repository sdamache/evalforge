# Tasks: Eval Test Case Generator

**Input**: Design documents from `specs/004-eval-test-case-generator/`
**Prerequisites**: `specs/004-eval-test-case-generator/plan.md`, `specs/004-eval-test-case-generator/spec.md`, `specs/004-eval-test-case-generator/research.md`, `specs/004-eval-test-case-generator/data-model.md`, `specs/004-eval-test-case-generator/contracts/eval-generator-openapi.yaml`

**Tests**: Minimal mode — **live integration tests only** (no mocks). Tests MUST be skipped unless `RUN_LIVE_TESTS=1`.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the new generator package and configuration hooks.

- [ ] T001 Create eval test generator package skeleton in `src/generators/eval_tests/` (`__init__.py`, `main.py`, `models.py`, `gemini_client.py`, `prompt_templates.py`, `firestore_repository.py`, `eval_test_service.py`)
- [ ] T002 Add eval test generator settings loader in `src/common/config.py` (`EVAL_TEST_BATCH_SIZE`, `EVAL_TEST_PER_SUGGESTION_TIMEOUT_SEC`, `EVAL_TEST_COST_BUDGET_USD_PER_SUGGESTION`, optional `EVAL_TEST_RUN_COST_BUDGET_USD`, optional `EVAL_TEST_MAX_OUTPUT_TOKENS`)
- [ ] T003 [P] Add Firestore collection name helpers in `src/common/firestore.py` for `{prefix}eval_test_runs` and `{prefix}eval_test_errors`
- [ ] T004 [P] Document new env vars in `.env.example` (generator tuning + timeouts + cost budgets)
- [ ] T005 [P] Add local dev wiring in `docker-compose.yml` (new `eval-tests` service on port `8004`) or document why it’s intentionally excluded

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core building blocks shared by all user stories.

- [ ] T006 Define Pydantic models for requests/responses and persistence in `src/generators/eval_tests/models.py` (align to `specs/004-eval-test-case-generator/data-model.md` and `specs/004-eval-test-case-generator/contracts/eval-generator-openapi.yaml`)
- [ ] T007 [P] Add a strict Gemini `response_schema` builder for EvalTestDraft in `src/generators/eval_tests/models.py` (or `src/generators/eval_tests/response_schema.py`)
- [ ] T008 Implement Gemini client wrapper in `src/generators/eval_tests/gemini_client.py` using `google-genai` with `response_mime_type="application/json"`, retries (3x exponential backoff), and prompt/response hashing for audit
- [ ] T009 Implement prompt builder in `src/generators/eval_tests/prompt_templates.py` (rubric-first assertions, optional golden output; include rationale + lineage; enforce “no raw PII” constraints)
- [ ] T010 Implement Firestore repository in `src/generators/eval_tests/firestore_repository.py` (query `Suggestion.type="eval"` using existing indexes from Issue #3, load referenced patterns for canonical selection, write only `suggestion_content.eval_test` (must not modify `Suggestion.status` / `Suggestion.approval_metadata`), persist run summaries + per-suggestion errors)
- [ ] T011 Implement orchestration in `src/generators/eval_tests/eval_test_service.py` (batch selection, per-suggestion timeout, overwrite rules via `edit_source`, idempotency, cost budget enforcement (per-suggestion + per-run), template fallback draft for `needs_human_input` (no Gemini call) when budget exceeded or reproduction context is insufficient, and structured outcomes)

**Checkpoint**: Service core can generate a draft object (in-memory) and persist it to Firestore for a single suggestion.

---

## Phase 3: User Story 1 - Draft eval tests from real failures (Priority: P1) 🎯 MVP

**Goal**: Generate a framework-agnostic eval test draft for eval-type suggestions and store it at `suggestion_content.eval_test`.

**Independent Test**: Create a suggestion + its referenced failure patterns in Firestore, run generation once, and verify the suggestion doc is updated with a valid EvalTestDraft (required fields + rubric assertions).

### Live Integration Test (minimal mode)

- [ ] T012 [P] [US1] Add live smoke test in `tests/integration/test_eval_test_generator_live.py` that:
  creates test FailurePattern + Suggestion docs in Firestore (with cleanup), runs generation (real Gemini call), and asserts `suggestion_content.eval_test` has required fields + rubric assertions, `Suggestion.status` is unchanged, and a missing-context suggestion produces `status="needs_human_input"` with placeholders (no fabricated details)

### Implementation

- [ ] T013 [US1] Implement `POST /eval-tests/run-once` in `src/generators/eval_tests/main.py` (batch generation + run summary per `eval-generator-openapi.yaml`)
- [ ] T014 [US1] Implement canonical source selection + prompt assembly in `src/generators/eval_tests/eval_test_service.py` (highest-confidence pattern, tie: most recent)
- [ ] T015 [US1] Enforce PII redaction/truncation for all stored text in `src/generators/eval_tests/eval_test_service.py` using `src/common/pii.py`
- [ ] T016 [US1] Persist run summaries + per-suggestion errors in `src/generators/eval_tests/firestore_repository.py` with traceable `run_id`

**Checkpoint**: Batch run can generate and persist drafts for a small set of eval-type suggestions.

---

## Phase 4: User Story 2 - Review-ready drafts with clear rationale (Priority: P2)

**Goal**: Make drafts easy to review by ensuring they include rationale + lineage and are safe to regenerate.

**Independent Test**: Generate a draft and verify it includes plain-language rationale and references all contributing sources; verify overwrite is blocked for human-edited drafts unless forced.

### Live Integration Test (minimal mode)

- [ ] T017 [P] [US2] Extend `tests/integration/test_eval_test_generator_live.py` with a live test that:
  verifies `rationale` is non-empty and `source.trace_ids` / `source.pattern_ids` match lineage; sets `edit_source="human"` and confirms regeneration is blocked unless `forceOverwrite=true`

### Implementation

- [ ] T018 [US2] Implement `POST /eval-tests/generate/{suggestionId}` in `src/generators/eval_tests/main.py` (single suggestion generation, overwrite controls, 404/409 handling per contract)
- [ ] T019 [US2] Add overwrite detection + `forceOverwrite` gating in `src/generators/eval_tests/eval_test_service.py` (do not silently discard human edits)
- [ ] T020 [US2] Ensure structured logs include `run_id`, `suggestion_id`, canonical IDs, `prompt_hash`, and decision outcomes in `src/generators/eval_tests/*`

---

## Phase 5: User Story 3 - Safe, reusable artifacts for CI/CD (Priority: P3)

**Goal**: Provide a consistent retrieval surface for the stored JSON draft.

**Independent Test**: After generation, retrieve the draft via the API and confirm it is a valid JSON object with required fields and no raw PII patterns.

### Live Integration Test (minimal mode)

- [ ] T021 [P] [US3] Extend `tests/integration/test_eval_test_generator_live.py` with a live test that:
  calls `GET /eval-tests/{suggestionId}`, validates response shape (includes `suggestion_status` + optional `approval_metadata` + `eval_test`), and runs a basic PII regex check (email/phone) over stored text fields

### Implementation

- [ ] T022 [US3] Implement `GET /eval-tests/{suggestionId}` in `src/generators/eval_tests/main.py` to return `EvalTestArtifactResponse` (draft + `suggestion_status` + optional `approval_metadata.timestamp`) (404 if missing suggestion or missing draft)
- [ ] T023 [US3] Add `GET /health` in `src/generators/eval_tests/main.py` (include last run info where available, similar to other services)

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T024 [P] Update `README.md` with the new generator service (`python -m src.generators.eval_tests.main`, port `8004`, and example curl)
- [ ] T025 [P] Add a short operator note to `specs/004-eval-test-case-generator/quickstart.md` for common failure modes (429/quota, missing patterns, overwrite blocked)

---

## Dependencies & Execution Order

- **Setup (Phase 1)**: Start immediately.
- **Foundational (Phase 2)**: Blocks all user story work.
- **User Story 1 (P1)**: Depends on Phase 2.
- **User Story 2 (P2)**: Depends on US1 draft shape + overwrite rules.
- **User Story 3 (P3)**: Depends on storage + API retrieval.

## Parallel Opportunities

- Phase 1 tasks marked [P] can be done in parallel.
- Phase 2 tasks: models/schema work can proceed in parallel with prompt/client/repository scaffolding.
- Integration tests can be written in parallel with implementation as long as they remain live-only and clean up Firestore state.
