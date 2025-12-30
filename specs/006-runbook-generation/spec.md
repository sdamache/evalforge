# Feature Specification: Runbook Draft Generator

**Feature Branch**: `006-runbook-generation`
**Created**: 2025-12-30
**Status**: Draft
**Blueprint**: Follows 004-eval-test-case-generator architecture with maximum code reuse

## Overview

Transform approved failure patterns into operational runbook entries with incident response procedures, troubleshooting steps, and escalation paths. This generator runs parallel to eval/guardrail generators and embeds RunbookDraft on Suggestion documents at `suggestion_content.runbook_snippet`.

## Code Reuse Strategy

### Directly Reusable (No Changes)
| Module | Path | Usage |
|--------|------|-------|
| GeminiConfig | `src/common/config.py` | Configuration for Gemini calls |
| FirestoreConfig | `src/common/config.py` | Firestore connection settings |
| PII utilities | `src/common/pii.py` | `redact_and_truncate()` for sanitization |
| Firestore helpers | `src/common/firestore.py` | Collection name functions, client factory |
| Logging | `src/common/logging.py` | Structured logging utilities |

### Reusable with Minor Adaptation (Copy & Modify)
| Source Module | Runbook Version | Changes Required |
|---------------|-----------------|------------------|
| `eval_tests/models.py` | `runbooks/models.py` | Replace EvalTestDraft with RunbookDraft; keep TriggeredBy, EditSource, error types |
| `eval_tests/gemini_client.py` | `runbooks/gemini_client.py` | Change response_schema to runbook schema |
| `eval_tests/firestore_repository.py` | `runbooks/firestore_repository.py` | Query `type=="runbook"`; write to `runbook_snippet` |
| `eval_tests/eval_test_service.py` | `runbooks/runbook_service.py` | Use runbook prompt template; same orchestration logic |
| `eval_tests/main.py` | `runbooks/main.py` | Change endpoint prefix to `/runbooks`; identical structure |

### Runbook-Specific (New Code)
| Module | Purpose |
|--------|---------|
| `runbooks/prompt_templates.py` | SRE runbook-specific prompt with Markdown template |

---

## User Scenarios & Testing

### User Story 1 - Batch Runbook Generation (Priority: P1)

As an SRE platform engineer, I want to trigger batch runbook generation for pending suggestions so that operational documentation is created systematically without manual effort.

**Why this priority**: Core functionality that enables automated runbook creation at scale.

**Independent Test**: Can be fully tested by calling POST `/runbooks/run-once` with test suggestions and verifying runbook drafts appear in Firestore.

**Acceptance Scenarios**:

1. **Given** 5 pending runbook-type suggestions exist, **When** I call `/runbooks/run-once` with batch_size=5, **Then** 5 runbook drafts are generated and embedded on their respective suggestions.

2. **Given** a suggestion with insufficient reproduction context, **When** batch generation processes it, **Then** a template fallback runbook with `status="needs_human_input"` is created.

3. **Given** a suggestion already has a human-edited runbook (`edit_source="human"`), **When** batch generation runs without force_overwrite, **Then** that suggestion is skipped to protect human edits.

---

### User Story 2 - Single Runbook Generation (Priority: P2)

As an SRE, I want to generate or regenerate a runbook for a specific suggestion so that I can get immediate documentation for a particular incident type.

**Why this priority**: Enables on-demand generation for urgent incidents.

**Independent Test**: Can be tested by calling POST `/runbooks/generate/{id}` and verifying the specific suggestion is updated.

**Acceptance Scenarios**:

1. **Given** a valid suggestion ID, **When** I call `/runbooks/generate/{id}`, **Then** a runbook draft is generated and embedded on the suggestion.

2. **Given** a suggestion with `edit_source="human"`, **When** I call `/runbooks/generate/{id}` without `forceOverwrite=true`, **Then** I receive a 409 Conflict response.

3. **Given** a suggestion with `edit_source="human"`, **When** I call `/runbooks/generate/{id}` with `forceOverwrite=true`, **Then** the runbook is regenerated and `edit_source` is set back to "generated".

---

### User Story 3 - Runbook Retrieval (Priority: P3)

As an SRE reviewing the suggestion queue, I want to retrieve the current runbook draft for a suggestion so that I can review it before approval.

**Why this priority**: Supports the approval workflow with read access.

**Independent Test**: Can be tested by calling GET `/runbooks/{id}` after generation and verifying complete response structure.

**Acceptance Scenarios**:

1. **Given** a suggestion with a runbook draft, **When** I call GET `/runbooks/{id}`, **Then** I receive the full runbook content including approval metadata.

2. **Given** a suggestion without a runbook draft, **When** I call GET `/runbooks/{id}`, **Then** I receive a 404 Not Found response.

---

### Edge Cases

- What happens when Gemini API is unavailable? → Retry 3x with exponential backoff, then record error and continue batch.
- What happens when suggestion has no failure patterns? → Use template fallback with `status="needs_human_input"`.
- What happens when run cost budget is exceeded? → Generate template fallback (no Gemini call) with `model="template_run_budget_exceeded"`.
- What happens when per-suggestion timeout is reached? → Record timeout error, continue with next suggestion.

---

## Requirements

### Functional Requirements

- **FR-001**: System MUST generate runbook drafts following SRE standard format (Summary → Symptoms → Diagnosis → Mitigation → Root Cause Fix → Escalation)
- **FR-002**: System MUST embed runbook drafts on Suggestion documents at `suggestion_content.runbook_snippet`
- **FR-003**: System MUST NOT modify Suggestion `status` or `approval_metadata` (generator is read-only for approval state)
- **FR-004**: System MUST protect human-edited runbooks (`edit_source="human"`) from overwrite unless explicitly forced
- **FR-005**: System MUST sanitize all inputs through PII redaction before building prompts
- **FR-006**: System MUST include specific Datadog queries and commands in generated runbooks (not just "check logs")
- **FR-007**: System MUST track generation lineage (trace_ids, pattern_ids, canonical sources)
- **FR-008**: System MUST record run summaries and per-suggestion errors for observability
- **FR-009**: System MUST implement cost budgeting with template fallback when budget exceeded
- **FR-010**: System MUST output Markdown format compatible with Confluence/GitHub

### Key Entities

- **RunbookDraft**: Generated operational runbook with title, rationale (plain-language reasoning citing source trace), markdown_content, symptoms, diagnosis_commands, mitigation_steps, escalation_criteria, and generator metadata
- **RunbookDraftSource**: Lineage tracking (suggestion_id, canonical_trace_id, pattern_ids, trace_ids)
- **RunbookRunSummary**: Batch execution record (run_id, counts, timing, outcomes)
- **RunbookError**: Per-suggestion failure record for diagnostics

---

## Success Criteria

### Measurable Outcomes

- **SC-001**: Generated runbooks are coherent and actionable (5 sample review by SRE shows 80%+ acceptance rate)
- **SC-002**: Runbooks follow standard SRE format with all 6 sections present (Summary, Symptoms, Diagnosis, Mitigation, Root Cause Fix, Escalation)
- **SC-003**: Diagnosis sections include at least 2 specific commands or queries per runbook
- **SC-004**: Runbook Markdown renders correctly in GitHub preview without formatting errors
- **SC-005**: Batch generation processes 20 suggestions in under 5 minutes
- **SC-006**: 95% of runbooks generated without requiring template fallback (under normal conditions)

---

## Out of Scope

- Runbook versioning system (store in Firestore only for hackathon)
- Automatic runbook updates when new similar incidents occur
- Integration with PagerDuty or incident management tools
- Cross-linking between runbook and generated eval test/guardrail (deferred to future)

---

## Runbook Template Structure

Generated runbooks MUST follow this Markdown structure:

```markdown
# {Failure Type} - Operational Runbook

**Source Incident**: `{trace_id}`
**Severity**: {severity}
**Generated**: {timestamp}

---

## Summary
Brief description of the failure mode (1-2 sentences).

## Symptoms
Observable indicators that this failure is occurring:
- Symptom 1 (with metric/log pattern to check)
- Symptom 2 (with specific error message)

## Diagnosis Steps
1. **Check X** using command: `datadog trace search "service:llm-agent status:error"`
2. **Verify Y** in dashboard: [LLM Observability Dashboard](link)
3. **Review Z logs**: Look for pattern `{specific_pattern}`

## Immediate Mitigation
Actions to reduce customer impact right now:
1. **Step 1**: Specific action with command/API call
2. **Step 2**: Validation step to confirm mitigation worked

## Root Cause Fix
Long-term fix to prevent recurrence:
1. **Code change**: Modify `{file}` to add `{check}`
2. **Deploy guardrail**: Apply guardrail rule `{rule_name}`

## Escalation
- **When to escalate**: If diagnosis steps don't confirm root cause within 15 minutes
- **Who to contact**: #team-llm-ops in Slack
- **Escalation threshold**: Customer impact >100 users OR downtime >30 minutes

---

*Auto-generated by EvalForge from production failure patterns.*
```

---

## Assumptions

1. Gemini 2.5 Flash can generate coherent Markdown runbooks with structured sections
2. Failure patterns contain sufficient context (trigger_condition, reproduction_context) for runbook generation
3. SRE team will review and refine generated runbooks before using in production incidents
4. Existing GeminiConfig settings (temperature=0.2-0.4) are appropriate for runbook generation
5. Same cost budgeting thresholds as eval generator are acceptable for runbooks
