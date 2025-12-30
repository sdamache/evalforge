# Implementation Plan: Runbook Draft Generator

**Branch**: `006-runbook-generation` | **Date**: 2025-12-30 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/006-runbook-generation/spec.md`
**Blueprint**: Follows 004-eval-test-case-generator with maximum code reuse

## Summary

Transform approved failure patterns into operational runbook entries with incident response procedures, troubleshooting steps, and escalation paths. The generator embeds RunbookDraft on Suggestion documents at `suggestion_content.runbook_snippet`, following the identical architecture pattern as the eval test generator with 80%+ code reuse.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: FastAPI, google-genai, google-cloud-firestore, pydantic, tenacity
**Storage**: Firestore `evalforge_suggestions` collection (embedded at `suggestion_content.runbook_snippet`)
**Testing**: pytest with RUN_LIVE_TESTS=1 (LIVE tests only, no mocks)
**Target Platform**: Google Cloud Run (serverless)
**Project Type**: Single project - extends existing `src/generators/` module
**Performance Goals**: 20 suggestions in <5 minutes batch processing
**Constraints**: <30s per suggestion, cost budget $0.10/suggestion with template fallback
**Scale/Scope**: Same as eval generator - batch sizes up to 200

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| **Observability-First Insight Trail** | ✅ PASS | FR-007/FR-008: Track lineage (trace_ids, pattern_ids), record run summaries and errors with structured logging |
| **Human-Governed Fail-Safe Loops** | ✅ PASS | FR-003: Generator NEVER modifies Suggestion.status or approval_metadata; FR-004: Protect human edits |
| **Cost-Conscious Experimentation** | ✅ PASS | FR-009: Cost budgeting with template fallback when exceeded; reuse existing GeminiConfig |
| **Reliability & Cognitive Ease** | ✅ PASS | Edge cases: 3x retry with backoff; FR-001: Standard SRE format executable in <5 min; FR-006: Specific commands |
| **Demo-Ready Transparency & UX** | ✅ PASS | Runbooks include reasoning via rationale field; Markdown format for immediate use |
| **Platform Constraints** | ✅ PASS | Cloud Run serverless; Vertex AI Gemini only; PII stripped (FR-005); Secrets from Secret Manager |
| **Workflow & Quality Gates** | ✅ PASS | Live integration tests only (minimal test mode); follows $0.10/test budget |

**Gate Result**: ✅ ALL GATES PASS - Proceed to Phase 0

## Project Structure

### Documentation (this feature)

```text
specs/006-runbook-generation/
├── spec.md              # Feature specification (complete)
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (OpenAPI)
│   └── runbook-generator-openapi.yaml
├── checklists/          # Quality checklists
│   └── requirements.md
└── tasks.md             # Phase 2 output (speckit.tasks)
```

### Source Code (repository root)

```text
src/generators/
├── eval_tests/          # EXISTING - Blueprint for reuse
│   ├── __init__.py
│   ├── main.py
│   ├── models.py
│   ├── prompt_templates.py
│   ├── gemini_client.py
│   ├── firestore_repository.py
│   └── eval_test_service.py
│
└── runbooks/            # NEW - Mirror eval_tests structure
    ├── __init__.py
    ├── main.py                    # Copy from eval_tests, change to /runbooks endpoints
    ├── models.py                  # Copy from eval_tests, replace EvalTestDraft with RunbookDraft
    ├── prompt_templates.py        # NEW - SRE runbook-specific Markdown prompt
    ├── gemini_client.py           # Copy from eval_tests, change response_schema
    ├── firestore_repository.py    # Copy from eval_tests, query type="runbook", write to runbook_snippet
    └── runbook_service.py         # Copy from eval_tests, use runbook prompt template

tests/
├── integration/
│   └── test_runbook_generator_live.py  # LIVE tests only (RUN_LIVE_TESTS=1)
└── [no unit/ tests - minimal test mode]
```

**Structure Decision**: Extend existing `src/generators/` module with new `runbooks/` subpackage mirroring `eval_tests/` structure for maximum code reuse.

## Code Reuse Matrix

| Source File | Target File | Reuse Level | Changes Required |
|-------------|-------------|-------------|------------------|
| `eval_tests/models.py` | `runbooks/models.py` | 70% Copy | Replace EvalTestDraft→RunbookDraft; keep TriggeredBy, EditSource, error types |
| `eval_tests/gemini_client.py` | `runbooks/gemini_client.py` | 95% Copy | Change `get_eval_test_draft_response_schema` → `get_runbook_draft_response_schema` |
| `eval_tests/firestore_repository.py` | `runbooks/firestore_repository.py` | 90% Copy | Change type filter `"eval"` → `"runbook"`; write to `runbook_snippet` |
| `eval_tests/eval_test_service.py` | `runbooks/runbook_service.py` | 85% Copy | Use runbook prompt template; same orchestration logic |
| `eval_tests/main.py` | `runbooks/main.py` | 95% Copy | Change endpoint prefix `/eval-tests` → `/runbooks` |
| `eval_tests/prompt_templates.py` | `runbooks/prompt_templates.py` | 0% New | SRE-specific Markdown runbook prompt (only truly new file) |

**Estimated New Code**: ~150 lines (prompt_templates.py only)
**Estimated Copied/Adapted Code**: ~1200 lines

## Deferred Decisions

| Decision | Rationale | Revisit When |
|----------|-----------|--------------|
| Shared base generator module | Would reduce duplication further but adds abstraction complexity | Post-hackathon refactoring |
| Runbook-to-eval cross-linking | FR out of scope; could add `related_artifacts` field | Future feature request |
| Temperature tuning for Markdown | Using same 0.2-0.4 as eval; may need adjustment | After SRE review of samples |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Gemini generates poor Markdown structure | Low | Medium | Structured prompt with explicit template; template fallback |
| Copy-paste introduces subtle bugs | Medium | Low | Live integration tests catch real behavior |
| Runbook content too generic | Medium | Medium | Specific diagnosis commands required (FR-006); SRE review |

## Implementation Phases

### Phase 0: Research (Complete - see research.md)
- Confirm reuse strategy viability
- Validate Markdown generation approach with Gemini

### Phase 1: Design (Complete - see data-model.md, contracts/)
- Define RunbookDraft schema
- Define API contracts

### Phase 2: Tasks (Next - speckit.tasks)
- Generate implementation tasks from this plan
