# Feature Specification: Guardrail Suggestion Engine

**Feature Branch**: `005-guardrail-generation`
**Created**: 2025-12-30
**Status**: Draft
**Input**: Issue #5 — generate guardrail rules from failure suggestions so teams can deploy runtime protection against known failure modes.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate guardrail rules from failure patterns (Priority: P1)

As a platform team lead, when a failure pattern is turned into a guardrail-type suggestion, I want a guardrail rule draft generated that specifies conditions to block/prevent similar failures, so I can deploy runtime protection without manually crafting rules.

**Why this priority**: This is the core value proposition — proactively suggesting guardrails based on observed failure patterns rather than creating them reactively after damage is done.

**Independent Test**: Create 5 guardrail-type suggestions from representative failure patterns (hallucination, runaway_loop, pii_leak, stale_data, prompt_injection) and verify each receives a complete guardrail draft with specific rule configuration within the expected latency budget.

**Acceptance Scenarios**:

1. **Given** a guardrail-type suggestion for a hallucination failure, **When** the generator runs, **Then** it produces a content validation guardrail with specific check conditions (e.g., verify against knowledge base before responding).
2. **Given** a guardrail-type suggestion for a runaway_loop failure, **When** the generator runs, **Then** it produces a rate limit guardrail with specific thresholds (max calls, time window) aligned to the observed failure.
3. **Given** a guardrail-type suggestion created from multiple similar source traces, **When** the generator runs, **Then** the guardrail draft references the aggregated lineage and covers the common failure pattern.

---

### User Story 2 - Review-ready drafts with actionable configuration (Priority: P2)

As a quality lead, I want each generated guardrail draft to include plain-language justification and concrete configuration values, so I can quickly evaluate whether to approve it without reverse-engineering the rule logic.

**Why this priority**: Human governance is critical — reviewers must understand why a guardrail exists and what it blocks before deploying to production.

**Independent Test**: For a set of pending guardrail suggestions, verify that reviewers can inspect the guardrail draft, understand what it blocks and why, and approve or reject with minimal back-and-forth.

**Acceptance Scenarios**:

1. **Given** a pending guardrail-type suggestion with a generated draft, **When** a reviewer inspects it, **Then** they can see (a) the source trace references, (b) the failure type it guards against, (c) the justification explaining how this rule prevents recurrence.
2. **Given** a guardrail draft for a rate limit rule, **When** a reviewer inspects it, **Then** they can see specific values (max_calls, window_seconds, action) that can be deployed without further specification.

---

### User Story 3 - Consistent output format for deployment tooling (Priority: P3)

As a DevOps engineer, I want approved guardrail rules to be stored in a consistent structure that Datadog AI Guard or similar systems can consume, so we can deploy them with minimal translation effort.

**Why this priority**: Guardrails provide no value until deployed — consistent output formats enable automation and reduce deployment friction.

**Independent Test**: Take an approved guardrail-type suggestion and confirm its guardrail draft can be exported in both JSON and YAML formats compatible with common guardrail systems.

**Acceptance Scenarios**:

1. **Given** an approved guardrail-type suggestion, **When** downstream tooling requests its guardrail artifact, **Then** the system returns a structured guardrail object with required fields present and the approval status preserved.
2. **Given** a guardrail draft in JSON format, **When** converted to YAML, **Then** the output is compatible with Datadog AI Guard configuration schema.

---

### Edge Cases

- A suggestion lacks sufficient context to form a specific guardrail — generator produces a "needs-human-input" draft with clear placeholders rather than generating a generic "add validation" rule.
- Multiple source traces suggest conflicting guardrail parameters (e.g., different rate limits) — generator surfaces ambiguity and proposes conservative defaults.
- The failure pattern maps to an unusual guardrail type not in the standard mapping — generator falls back to a general "validation_rule" type with clear notes.
- A suggestion is regenerated after reviewer edits — system must avoid silently discarding human edits (preserve edits or require explicit overwrite).
- Generator dependency outage or quota throttling — suggestion remains reviewable and retryable; failures are recorded with actionable messages.
- Generation exceeds cost budget — system degrades to a lower-cost template-based draft rather than failing the run.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST generate a guardrail draft for each guardrail-type suggestion using the suggestion's failure pattern and reproduction context.
- **FR-002**: Every generated guardrail draft MUST include: a rule name, guardrail type, configuration with specific values, justification explaining prevention mechanism, and references to source traces/patterns.
- **FR-003**: System MUST map failure types to appropriate guardrail types using a deterministic mapping (e.g., hallucination → validation_rule, runaway_loop → rate_limit, pii_leak → redaction_rule).
- **FR-004**: System MUST produce guardrail drafts in a structured JSON format that can be converted to Datadog AI Guard compatible YAML.
- **FR-005**: System MUST keep generated guardrails in a "pending" state until a human explicitly approves the suggestion; generation MUST NOT auto-approve or auto-deploy guardrails (must not modify `Suggestion.status` or `Suggestion.approval_metadata`).
- **FR-006**: Every guardrail draft MUST include plain-language justification that explains how the guardrail prevents recurrence of the observed failure.
- **FR-007**: System MUST ensure stored guardrails do not contain raw sensitive user data; any included text must be sanitized/redacted.
- **FR-008**: System MUST be idempotent per suggestion: re-running generation for the same suggestion MUST update the existing draft rather than creating duplicates.
- **FR-009**: Users MUST be able to request regeneration for a specific suggestion (manual trigger) without affecting unrelated suggestions.
- **FR-010**: If generation fails (timeouts, upstream errors, invalid input), System MUST record an actionable error linked to the suggestion and allow retry without blocking other workflows.
- **FR-011**: System MUST validate generated guardrail drafts against an agreed schema before storing; invalid drafts MUST NOT be persisted.
- **FR-012**: System MUST record an auditable generation event (timestamp, outcome, run_id, linked suggestion + source trace references) so reviewers can trace how a guardrail draft was produced.
- **FR-013**: System MUST support both scheduled (batch) and manual (single suggestion) initiation of guardrail generation runs.
- **FR-014**: When a guardrail-type suggestion has multiple source traces/patterns, System MUST choose a canonical source for context using the highest-confidence source (tie-breaker: most recent) while referencing all sources for lineage.
- **FR-015**: System MUST store the generated guardrail JSON embedded on the suggestion as `suggestion_content.guardrail`.
- **FR-016**: System MUST reuse existing infrastructure from the eval test generator (Gemini client, repository pattern, cost budget enforcement, overwrite protection with edit_source flag).
- **FR-017**: Every guardrail draft MUST include concrete configuration values (thresholds, limits, conditions) — not generic placeholders like "add appropriate validation".

### Non-Functional Requirements

- **Latency**: 95% of guardrail draft generations complete within 30 seconds per suggestion; timeouts are recorded and do not block other work.
- **Observability**: Generation events are traceable end-to-end with linked suggestion IDs and source trace references; failures include actionable messages for retry.
- **Cost**: Average generation cost per suggestion is kept under $0.10. The system records per-suggestion cost estimates and enforces a per-run budget. If budget is exceeded, system falls back to a template-based `needs_human_input` draft.

### Key Entities

- **Suggestion**: A deduplicated recommendation derived from one or more failure patterns, tracked through review states (pending/approved/rejected). For this feature, only suggestions with `type="guardrail"` are processed.
- **Guardrail Draft**: A structured rule artifact derived from a suggestion that encodes prevention conditions and configuration for runtime enforcement.
- **Guardrail Type**: Category of protection (validation_rule, rate_limit, content_filter, redaction_rule, scope_limit, freshness_check, input_sanitization).
- **Approval Metadata**: Reviewer identity, decision, and notes that determine whether the guardrail is eligible for deployment.

### Failure Type to Guardrail Type Mapping

| Failure Type | Guardrail Type | Description |
|--------------|----------------|-------------|
| hallucination | validation_rule | Check facts against knowledge base before responding |
| toxicity | content_filter | Block offensive or harmful outputs |
| runaway_loop | rate_limit | Max N calls per session/time window |
| pii_leak | redaction_rule | Strip sensitive patterns from output |
| wrong_tool | scope_limit | Restrict tool availability based on context |
| stale_data | freshness_check | Verify data recency before use |
| prompt_injection | input_sanitization | Block malicious prompt patterns |

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a batch of 10 guardrail-type suggestions, at least 90% receive a complete guardrail draft (type + configuration + justification + lineage) within 30 seconds per suggestion.
- **SC-002**: 100% of persisted guardrail drafts conform to the agreed schema (schema validation occurs before storage).
- **SC-003**: In a manual spot-check of 20 guardrail drafts, at least 80% are judged by reviewers to (a) match the intended failure mode, (b) have actionable configuration values, and (c) be deployable with minimal edits.
- **SC-004**: In a manual audit of 20 stored guardrails, 0 contain raw sensitive user data.
- **SC-005**: Reviewers can approve or reject a guardrail-type suggestion in under 2 minutes on average using only the generated draft, justification, and lineage.
- **SC-006**: Given a hallucination failure pattern, the generated guardrail MUST be a content validation type with specific check conditions.
- **SC-007**: Given a runaway_loop failure pattern, the generated guardrail MUST be a rate_limit type with specific thresholds (max_calls, window_seconds).

## Assumptions

1. Guardrail-type suggestions exist and include enough context (failure_type, trigger_condition, reproduction_context) to generate specific rules.
2. Reviewers approve or reject suggestions before any guardrail is deployed to production.
3. The eval test generator infrastructure (Gemini client, repository pattern, cost budget) is available for reuse.
4. Suggestion documents follow Issue #3 schema (including `Suggestion.type`, `Suggestion.status`, and optional `Suggestion.approval_metadata`).
5. Downstream tooling can consume structured guardrail objects in JSON or YAML format.

## Out of Scope

- Automatic deployment of guardrails to production systems.
- Guardrail conflict detection across multiple rules.
- Multi-layer guardrails (one guardrail per suggestion).
- Building a UI for editing guardrails; minimal review surfaces are sufficient for hackathon scope.
- Creating new infrastructure — reuses existing patterns from 004-eval-test-case-generator.

## Code Reuse Strategy

This feature follows the exact architecture of 004-eval-test-case-generator, maximizing code reuse.

### Directly Reusable (No Changes)

| Module | Path | Usage |
|--------|------|-------|
| GeminiConfig | `src/common/config.py` | Configuration for Gemini calls |
| FirestoreConfig | `src/common/config.py` | Firestore connection settings |
| PII utilities | `src/common/pii.py` | `redact_and_truncate()` for sanitization |
| Firestore helpers | `src/common/firestore.py` | Collection name functions, client factory |
| Logging | `src/common/logging.py` | Structured logging utilities |

### Reusable with Minor Adaptation (Copy & Modify)

| Source Module | Guardrail Version | Changes Required |
|---------------|-------------------|------------------|
| `eval_tests/models.py` | `guardrails/models.py` | Replace EvalTestDraft with GuardrailDraft; keep TriggeredBy, EditSource, error types, RunSummary pattern |
| `eval_tests/gemini_client.py` | `guardrails/gemini_client.py` | Change response_schema to guardrail schema; same retry/hashing logic |
| `eval_tests/firestore_repository.py` | `guardrails/firestore_repository.py` | Query `type=="guardrail"`; write to `suggestion_content.guardrail`; collections: `guardrail_runs`, `guardrail_errors` |
| `eval_tests/eval_test_service.py` | `guardrails/guardrail_service.py` | Use guardrail prompt template; add failure-type-to-guardrail-type mapping; same orchestration logic |
| `eval_tests/main.py` | `guardrails/main.py` | Change endpoint prefix to `/guardrails`; identical FastAPI structure |

### Guardrail-Specific (New Code)

| Module | Purpose |
|--------|---------|
| `guardrails/prompt_templates.py` | Guardrail-specific prompt with failure type mapping and JSON/YAML output templates |
| `guardrails/guardrail_types.py` | `GUARDRAIL_MAPPING` dict for failure_type → guardrail_type conversion |

### Shared Patterns from 004

| Pattern | Description |
|---------|-------------|
| Overwrite Protection | `edit_source` flag prevents silent overwrite of human-edited drafts |
| Cost Budget | Per-suggestion + per-run budget enforcement with template fallback |
| Canonical Source Selection | Highest confidence pattern (tie-breaker: most recent) |
| Template Fallback | `needs_human_input` draft when Gemini unavailable or context insufficient |
| Run Summary | `guardrail_runs` collection tracks batch execution metrics |
| Error Recording | `guardrail_errors` collection stores per-suggestion failures with hashes |
| Idempotency | Re-running updates `updated_at`, preserves original `generated_at` |
