# Implementation Plan: Suggestion Storage and Deduplication

**Branch**: `003-suggestion-deduplication` | **Date**: 2025-12-28 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-suggestion-deduplication/spec.md`

## Summary

Build a deduplication service that clusters similar failure patterns into single suggestions, reducing approval queue from ~100 duplicates to ~20 unique items. Uses Vertex AI text embeddings (text-embedding-004) with cosine similarity (threshold 0.85) to detect duplicates. Polls Firestore for unprocessed patterns in batches of 20, merges similar patterns into existing suggestions, and maintains full lineage tracking and audit trails.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: FastAPI, google-cloud-firestore, google-cloud-aiplatform, numpy, tenacity, pydantic
**Storage**: Firestore collections `evalforge_failure_patterns` (input), `evalforge_suggestions` (output)
**Testing**: pytest with RUN_LIVE_TESTS=1 for integration tests (minimal mode - live tests only, no mocks)
**Target Platform**: Google Cloud Run (serverless, stateless)
**Project Type**: Single project (extends existing src/ structure)
**Performance Goals**: <2 seconds for dashboard queries with 1000+ suggestions; batch processing 20 patterns in <30 seconds
**Constraints**: 20 patterns/batch to respect Vertex AI rate limits; exponential backoff on 429 errors
**Scale/Scope**: 1000+ suggestions, single project scope

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| **Observability-First Insight Trail** | PASS | FR-013/FR-014 require structured logging for merge decisions, similarity scores, processing metrics |
| **Human-Governed Fail-Safe Loops** | PASS | All suggestions created with "pending" status (FR-003); requires explicit approval; audit trails (FR-005) |
| **Cost-Conscious Experimentation** | PASS | Batch size limited to 20 (FR-017); embedding caching (FR-007); exponential backoff prevents quota exhaustion |
| **Reliability & Cognitive Ease** | PASS | 3x retry with exponential backoff (FR-018); patterns queued on failure (FR-009); <2s query performance (FR-006) |
| **Demo-Ready Transparency & UX** | PASS | Lineage tracking shows contributing traces (FR-004); status history enables audit reconstruction |
| **Platform Constraints** | PASS | Cloud Run compatible (stateless batch processing); Vertex AI for embeddings; Firestore for storage |
| **Workflow & Quality Gates** | PASS | Live integration tests only (minimal mode); no mocks per constitution |

**Gate Result**: PASSED - No violations. Proceed to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/003-suggestion-deduplication/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── deduplication-openapi.yaml
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
src/
├── common/              # Existing shared utilities
│   ├── config.py        # Add deduplication config
│   ├── firestore.py     # Add suggestions_collection helper
│   └── logging.py       # Reuse for structured logging
├── extraction/          # Existing - provides FailurePattern input
│   └── models.py        # FailurePattern, Severity, FailureType enums
├── deduplication/       # NEW - this feature
│   ├── __init__.py
│   ├── main.py          # FastAPI service with /health and /dedup/run-once
│   ├── models.py        # Suggestion, StatusHistoryEntry, DeduplicationResult
│   ├── embedding_client.py  # Vertex AI embeddings with caching
│   ├── similarity.py    # Cosine similarity computation
│   ├── deduplication_service.py  # Core deduplication logic
│   └── firestore_repository.py   # Suggestion CRUD operations
└── api/                 # Existing - will consume suggestions in future issues

tests/
├── integration/
│   └── test_deduplication_live.py  # Live tests hitting real Vertex AI + Firestore
└── contract/
    └── test_deduplication_contracts.py  # Schema validation tests
```

**Structure Decision**: Extends existing single-project structure with new `src/deduplication/` module. Follows established patterns from `src/extraction/` (models, main, firestore_repository).

## Complexity Tracking

> No violations identified. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| - | - | - |

## Deferred Decisions

| Decision | Reason Deferred | Impact if Deferred |
|----------|-----------------|-------------------|
| Configurable threshold per failure type | Out of scope for hackathon | Single 0.85 threshold may be suboptimal for some failure types; can tune later |
| Cross-project deduplication | Explicitly out of scope | Limited to single project; acceptable for hackathon demo |
| Pattern splitting | Out of scope | Once merged, cannot unmerge; acceptable tradeoff for simplicity |
