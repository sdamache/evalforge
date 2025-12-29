"""Core deduplication service for clustering failure patterns into suggestions.

Implements the main deduplication workflow:
1. Fetch unprocessed patterns from Firestore
2. Generate embeddings via Vertex AI
3. Compare with existing suggestions using cosine similarity
4. Merge (>85% similarity) or create new suggestion
5. Mark patterns as processed

Per spec.md User Story 1:
- Automatically check if similar suggestion exists
- Merge when similarity exceeds 85%
- Create new suggestion with pending status otherwise
"""

from datetime import datetime
from typing import List, Optional, Tuple
import logging
import time
import uuid

import numpy as np

from src.common.config import DeduplicationSettings, load_deduplication_settings
from src.deduplication.embedding_client import EmbeddingClient, EmbeddingServiceError
from src.deduplication.firestore_repository import SuggestionRepository
from src.deduplication.models import (
    DeduplicationRunSummary,
    PatternOutcome,
    PatternOutcomeStatus,
    SuggestionType,
    TriggeredBy,
)
from src.deduplication.similarity import find_best_match
from src.extraction.models import FailurePattern

logger = logging.getLogger(__name__)


class DeduplicationServiceError(Exception):
    """Base exception for deduplication service errors."""

    pass


class DeduplicationService:
    """Service for deduplicating failure patterns into suggestions.

    Provides:
    - Batch processing of unprocessed patterns
    - Embedding generation and similarity comparison
    - Merge or create decision logic
    - Structured logging for observability (FR-013, FR-014)

    Usage:
        service = DeduplicationService()
        summary = service.process_batch(batch_size=20)
    """

    def __init__(
        self,
        settings: Optional[DeduplicationSettings] = None,
        embedding_client: Optional[EmbeddingClient] = None,
        repository: Optional[SuggestionRepository] = None,
    ):
        """Initialize the deduplication service.

        Args:
            settings: Optional DeduplicationSettings. Loads from env if not provided.
            embedding_client: Optional EmbeddingClient. Creates one if not provided.
            repository: Optional SuggestionRepository. Creates one if not provided.
        """
        self.settings = settings or load_deduplication_settings()
        self.embedding_client = embedding_client or EmbeddingClient(
            config=self.settings.embedding
        )
        self.repository = repository or SuggestionRepository(
            config=self.settings.firestore
        )

    def _generate_embedding_text(self, pattern: FailurePattern) -> str:
        """Generate text for embedding from a failure pattern (T015).

        Combines failure_type and trigger_condition for semantic representation.
        Per research.md: "Embeddings are generated from the combination of
        failure type and trigger condition text"

        Args:
            pattern: FailurePattern to generate text for.

        Returns:
            Formatted text string for embedding generation.

        Example:
            "hallucination: User asks for product recommendation without category"
        """
        return f"{pattern.failure_type.value}: {pattern.trigger_condition}"

    def _find_or_create_suggestion(
        self,
        pattern: FailurePattern,
        embedding: np.ndarray,
        existing_embeddings: List[Tuple[str, np.ndarray]],
    ) -> Tuple[str, PatternOutcomeStatus, Optional[float]]:
        """Find matching suggestion or create new one (T016).

        Implements FR-001, FR-002, FR-003:
        - FR-001: Compute semantic similarity using embeddings
        - FR-002: Merge when similarity exceeds threshold (85%)
        - FR-003: Create new with pending status when no match

        Args:
            pattern: FailurePattern to process.
            embedding: Pre-computed embedding for the pattern.
            existing_embeddings: List of (suggestion_id, embedding) tuples.

        Returns:
            Tuple of (suggestion_id, outcome_status, similarity_score).
            similarity_score is None for new suggestions.
        """
        # Find best match above threshold
        match = find_best_match(
            new_embedding=embedding,
            existing_embeddings=existing_embeddings,
            threshold=self.settings.similarity_threshold,
        )

        if match is not None:
            # Merge into existing suggestion (FR-002)
            suggestion_id, similarity_score = match
            self.repository.merge_into_suggestion(
                suggestion_id=suggestion_id,
                pattern=pattern,
                similarity_score=similarity_score,
            )

            # Log merge decision (FR-013)
            logger.info(
                "Merged pattern into existing suggestion",
                extra={
                    "pattern_id": pattern.pattern_id,
                    "suggestion_id": suggestion_id,
                    "similarity_score": round(similarity_score, 4),
                    "decision": "merged",
                    "threshold": self.settings.similarity_threshold,
                },
            )

            return suggestion_id, PatternOutcomeStatus.MERGED, similarity_score
        else:
            # Create new suggestion (FR-003)
            suggestion = self.repository.create_suggestion(
                pattern=pattern,
                embedding=embedding.tolist(),
                suggestion_type=self._determine_suggestion_type(pattern),
            )

            # Log create decision (FR-013)
            logger.info(
                "Created new suggestion from pattern",
                extra={
                    "pattern_id": pattern.pattern_id,
                    "suggestion_id": suggestion.suggestion_id,
                    "similarity_score": None,
                    "decision": "created_new",
                    "threshold": self.settings.similarity_threshold,
                },
            )

            return suggestion.suggestion_id, PatternOutcomeStatus.CREATED_NEW, None

    def _determine_suggestion_type(self, pattern: FailurePattern) -> SuggestionType:
        """Determine suggestion type based on failure pattern.

        Default heuristic: most failures map to eval test cases.
        Future: Could use more sophisticated classification.

        Args:
            pattern: FailurePattern to classify.

        Returns:
            SuggestionType (eval, guardrail, or runbook).
        """
        # Simple heuristic: runaway loops -> guardrails, others -> evals
        from src.extraction.models import FailureType

        if pattern.failure_type == FailureType.RUNAWAY_LOOP:
            return SuggestionType.GUARDRAIL
        elif pattern.failure_type == FailureType.INFRASTRUCTURE_ERROR:
            return SuggestionType.RUNBOOK
        else:
            return SuggestionType.EVAL

    def process_batch(
        self,
        batch_size: Optional[int] = None,
        triggered_by: TriggeredBy = TriggeredBy.MANUAL,
        dry_run: bool = False,
    ) -> DeduplicationRunSummary:
        """Process a batch of unprocessed patterns (T014).

        Main entry point for deduplication. Fetches patterns, generates embeddings,
        compares with existing suggestions, and either merges or creates new.

        Args:
            batch_size: Max patterns to process (default from settings).
            triggered_by: How this run was initiated.
            dry_run: If True, compute but don't persist changes.

        Returns:
            DeduplicationRunSummary with processing statistics.
        """
        start_time = time.time()
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        started_at = datetime.utcnow()

        batch_size = batch_size or self.settings.batch_size

        logger.info(
            "Starting deduplication batch",
            extra={
                "run_id": run_id,
                "batch_size": batch_size,
                "triggered_by": triggered_by.value,
                "dry_run": dry_run,
            },
        )

        # Fetch pending patterns (FR-015)
        patterns = self.repository.get_pending_patterns(limit=batch_size)

        if not patterns:
            logger.info("No pending patterns to process", extra={"run_id": run_id})
            return self._create_summary(
                run_id=run_id,
                started_at=started_at,
                triggered_by=triggered_by,
                patterns_processed=0,
                suggestions_created=0,
                suggestions_merged=0,
                embedding_errors=0,
                pattern_outcomes=[],
                merge_scores=[],
                start_time=start_time,
            )

        # Get existing suggestion embeddings for comparison
        existing_embeddings = self.repository.get_all_suggestion_embeddings()

        # Process each pattern
        pattern_outcomes: List[PatternOutcome] = []
        suggestions_created = 0
        suggestions_merged = 0
        embedding_errors = 0
        merge_scores: List[float] = []

        for pattern in patterns:
            try:
                # Generate embedding text and compute embedding
                text = self._generate_embedding_text(pattern)
                embedding = self.embedding_client.get_embedding_as_array(text)

                if not dry_run:
                    # Find or create suggestion
                    suggestion_id, status, score = self._find_or_create_suggestion(
                        pattern=pattern,
                        embedding=embedding,
                        existing_embeddings=existing_embeddings,
                    )

                    # Update counters
                    if status == PatternOutcomeStatus.CREATED_NEW:
                        suggestions_created += 1
                        # Add new embedding to comparison set
                        existing_embeddings.append((suggestion_id, embedding))
                    elif status == PatternOutcomeStatus.MERGED:
                        suggestions_merged += 1
                        if score is not None:
                            merge_scores.append(score)

                    # Mark pattern as processed (FR-016)
                    self.repository.mark_pattern_processed(pattern.pattern_id)

                    pattern_outcomes.append(
                        PatternOutcome(
                            pattern_id=pattern.pattern_id,
                            status=status,
                            suggestion_id=suggestion_id,
                            similarity_score=score,
                        )
                    )
                else:
                    # Dry run - just compute what would happen
                    match = find_best_match(
                        new_embedding=embedding,
                        existing_embeddings=existing_embeddings,
                        threshold=self.settings.similarity_threshold,
                    )
                    if match:
                        status = PatternOutcomeStatus.MERGED
                        suggestion_id, score = match
                        merge_scores.append(score)
                    else:
                        status = PatternOutcomeStatus.CREATED_NEW
                        suggestion_id = f"sugg_dry_{pattern.pattern_id[-8:]}"
                        score = None

                    pattern_outcomes.append(
                        PatternOutcome(
                            pattern_id=pattern.pattern_id,
                            status=status,
                            suggestion_id=suggestion_id,
                            similarity_score=score,
                        )
                    )

            except EmbeddingServiceError as e:
                logger.error(
                    "Embedding generation failed",
                    extra={
                        "pattern_id": pattern.pattern_id,
                        "error": str(e),
                        "run_id": run_id,
                    },
                )
                embedding_errors += 1
                pattern_outcomes.append(
                    PatternOutcome(
                        pattern_id=pattern.pattern_id,
                        status=PatternOutcomeStatus.ERROR,
                        error_reason=str(e),
                    )
                )

            except Exception as e:
                logger.error(
                    "Pattern processing failed",
                    extra={
                        "pattern_id": pattern.pattern_id,
                        "error": str(e),
                        "run_id": run_id,
                    },
                )
                pattern_outcomes.append(
                    PatternOutcome(
                        pattern_id=pattern.pattern_id,
                        status=PatternOutcomeStatus.ERROR,
                        error_reason=str(e),
                    )
                )

        # Create summary
        summary = self._create_summary(
            run_id=run_id,
            started_at=started_at,
            triggered_by=triggered_by,
            patterns_processed=len(patterns),
            suggestions_created=suggestions_created,
            suggestions_merged=suggestions_merged,
            embedding_errors=embedding_errors,
            pattern_outcomes=pattern_outcomes,
            merge_scores=merge_scores,
            start_time=start_time,
        )

        # Log processing metrics (FR-014)
        self._log_processing_metrics(summary, merge_scores)

        return summary

    def _create_summary(
        self,
        run_id: str,
        started_at: datetime,
        triggered_by: TriggeredBy,
        patterns_processed: int,
        suggestions_created: int,
        suggestions_merged: int,
        embedding_errors: int,
        pattern_outcomes: List[PatternOutcome],
        merge_scores: List[float],
        start_time: float,
    ) -> DeduplicationRunSummary:
        """Create a DeduplicationRunSummary from processing results."""
        finished_at = datetime.utcnow()
        duration_ms = int((time.time() - start_time) * 1000)

        avg_similarity = None
        if merge_scores:
            avg_similarity = sum(merge_scores) / len(merge_scores)

        return DeduplicationRunSummary(
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            triggered_by=triggered_by,
            patterns_processed=patterns_processed,
            suggestions_created=suggestions_created,
            suggestions_merged=suggestions_merged,
            embedding_errors=embedding_errors if embedding_errors > 0 else None,
            average_similarity_score=round(avg_similarity, 4) if avg_similarity else None,
            processing_duration_ms=duration_ms,
            pattern_outcomes=pattern_outcomes if pattern_outcomes else None,
        )

    def _log_processing_metrics(
        self,
        summary: DeduplicationRunSummary,
        merge_scores: List[float],
    ) -> None:
        """Log processing metrics for observability (T020, FR-014).

        Args:
            summary: Completed run summary.
            merge_scores: List of similarity scores from merges.
        """
        merge_rate = 0.0
        if summary.patterns_processed > 0:
            merge_rate = summary.suggestions_merged / summary.patterns_processed

        logger.info(
            "Deduplication batch complete",
            extra={
                "run_id": summary.run_id,
                "patterns_processed": summary.patterns_processed,
                "suggestions_created": summary.suggestions_created,
                "suggestions_merged": summary.suggestions_merged,
                "merge_rate": round(merge_rate, 4),
                "average_similarity_score": summary.average_similarity_score,
                "processing_duration_ms": summary.processing_duration_ms,
                "embedding_errors": summary.embedding_errors or 0,
            },
        )
