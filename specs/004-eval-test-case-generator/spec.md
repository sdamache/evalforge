# Feature Specification: Eval Test Case Generator

**Feature Branch**: `004-eval-test-case-generator`  
**Created**: 2025-12-29  
**Status**: Draft  
**Input**: Issue #7 (duplicate of #4) — generate eval test cases from failure suggestions so teams can add regression coverage to CI/CD.

## Clarifications

### Session 2025-12-29

- Q: What format should the generated eval test draft be stored/exported as? → A: Framework-agnostic JSON object.
- Q: When should the system attempt the first eval test draft generation for an eval-type suggestion? → A: Scheduled/batch runs (manual + scheduled).
- Q: If an eval-type suggestion has multiple source traces/patterns, which one should drive reproduction context? → A: Use the highest-confidence source trace/pattern (tie-breaker: most recent).
- Q: What should the generator produce as the default pass/fail criteria for an eval test draft? → A: Hybrid — rubric-first with optional golden output when deterministic.
- Q: Where should the generated eval test JSON be stored? → A: Embedded on the Suggestion (`suggestion_content.eval_test`).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Draft eval tests from real failures (Priority: P1)

As an ML engineer, when a failure pattern is turned into an eval-type suggestion, I want an eval test draft generated that reproduces the failure and specifies what “good” behavior looks like, so I can quickly turn production incidents into regression coverage.

**Why this priority**: This is the core value proposition of the Incident-to-Insight loop: convert failures into runnable tests with minimal manual effort.

**Independent Test**: Create 5 eval-type suggestions from representative failure patterns and verify each receives a complete eval test draft that a human can run (inputs + expected behavior + pass criteria) within the expected latency budget.

**Acceptance Scenarios**:

1. **Given** an eval-type suggestion with a clear trigger condition and reproduction context, **When** the generator runs, **Then** it produces an eval test draft with a reproducible input and explicit pass/fail criteria aligned to the failure.
2. **Given** an eval-type suggestion created from multiple similar source traces, **When** the generator runs, **Then** the eval test draft references the aggregated lineage and covers the common reproduction shape rather than a one-off edge incident.

---

### User Story 2 - Review-ready drafts with clear rationale (Priority: P2)

As a quality lead, I want each generated eval test draft to include plain-language rationale and trace references, so I can quickly decide whether to approve it without re-investigating raw incidents.

**Why this priority**: Human governance is a core safety mechanism—reviewers must understand why a test exists and what it guards against before approving it for CI.

**Independent Test**: For a small set of pending suggestions, verify that reviewers can inspect the eval test draft, understand what it is testing and why, and approve or reject with minimal back-and-forth.

**Acceptance Scenarios**:

1. **Given** a pending eval-type suggestion with a generated eval test draft, **When** a reviewer inspects it, **Then** they can see (a) the source trace references, (b) the failure summary it targets, and (c) the rationale mapping “what went wrong” → “what the test asserts.”
2. **Given** a suggestion where the generator could not confidently form a deterministic expected outcome, **When** a reviewer inspects it, **Then** the draft uses a rubric-based expectation (e.g., required/forbidden behaviors) and explains the trade-offs clearly.

---

### User Story 3 - Safe, reusable artifacts for CI/CD (Priority: P3)

As a platform lead, I want approved eval tests to be stored in a consistent structure that downstream tooling can consume, so we can add them to CI/CD with minimal translation effort.

**Why this priority**: Even great drafts are low value if they are not consistently shaped and safely storable/portable.

**Independent Test**: Take an approved eval-type suggestion and confirm its eval test draft can be exported/consumed as a structured artifact without manual restructuring.

**Acceptance Scenarios**:

1. **Given** an approved eval-type suggestion, **When** downstream tooling requests its eval artifact, **Then** the system returns a structured eval test object with required fields present and the approval status preserved.
2. **Given** an eval test draft that contains sensitive or overly-specific details, **When** the system persists or exports it, **Then** sensitive content is excluded or redacted and the artifact remains usable.

---

### Edge Cases
- A suggestion lacks sufficient reproduction context to form a runnable test — generator produces a “needs-human-input” draft with clear placeholders rather than fabricating details.
- Multiple source traces disagree on the “correct” expected outcome — generator surfaces ambiguity and proposes a conservative rubric until clarified.
- The input that triggered the failure contains sensitive data — generator must redact sensitive content and/or generalize the input shape.
- A suggestion is regenerated after reviewer edits — system must avoid silently discarding human edits (must either preserve edits or require explicit overwrite).
- Generator dependency outage or quota throttling — suggestion remains reviewable and retryable; failures are recorded with actionable messages.
- Generation exceeds cost budget — system MUST degrade to a lower-cost fallback (template-based `needs_human_input` draft) rather than failing the run.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST generate an eval test draft for each eval-type suggestion using the suggestion’s summarized failure pattern and reproduction context.
- **FR-002**: Every generated eval test draft MUST include: a human-readable title, a reproducible input (or steps), explicit pass/fail criteria, and references to the source traces/patterns that motivated the test.
- **FR-003**: System MUST produce a schema-defined, framework-agnostic JSON eval test draft that downstream tooling can consume without additional translation.
- **FR-004**: System MUST keep generated eval tests in a “pending” state until a human explicitly approves the suggestion; generation MUST NOT auto-approve or auto-deploy evals (must not modify `Suggestion.status` or `Suggestion.approval_metadata`).
- **FR-005**: Every eval test draft MUST include plain-language rationale that explains how the test guards against the production failure (what it prevents and why it matters).
- **FR-006**: System MUST ensure stored eval tests do not contain raw sensitive user data; any included text must be sanitized/redacted and limited to what is necessary to reproduce the behavior.
- **FR-007**: System MUST be idempotent per suggestion: re-running generation for the same suggestion MUST update the existing draft rather than creating duplicates.
- **FR-008**: Users MUST be able to request regeneration for a specific suggestion (manual trigger) without affecting unrelated suggestions.
- **FR-009**: If generation fails (timeouts, upstream errors, invalid input), System MUST record an actionable error linked to the suggestion and allow retry without blocking other workflows.
- **FR-010**: System MUST validate generated eval test drafts against an agreed schema before storing or exporting them; invalid drafts MUST NOT be persisted.
- **FR-011**: System MUST surface enough metadata for downstream tooling to determine whether an eval test is approved for use (approval status and timestamp).
- **FR-012**: System MUST record an auditable generation event (timestamp, outcome, and linked suggestion + source trace references) so reviewers can trace how an eval test draft was produced.
- **FR-013**: System MUST support both scheduled and manual initiation of eval test generation runs.
- **FR-014**: When an eval-type suggestion has multiple source traces/patterns, System MUST choose a canonical source for reproduction context using the highest-confidence source (tie-breaker: most recent) while still referencing all sources for lineage.
- **FR-015**: By default, System MUST generate rubric-based pass/fail criteria (required and forbidden behaviors) and MAY include an optional golden output check when the expected output is deterministic.
- **FR-016**: System MUST store the generated eval test JSON embedded on the suggestion as `suggestion_content.eval_test`.

### Non-Functional Requirements

- **Latency**: 95% of eval test draft generations complete within 30 seconds per suggestion; timeouts are recorded and do not block other work.
- **Observability**: Generation events are traceable end-to-end with linked suggestion IDs and source trace references; failures include actionable messages for retry.
- **Cost**: Average generation cost per **suggestion** is kept under $0.10. The system records per-suggestion token/cost estimates when available and enforces a per-run budget (derived from batch size and per-suggestion budget unless explicitly configured). If the budget would be exceeded, the system MUST fall back to a lower-cost, template-based `needs_human_input` draft (no Gemini call).

### Key Entities *(include if feature involves data)*

- **Suggestion**: A deduplicated recommendation derived from one or more failure patterns, tracked through review states (pending/approved/rejected).
- **Eval Test Draft**: A structured test artifact derived from a suggestion that encodes reproducible inputs and pass/fail criteria for regression checking.
- **Approval Metadata**: Reviewer identity, decision, and notes that determine whether the eval test is eligible to be promoted into CI/CD.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a batch of 10 eval-type suggestions, at least 90% receive a complete eval test draft (input + pass/fail criteria + lineage + rationale) within 30 seconds per suggestion.
- **SC-002**: 100% of persisted eval test drafts conform to the agreed schema (schema validation occurs before storage/export).
- **SC-003**: In a manual spot-check of 20 eval test drafts, at least 80% are judged by reviewers to (a) match the intended failure mode and (b) be runnable with minimal edits.
- **SC-004**: In a manual audit of 20 stored eval tests, 0 contain raw sensitive user data (including unredacted prompts/outputs or user identifiers).
- **SC-005**: Reviewers can approve or reject an eval-type suggestion in under 2 minutes on average using only the generated draft, rationale, and lineage (no rehydrating raw traces required for most cases).

## Assumptions

1. Eval-type suggestions exist and include (or can reference) enough reproduction context to build a runnable test draft.
2. Reviewers approve or reject suggestions before any eval test is promoted into CI/CD.
3. Downstream tooling can consume a structured eval test object once the schema is defined in planning.
4. Suggestion documents follow Issue #3 schema (including `Suggestion.type`, `Suggestion.status`, and optional `Suggestion.approval_metadata.timestamp` used as the approval timestamp surfaced to downstream tooling).

## Out of Scope

- Generating guardrail rules or runbook entries (handled in separate issues).
- Automatically committing eval tests into a source repository or deploying them without explicit human approval.
- Building a full UI for editing tests; minimal review surfaces are sufficient for hackathon scope.
