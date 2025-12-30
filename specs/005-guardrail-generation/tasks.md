# Tasks: Guardrail Suggestion Engine

**Input**: Design documents from `/specs/005-guardrail-generation/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: LIVE integration tests only (minimal mode) - no mocks, no unit tests
**Organization**: Tasks grouped by user story for independent implementation

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create guardrails module structure by copying from eval_tests

- [x] T001 Create guardrails package directory at src/generators/guardrails/
- [x] T002 [P] Create __init__.py with package docstring in src/generators/guardrails/__init__.py
- [x] T003 [P] Add PyYAML to project dependencies in pyproject.toml (for YAML export)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core models, types, and infrastructure that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T004 Create guardrail_types.py with GUARDRAIL_MAPPING dict (failure_type → guardrail_type) in src/generators/guardrails/guardrail_types.py
- [x] T005 [P] Create models.py by copying from eval_tests/models.py and adapting:
  - Replace EvalTestDraft with GuardrailDraft
  - Replace EvalTestDraftSource with GuardrailDraftSource
  - Replace EvalTestDraftGeneratorMeta with GuardrailDraftGeneratorMeta
  - Add GuardrailType enum (validation_rule, rate_limit, etc.)
  - Add configuration dataclasses (RateLimitConfig, ContentFilterConfig, etc.)
  - Keep TriggeredBy, EditSource, error types, RunSummary pattern
  - File: src/generators/guardrails/models.py
- [x] T006 [P] Create gemini_client.py by copying from eval_tests/gemini_client.py and adapting:
  - Change response_schema to GuardrailDraft schema
  - Keep retry/hashing logic, tenacity decorators
  - File: src/generators/guardrails/gemini_client.py
- [x] T007 Create prompt_templates.py with guardrail-specific prompt builder in src/generators/guardrails/prompt_templates.py:
  - Include failure type and guardrail type hint
  - Include example configurations for each guardrail type
  - Enforce JSON output via response_mime_type
  - Include PII constraints in prompt

**Checkpoint**: Foundation ready - models, types, Gemini client, prompts available

---

## Phase 3: User Story 1 - Generate Guardrail Rules from Failure Patterns (Priority: P1) 🎯 MVP

**Goal**: Generate guardrail drafts for guardrail-type suggestions using Gemini, storing results in `suggestion_content.guardrail`

**Independent Test**: Create 5 guardrail-type suggestions (hallucination, runaway_loop, pii_leak, stale_data, prompt_injection) and verify each receives a complete guardrail draft with specific rule configuration within 30 seconds

### Live Integration Test for User Story 1

- [x] T008 [US1] Create live integration test file at tests/integration/test_guardrail_generator_live.py:
  - Guard with `RUN_LIVE_TESTS=1` environment check (skip if not set)
  - Create test fixtures: `_create_suggestion_doc()`, `_create_failure_pattern_doc()`
  - Use unique collection prefix for test isolation
  - Add cleanup after each test
  - Test: `test_run_once_generates_guardrail_drafts()` - batch generation for multiple failure types
  - Test: `test_failure_type_to_guardrail_type_mapping()` - verify hallucination→validation_rule, runaway_loop→rate_limit
  - Test: `test_insufficient_context_returns_needs_human_input()` - verify suggestions with minimal context produce `needs_human_input` status (edge case coverage)

### Implementation for User Story 1

- [x] T009 [US1] Create firestore_repository.py by copying from eval_tests/firestore_repository.py and adapting:
  - Query `type=="guardrail"` instead of `type=="eval"`
  - Write to `suggestion_content.guardrail` instead of `suggestion_content.eval_test`
  - Use collections: `guardrail_runs`, `guardrail_errors`
  - Load failure patterns for canonical source selection
  - File: src/generators/guardrails/firestore_repository.py
- [x] T010 [US1] Create guardrail_service.py by copying from eval_tests/eval_test_service.py and adapting:
  - Use guardrail prompt template
  - Add failure-type-to-guardrail-type mapping lookup
  - Implement canonical source selection (highest confidence, tie-breaker: most recent)
  - Implement cost budget enforcement with template fallback
  - Implement overwrite protection (edit_source flag)
  - File: src/generators/guardrails/guardrail_service.py
- [x] T011 [US1] Add template fallback method `_template_needs_human_input()` to guardrail_service.py:
  - Generate `needs_human_input` draft when Gemini unavailable or context insufficient
  - Include placeholder configuration based on guardrail type
  - Document reason for fallback in generator_meta
- [x] T012 [US1] Create main.py FastAPI service by copying from eval_tests/main.py and adapting:
  - Change endpoint prefix to `/guardrails`
  - POST /guardrails/run-once (batch generation)
  - POST /guardrails/generate/{suggestionId} (single generation)
  - File: src/generators/guardrails/main.py

**Checkpoint**: User Story 1 complete - batch guardrail generation works end-to-end

---

## Phase 4: User Story 2 - Review-Ready Drafts with Actionable Configuration (Priority: P2)

**Goal**: Ensure each guardrail draft includes plain-language justification and concrete configuration values for reviewer approval

**Independent Test**: Verify reviewers can inspect guardrail drafts, understand what they block and why, with specific threshold/limit values visible

### Live Integration Test for User Story 2

- [x] T013 [US2] Add live test `test_generated_draft_has_justification_and_config()` to tests/integration/test_guardrail_generator_live.py:
  - Verify `justification` field is non-empty and explains prevention mechanism
  - Verify `configuration` has concrete values (not placeholders)
  - Verify `description` explains what the guardrail prevents
  - For rate_limit type: verify `max_calls`, `window_seconds`, `action` present

### Implementation for User Story 2

- [x] T014 [US2] Enhance prompt_templates.py to emphasize concrete configuration values:
  - Add explicit instruction: "Generate specific thresholds, limits, and conditions - not placeholders"
  - Include example configurations with actual values for each guardrail type
  - Add instruction for plain-language justification
- [x] T015 [US2] Add validation in guardrail_service.py to reject drafts with placeholder values:
  - Validate configuration against type-specific schemas
  - Reject generic text like "add appropriate validation"
  - Set status to `needs_human_input` if configuration incomplete
- [x] T016 [US2] Add GET /guardrails/{suggestionId} endpoint to main.py:
  - Return guardrail draft with suggestion_status and approval_metadata
  - Include lineage (trace_ids, pattern_ids, canonical sources)
  - Enable reviewers to see full context for approval decision

**Checkpoint**: User Story 2 complete - reviewers can approve/reject with actionable information

---

## Phase 5: User Story 3 - Consistent Output Format for Deployment Tooling (Priority: P3)

**Goal**: Store guardrail drafts in JSON format with YAML export capability for Datadog AI Guard compatibility

**Independent Test**: Export approved guardrail draft in both JSON and YAML formats, verify YAML structure matches Datadog AI Guard expectations

### Live Integration Test for User Story 3

- [x] T017 [US3] Add live test `test_yaml_export_format()` to tests/integration/test_guardrail_generator_live.py:
  - Generate a guardrail draft
  - Request with `?format=yaml` query param
  - Verify YAML output is valid
  - Verify structure includes rule_name, guardrail_type, configuration, description

### Implementation for User Story 3

- [x] T018 [US3] Add YAML export support to GET /guardrails/{suggestionId} endpoint in main.py:
  - Accept `format` query parameter (json | yaml, default: json)
  - Use PyYAML to convert GuardrailDraft to YAML
  - Set appropriate Content-Type header (application/json or application/x-yaml)
- [x] T019 [US3] Create yaml_export.py utility for Datadog AI Guard compatible output in src/generators/guardrails/yaml_export.py:
  - Convert GuardrailDraft to Datadog-compatible YAML structure
  - Include rule_name, type, configuration, description
  - Exclude internal metadata (generator_meta, source)

**Checkpoint**: User Story 3 complete - guardrails exportable in JSON and YAML

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect all user stories

- [x] T020 [P] Add /health endpoint to main.py with backlog count and last run info:
  - Query pending guardrail suggestion count
  - Query last guardrail_run for status info
  - Include config summary (model, batch_size, cost budget)
- [x] T021 [P] Add structured logging throughout guardrail_service.py:
  - Log run_id, suggestion_id, failure_type, guardrail_type, prompt_hash
  - Log generation outcomes (generated, skipped, error)
  - Log cost/budget information when available
- [x] T022 Validate implementation against quickstart.md scenarios:
  - Test health check endpoint
  - Test batch generation with curl
  - Test single suggestion generation
  - Test YAML export
- [x] T023 Update CLAUDE.md with guardrail generator commands and module info

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup - BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational - MVP delivery
- **User Story 2 (Phase 4)**: Depends on User Story 1 (enhances drafts)
- **User Story 3 (Phase 5)**: Depends on User Story 1 (adds export)
- **Polish (Phase 6)**: Depends on all user stories

### User Story Dependencies

- **User Story 1 (P1)**: Depends on Foundational only - core generation
- **User Story 2 (P2)**: Depends on US1 - enhances generated content
- **User Story 3 (P3)**: Depends on US1 - adds export capability

### Within Each Phase

- Models/types before services
- Services before endpoints
- Core implementation before tests (live tests validate real behavior)
- Complete each phase before moving to next

### Parallel Opportunities

**Phase 1 (Setup)**:
```bash
# All [P] tasks can run in parallel
T002: Create __init__.py
T003: Add PyYAML dependency
```

**Phase 2 (Foundational)**:
```bash
# After T004 (guardrail_types.py), these can run in parallel:
T005: Create models.py (depends on T004 for GuardrailType)
T006: Create gemini_client.py (depends on T005 for schema)
T007: Create prompt_templates.py (depends on T004 for type mapping)
```

**User Stories**:
```bash
# US2 and US3 can start in parallel once US1 core is complete
# US2 focuses on content quality
# US3 focuses on export format
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (3 tasks)
2. Complete Phase 2: Foundational (4 tasks)
3. Complete Phase 3: User Story 1 (5 tasks)
4. **STOP and VALIDATE**: Run live integration test
5. Deploy/demo if ready - guardrails generate correctly

### Incremental Delivery

1. Setup + Foundational → Foundation ready (7 tasks)
2. User Story 1 → Test with live Gemini + Firestore → Deploy MVP (5 tasks)
3. User Story 2 → Verify draft quality → Deploy (4 tasks)
4. User Story 3 → Test YAML export → Deploy (3 tasks)
5. Polish → Final validation (4 tasks)

### Code Reuse Summary

| Task | Source | Adaptation Required |
|------|--------|---------------------|
| T005 models.py | eval_tests/models.py | Replace EvalTestDraft with GuardrailDraft |
| T006 gemini_client.py | eval_tests/gemini_client.py | Change response_schema |
| T009 firestore_repository.py | eval_tests/firestore_repository.py | Query type="guardrail", new collections |
| T010 guardrail_service.py | eval_tests/eval_test_service.py | Add failure type mapping |
| T012 main.py | eval_tests/main.py | Change endpoint prefix |

---

## Notes

- Testing: LIVE integration tests only (RUN_LIVE_TESTS=1) - no mocks
- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story
- Each user story is independently testable
- Commit after each task or logical group
- Stop at any checkpoint to validate progress
