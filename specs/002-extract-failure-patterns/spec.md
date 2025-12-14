# Feature Specification: Failure Pattern Extraction

**Feature Branch**: `002-extract-failure-patterns`  
**Created**: 2025-12-14  
**Status**: Draft  
**Input**: User description: "**Context & Goals:** Current tools (Datadog, LangSmith, Arize) observe problems but don't extract actionable patterns. 93% of evaluations happen pre-deployment only (arXiv MLR research) because theres no systematic way to learn from production failures. This service bridges that gap by using Gemini to analyze traces and extract structured failure patterns. **User Story:** As an ML engineer, I want failure patterns automatically extracted from traces so that I can understand root causes without manually analyzing each incident and can focus on prevention. **Acceptance Criteria:** - AC1: Given 10 sample failure traces, extracts consistent patterns with >80% accuracy - AC2: Output matches defined JSON schema (validated before storage) - AC3: Handles malformed/incomplete traces gracefully (logs error, continues) - AC4: Extraction completes in <10 seconds per trace - AC5: Confidence scores accurately reflect pattern quality (manual spot-check on 20 samples) **Out of Scope:** - Pattern clustering at this stage (deduplication happens in Issue - Real-time extraction (batch processing sufficient)"

## Clarifications

### Session 2025-12-14

- Q: What “evidence” content is allowed to be stored in an extracted failure pattern record? → A: Allow short redacted text excerpts (prompts/outputs/errors) plus structured signals.
- Q: For AC1 (“>80% accuracy”), what exactly are we scoring as “accurate”? → A: Accuracy = correct category + primary contributing factor; weighted scoring deferred.
- Q: Who is allowed to view stored extracted patterns (including redacted evidence excerpts)? → A: Internal ML engineering + on-call only.
- Q: How are batch extraction runs initiated? → A: Both scheduled + manual runs.
- Q: Where do the “10 sample failure traces” for AC1 come from? → A: Sanitized real traces captured from production.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Batch extract failure patterns (Priority: P1)

An ML engineer wants production failure traces analyzed in batch so they receive a structured failure pattern per trace (what happened, why it likely happened, what evidence supports it, and what to do next), without manually reading raw trace data.

**Why this priority**: This is the core value: turning production failures into actionable, reusable insights so teams can prevent repeat incidents.

**Independent Test**: Provide a curated set of 10 representative failure traces with expected labels (failure category + key contributing factor). Trigger an extraction run (scheduled or manual) and verify a structured pattern record is produced for each valid trace, and that at least 8/10 match the expected labels.

**Acceptance Scenarios**:

1. **Given** 10 well-formed sample failure traces with expected labels, **When** a batch extraction run is executed, **Then** the system produces a structured pattern record per trace and achieves ≥80% correctness, where correctness means the predicted category and primary contributing factor (trigger condition label) both match the expected labels.
2. **Given** a trace containing clear failure signals, **When** extraction runs, **Then** the output includes a concise pattern title, category, root-cause hypothesis, supporting evidence, recommended prevention/mitigation actions, and a confidence score.

---

### User Story 2 - Schema-validated storage for downstream use (Priority: P2)

An ML engineer needs extracted patterns to be reliably stored in a consistent structured format so they can be consumed by downstream workflows (e.g., evaluation creation, guardrails, runbooks) without additional cleanup.

**Why this priority**: If outputs are not consistently structured and validated, downstream automation becomes brittle and the extracted insights cannot be trusted or reused.

**Independent Test**: Run extraction on a small batch and verify that only outputs that conform to the agreed schema are stored and retrievable; any non-conforming outputs are rejected with a recorded validation error.

**Acceptance Scenarios**:

1. **Given** an extracted pattern that conforms to the agreed schema, **When** the system persists it, **Then** it is stored and an authorized internal user can retrieve it intact with required fields present.
2. **Given** an extracted pattern that does not conform to the agreed schema, **When** the system attempts to persist it, **Then** it is not stored and a validation error is recorded with the related trace reference.

---

### User Story 3 - Resilient processing for malformed traces (Priority: P3)

An operator or ML engineer expects batch extraction to continue even if some traces are malformed or incomplete, so a single bad input does not block learning from the rest of the batch.

**Why this priority**: Production data is imperfect; resilience prevents stalled pipelines and keeps the feedback loop moving.

**Independent Test**: Submit a batch containing both valid and malformed traces. Verify the run completes, valid traces produce stored patterns, malformed traces are reported as errors, and the run summary reflects partial success.

**Acceptance Scenarios**:

1. **Given** a batch where at least one trace is malformed/incomplete, **When** extraction runs, **Then** the system records an error for the malformed trace and continues processing the remaining traces.
2. **Given** a batch run completes with mixed outcomes, **When** the run summary is reviewed, **Then** it clearly lists counts and trace references for successes, validation failures, and processing errors.
3. **Given** an operator needs to re-run extraction for the same inputs after a fix, **When** they manually start a new extraction run, **Then** the system completes a new run summary and updates/replaces per-trace stored patterns according to idempotency rules.

---

### Edge Cases

- Trace is missing a unique identifier or timestamp — pattern extraction is skipped for that trace and the error is recorded.
- Trace payload is present but structurally incomplete (missing spans/attributes) — system extracts a best-effort pattern when possible and downgrades confidence; otherwise records an error and continues.
- Trace contains large/verbose payloads — system still completes within performance targets or explicitly records a timeout/oversize error for that trace without failing the batch.
- Analysis output is unparseable or missing required fields — output is rejected by schema validation and not stored.
- Trace includes sensitive user-provided text — stored evidence excerpts must be redacted or omitted, and the pattern remains linked to the trace reference for deeper investigation when needed.
- Re-processing the same input traces — system is idempotent per trace reference and updates/replaces the existing stored pattern record rather than creating duplicates.
- Batch contains a high proportion of malformed traces — run completes with accurate error accounting and no partial data corruption.
- An unauthorized user attempts to retrieve stored patterns — access is denied and no pattern content is revealed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a batch of failure traces and attempt pattern extraction for each trace independently; the system MUST support batches of at least 10 traces per run.
- **FR-002**: For each successfully processed trace, System MUST produce exactly one extracted pattern record linked to that trace reference.
- **FR-003**: Each extracted pattern record MUST include: trace reference, pattern title, standardized category (from a controlled vocabulary defined by the schema), trigger condition / primary contributing factor (single short label), concise summary, root-cause hypothesis, supporting evidence (at least one trace-derived signal and optionally short redacted text excerpts), recommended prevention/mitigation actions (at least one), confidence score, and extraction timestamp.
- **FR-004**: System MUST validate each extracted pattern record against the agreed JSON schema before storage; any record that fails validation MUST NOT be stored.
- **FR-005**: For validation failures or processing errors, System MUST record an error event that includes the trace reference and a human-readable reason.
- **FR-006**: System MUST continue processing remaining traces when any individual trace fails (malformed input, extraction error, or schema validation failure).
- **FR-007**: System MUST produce a per-run summary that includes: total traces received, successfully processed count, stored pattern count, validation failure count, processing error count, and trace references for failures.
- **FR-008**: System MUST complete processing for each trace within 10 seconds by enforcing a per-trace time budget; if the time budget is exceeded, the trace MUST be marked as timed out, an error MUST be recorded, and the batch MUST continue.
- **FR-009**: System MUST assign a confidence score in the range [0.0, 1.0] for every stored pattern, where higher values indicate higher expected correctness and completeness.
- **FR-010**: System MUST include a short confidence rationale explaining key signals that most influenced the confidence score.
- **FR-011**: System MUST ensure stored extracted patterns do not include raw sensitive user data; if storing evidence text excerpts, they MUST be redacted and limited to short snippets rather than full prompt/output transcripts.
- **FR-012**: System MUST be idempotent per trace reference: re-processing the same trace MUST update/replace the existing stored pattern record rather than creating duplicates.
- **FR-013**: System MUST restrict retrieval/viewing of stored extracted patterns and run summaries to authorized internal users in ML engineering and on-call roles.
- **FR-014**: System MUST support both scheduled and manual initiation of extraction runs.

### Key Entities *(include if feature involves data)*

- **Failure Trace**: A captured record of a production failure event (identifier, timestamp, service/agent context, and supporting trace payload).
- **Extracted Failure Pattern**: A structured insight derived from a single failure trace, including category, primary contributing factor, root-cause hypothesis, evidence (structured signals plus optional redacted excerpts), recommended actions, and confidence.
- **Extraction Run Summary**: A record describing one batch extraction attempt, including counts, timing, and per-trace outcomes for auditing and troubleshooting.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a curated evaluation set of 10 sample failure traces with expected labels, the system achieves ≥80% correctness on (a) the primary failure category and (b) the primary contributing factor (single label), per the evaluation rubric.
- **SC-002**: 100% of stored extracted pattern records conform to the agreed JSON schema (schema validation occurs before storage).
- **SC-003**: In a batch containing at least one malformed/incomplete trace, the batch completes and produces patterns for all remaining valid traces; the run summary reports errors without halting the batch.
- **SC-004**: For a batch of 10 well-formed traces, at least 95% of traces produce a stored pattern within 10 seconds, and 100% of traces finish processing (stored pattern or recorded error) within 10 seconds.
- **SC-005**: In a manual spot-check of 20 extracted patterns, confidence scores are directionally calibrated: (a) the average confidence for reviewer-rated “correct” patterns is at least 0.2 higher than for “incorrect” patterns, and (b) at least 75% of patterns with confidence ≥0.8 are rated “correct.”
- **SC-006**: In a manual audit of 20 stored extracted patterns, 0 contain raw sensitive user data in any field, including evidence excerpts.

## Assumptions

1. A curated set of sample failure traces exists (or will be created) with expected labels and a lightweight rubric for judging correctness.
2. The 10-sample evaluation set is built from sanitized real failure traces captured from production and labeled with category + primary contributing factor.
3. Batch processing is sufficient for this iteration; near-real-time extraction is explicitly deferred.

## Out of Scope

- Clustering/deduplication of extracted patterns across multiple traces (handled in a separate issue).
- Real-time extraction at ingestion time (batch processing only for this iteration).
- Weighted multi-field accuracy scoring across pattern fields (category, cause, evidence, actions).
