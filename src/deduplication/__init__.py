"""Suggestion deduplication service.

This package contains the Cloud Run deduplication service that reads unprocessed
failure patterns from Firestore, computes text embeddings via Vertex AI,
clusters similar patterns into suggestions using cosine similarity (>0.85),
and maintains lineage tracking and audit trails for approval workflows.

Shared Utilities (from src/common/):
    - config: load_deduplication_settings(), DeduplicationSettings, EmbeddingConfig
    - firestore: get_firestore_client(), suggestions_collection()
    - logging: Structured logging for merge decisions and metrics

Modules:
    models: Pydantic models for Suggestion, StatusHistoryEntry, SourceTraceEntry
    similarity: Cosine similarity computation and best match finding
    embedding_client: Vertex AI text embeddings with caching and retry
    deduplication_service: Core deduplication logic (find-or-create, merge)
    firestore_repository: Suggestion CRUD operations
    main: FastAPI app with /health and /dedup/run-once endpoints
"""

from src.deduplication.models import (
    Suggestion,
    SuggestionType,
    SuggestionStatus,
    StatusHistoryEntry,
    SourceTraceEntry,
    PatternSummary,
    SuggestionContent,
    ApprovalMetadata,
    DeduplicationRunRequest,
    DeduplicationRunSummary,
    PatternOutcome,
    PatternOutcomeStatus,
)

__all__ = [
    "Suggestion",
    "SuggestionType",
    "SuggestionStatus",
    "StatusHistoryEntry",
    "SourceTraceEntry",
    "PatternSummary",
    "SuggestionContent",
    "ApprovalMetadata",
    "DeduplicationRunRequest",
    "DeduplicationRunSummary",
    "PatternOutcome",
    "PatternOutcomeStatus",
]
