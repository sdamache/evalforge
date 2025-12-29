# Feature Specification: Suggestion Storage and Deduplication

**Feature Branch**: `003-suggestion-deduplication`
**Created**: 2025-12-28
**Status**: Draft
**Input**: Issue #3 - Clustering similar failure patterns into single suggestions to reduce approval fatigue

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Pattern Deduplication on Ingestion (Priority: P1)

As a platform lead, when a new failure pattern is extracted, I want the system to automatically check if a similar suggestion already exists and merge them if similarity exceeds 85%, so that I don't have to review duplicate suggestions for the same underlying issue.

**Why this priority**: This is the core value proposition - without deduplication, reviewers are overwhelmed with duplicates. This directly enables the user story of "focus review time on unique issues instead of approving 100 duplicates."

**Independent Test**: Can be fully tested by submitting 10 similar failure patterns and verifying that 1-2 suggestions are created (not 10). Delivers immediate value by reducing approval queue noise.

**Acceptance Scenarios**:

1. **Given** a new failure pattern with trigger "User asks for product recommendation without specifying category", **When** the system processes it and finds an existing suggestion with 90% semantic similarity, **Then** the new pattern's trace ID is added to the existing suggestion's source list instead of creating a new suggestion.

2. **Given** a new failure pattern for "hallucination" type, **When** the system processes it and finds no existing suggestions with >85% similarity, **Then** a new suggestion is created with status "pending" and the pattern's trace ID as the first source.

3. **Given** 10 failure traces all describing the same "stale product data" issue, **When** processed sequentially, **Then** the system creates 1-2 suggestions maximum (demonstrating effective clustering).

---

### User Story 2 - Suggestion Lineage Tracking (Priority: P2)

As a platform lead, when I approve a suggestion, I want to see which failure traces contributed to it, so that I can understand the scope of the problem and validate the suggestion against real incidents.

**Why this priority**: Lineage provides transparency and trust in the system. Without seeing source traces, users can't validate suggestions or understand their impact.

**Independent Test**: Can be tested by creating a suggestion from multiple traces, then querying the suggestion to verify all contributing trace IDs are visible. Delivers value by enabling informed approval decisions.

**Acceptance Scenarios**:

1. **Given** a suggestion that was created from 5 merged failure traces, **When** I view the suggestion details, **Then** I can see all 5 source trace IDs with timestamps of when each was added.

2. **Given** a suggestion created from a single trace, **When** a new similar trace is merged in, **Then** the suggestion's source list grows to include both trace IDs.

---

### User Story 3 - Audit Trail for Status Changes (Priority: P2)

As a compliance officer, I need a complete audit trail of all suggestion status changes (pending, approved, rejected), so that I can demonstrate proper review processes were followed.

**Why this priority**: Audit trails support compliance and accountability. They enable post-hoc analysis of approval patterns and reviewer behavior.

**Independent Test**: Can be tested by changing a suggestion's status multiple times and verifying each transition is recorded with timestamp, actor, and reason. Delivers value for compliance audits.

**Acceptance Scenarios**:

1. **Given** a suggestion in "pending" status, **When** it is approved by user "reviewer@company.com" with note "Validated against recent incidents", **Then** the audit trail records the transition with timestamp, user identity, and notes.

2. **Given** a suggestion with multiple status changes in its history, **When** I query the suggestion, **Then** I can see the complete chronological history of all status transitions.

---

### User Story 4 - Efficient Dashboard Queries (Priority: P3)

As an ML engineer using the dashboard, I want to browse and filter pending suggestions quickly, so that I can efficiently work through the approval queue during my weekly quality meeting.

**Why this priority**: Performance is important but secondary to core functionality. Poor performance degrades UX but doesn't block the workflow.

**Independent Test**: Can be tested by populating 1000+ suggestions and measuring query response time. Delivers value by enabling practical use at scale.

**Acceptance Scenarios**:

1. **Given** a database containing 1000 suggestions, **When** I query for pending suggestions sorted by severity, **Then** results are returned in under 2 seconds.

2. **Given** a large suggestion backlog, **When** I filter by suggestion type (eval, guardrail, runbook), **Then** filtered results return in under 2 seconds.

---

### Edge Cases

- What happens when two patterns are submitted simultaneously with 86% similarity? The first to complete processing becomes the "primary" suggestion, and the second merges into it.
- How does the system handle a pattern that is 85% similar to multiple different existing suggestions? It merges into the suggestion with the highest similarity score.
- What happens if embedding service is unavailable? The system queues the pattern for later processing and logs the failure, rather than creating a potentially duplicate suggestion.
- How are suggestions handled when the similarity is exactly at the threshold (85%)? Patterns at exactly 85% similarity are merged (threshold is inclusive).
- What happens when embedding service rate limit is exceeded? System applies exponential backoff (1s → 2s → 4s), retries up to 3 times, then queues remaining patterns for next batch cycle.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST compute semantic similarity between new failure patterns and existing suggestions using text embeddings.
- **FR-002**: System MUST merge new patterns into existing suggestions when similarity exceeds 85% threshold.
- **FR-003**: System MUST create new suggestions with "pending" status when no sufficiently similar suggestion exists.
- **FR-004**: System MUST maintain a list of all source trace IDs that contributed to each suggestion.
- **FR-005**: System MUST record every status transition (pending to approved, pending to rejected) with timestamp and actor identity.
- **FR-006**: System MUST support efficient querying of suggestions by status, type, and severity with response times under 2 seconds for 1000+ records.
- **FR-007**: System MUST cache embeddings for existing suggestions to avoid redundant computation.
- **FR-008**: System MUST apply appropriate indexing to support dashboard query patterns.
- **FR-009**: System MUST handle embedding service failures gracefully by queueing patterns for retry.
- **FR-010**: System MUST support three suggestion types: eval, guardrail, and runbook.
- **FR-011**: System MUST support three suggestion statuses: pending, approved, rejected (with pending as the only non-terminal state).
- **FR-012**: System MUST append to source trace list (not replace) when merging patterns into existing suggestions.
- **FR-013**: System MUST emit structured logs for all merge decisions including: pattern ID, matched suggestion ID (if any), similarity score, and decision outcome (merged/created new).
- **FR-014**: System MUST log processing metrics including: patterns processed count, merge rate, average similarity score, and processing duration per batch.
- **FR-015**: System MUST poll Firestore for failure patterns with `processed=false` flag on a scheduled interval.
- **FR-016**: System MUST mark patterns as `processed=true` after successful deduplication processing.
- **FR-017**: System MUST limit embedding requests to 20 patterns per batch to avoid quota exhaustion.
- **FR-018**: System MUST apply exponential backoff (starting at 1 second, max 3 retries) when embedding service returns throttling errors.

### Key Entities

- **Suggestion**: A deduplicated recommendation for improvement derived from one or more failure patterns. Contains type (eval/guardrail/runbook), status (pending/approved/rejected), severity, source trace IDs, pattern summary, similarity group identifier, cached embedding, and creation/update timestamps.

- **Failure Pattern**: The extracted pattern from a raw trace (from Issue #2). Contains failure type, trigger condition, reproduction context, severity, confidence score, and source trace ID.

- **Status History Entry**: A record of a status transition. Contains previous status, new status, timestamp, actor identity, and optional notes/reason.

- **Similarity Group**: A logical grouping of patterns that have been merged into a single suggestion. Identified by a group ID referenced by all merged suggestions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Given 10 failure traces describing the same underlying issue, the system creates 1-2 suggestions maximum (not 10), demonstrating greater than 80% deduplication rate.
- **SC-002**: Dashboard queries for suggestions (filtered by status, type, or severity) complete in under 2 seconds with 1000+ suggestions in the database.
- **SC-003**: Every suggestion displays complete lineage (all contributing trace IDs) to the reviewer.
- **SC-004**: Every status change is recorded with timestamp and actor identity, enabling complete audit reconstruction.
- **SC-005**: Reviewers can process the approval queue 5x faster compared to reviewing individual duplicates (reduced from 100 items to approximately 20 unique suggestions for typical failure bursts).
- **SC-006**: System maintains greater than 99% accuracy in merge decisions (similar patterns merged, dissimilar patterns kept separate) as validated by manual spot-check of 50 samples.

## Assumptions

- Failure patterns from Issue #2 (Pattern Extraction) are available as input to this system.
- The similarity threshold of 85% provides acceptable balance between aggressive merging (false positives) and under-merging (too many duplicates). This can be tuned via configuration.
- Single-project scope is sufficient for hackathon; cross-project deduplication is out of scope.
- Embeddings are generated from the combination of failure type and trigger condition text.
- The system processes patterns asynchronously in batches rather than real-time streaming.
- Actor identity for audit trails comes from the API caller context (API key or authenticated user).

## Clarifications

### Session 2025-12-28

- Q: What level of observability is required for the deduplication service? → A: Structured logging with key metrics (merge decisions, similarity scores, processing times)
- Q: How is this service triggered to process new failure patterns from Issue #2? → A: Poll Firestore for unprocessed patterns (async, decoupled, batch-friendly)
- Q: What rate limiting strategy should be used for the embedding service? → A: Limit batch size to 20 patterns with exponential backoff on throttling

## Out of Scope

- Manual pattern merging UI (auto-merge only for hackathon)
- Pattern splitting (once merged, stays merged)
- Cross-project deduplication (single project scope)
- Real-time similarity updates when existing suggestions are modified
- Configurable similarity thresholds per user or per failure type
