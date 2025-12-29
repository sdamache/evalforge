"""Firestore repository helpers for extraction service.

Handles:
- Reading unprocessed traces from evalforge_raw_traces (T018)
- Writing/upserting patterns to evalforge_failure_patterns (T019)
- Marking traces as processed (T021)
- Persisting run summaries to evalforge_extraction_runs (T022)
- Persisting error records to evalforge_extraction_errors

Uses shared Firestore utilities from src/common/firestore.py.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.common.config import FirestoreConfig
from src.common.firestore import (
    FirestoreError,
    get_firestore_client,
    extraction_errors_collection,
    extraction_runs_collection,
    failure_patterns_collection,
    raw_traces_collection,
)
from src.extraction.models import (
    ExtractionError,
    ExtractionRunSummary,
    FailurePattern,
)

logger = logging.getLogger(__name__)


# Re-export FirestoreError as FirestoreRepositoryError for backward compatibility
FirestoreRepositoryError = FirestoreError


class FirestoreRepository:
    """Repository for extraction-related Firestore operations.

    Collections used:
    - {prefix}raw_traces: Input traces (read, update processed flag)
    - {prefix}failure_patterns: Output patterns (write/upsert)
    - {prefix}extraction_runs: Run summaries (write)
    - {prefix}extraction_errors: Error records (write)
    """

    def __init__(self, config: FirestoreConfig):
        """Initialize the repository.

        Args:
            config: Firestore configuration with collection prefix.
        """
        self.config = config
        self._client = None

    def _get_client(self):
        """Lazy-load the Firestore client using shared helper."""
        if self._client is None:
            self._client = get_firestore_client(self.config)
        return self._client

    @property
    def raw_traces_collection_name(self) -> str:
        """Collection name for raw traces."""
        return raw_traces_collection(self.config.collection_prefix)

    @property
    def failure_patterns_collection_name(self) -> str:
        """Collection name for failure patterns."""
        return failure_patterns_collection(self.config.collection_prefix)

    @property
    def extraction_runs_collection_name(self) -> str:
        """Collection name for extraction run summaries."""
        return extraction_runs_collection(self.config.collection_prefix)

    @property
    def extraction_errors_collection_name(self) -> str:
        """Collection name for extraction error records."""
        return extraction_errors_collection(self.config.collection_prefix)

    # ========================================================================
    # T018: Query for unprocessed traces
    # ========================================================================

    def get_unprocessed_traces(
        self,
        batch_size: int,
        trace_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch unprocessed traces from Firestore.

        Args:
            batch_size: Maximum number of traces to fetch.
            trace_ids: Optional explicit list of trace IDs to fetch
                      (overrides processed=false query).

        Returns:
            List of trace documents as dicts.
        """
        client = self._get_client()
        collection = client.collection(self.raw_traces_collection_name)

        if trace_ids:
            # Explicit trace IDs requested
            traces = []
            for trace_id in trace_ids[:batch_size]:
                doc = collection.document(trace_id).get()
                if doc.exists:
                    trace_data = doc.to_dict()
                    trace_data["trace_id"] = doc.id
                    traces.append(trace_data)
            return traces

        # Query for unprocessed traces
        query = collection.where("processed", "==", False).limit(batch_size)

        traces = []
        for doc in query.stream():
            trace_data = doc.to_dict()
            trace_data["trace_id"] = doc.id
            traces.append(trace_data)

        return traces

    # ========================================================================
    # T019: Upsert extracted patterns
    # ========================================================================

    def upsert_failure_pattern(self, pattern: FailurePattern) -> None:
        """Upsert a failure pattern to Firestore.

        Uses source_trace_id as document ID for idempotent writes
        (re-processing the same trace overwrites the same document).

        Sets processed=False so deduplication service can pick up new patterns.

        Args:
            pattern: The validated FailurePattern to store.
        """
        client = self._get_client()
        collection = client.collection(self.failure_patterns_collection_name)

        # Document ID is source_trace_id for idempotency
        doc_ref = collection.document(pattern.source_trace_id)

        # Add processed=False for deduplication service to query
        pattern_data = pattern.to_dict()
        pattern_data["processed"] = False

        doc_ref.set(pattern_data)

        logger.info(
            "pattern_stored",
            extra={
                "event": "pattern_stored",
                "pattern_id": pattern.pattern_id,
                "source_trace_id": pattern.source_trace_id,
            },
        )

    # ========================================================================
    # T021: Mark trace as processed
    # ========================================================================

    def mark_trace_processed(self, trace_id: str) -> None:
        """Mark a trace as processed after successful pattern extraction.

        Args:
            trace_id: The trace ID to mark as processed.
        """
        client = self._get_client()
        collection = client.collection(self.raw_traces_collection_name)

        doc_ref = collection.document(trace_id)
        doc_ref.update({
            "processed": True,
            "processed_at": datetime.now(tz=timezone.utc).isoformat(),
        })

        logger.info(
            "trace_marked_processed",
            extra={
                "event": "trace_marked_processed",
                "trace_id": trace_id,
            },
        )

    # ========================================================================
    # T022: Persist run summary
    # ========================================================================

    def save_run_summary(self, summary: ExtractionRunSummary) -> None:
        """Persist an extraction run summary.

        Args:
            summary: The run summary to persist.
        """
        client = self._get_client()
        collection = client.collection(self.extraction_runs_collection_name)

        doc_ref = collection.document(summary.run_id)
        doc_ref.set(summary.to_dict())

        logger.info(
            "run_summary_saved",
            extra={
                "event": "run_summary_saved",
                "run_id": summary.run_id,
                "stored_count": summary.stored_count,
                "error_count": summary.error_count,
            },
        )

    # ========================================================================
    # Error record persistence
    # ========================================================================

    def save_extraction_error(self, error: ExtractionError) -> None:
        """Persist an extraction error record.

        Args:
            error: The error record to persist.
        """
        client = self._get_client()
        collection = client.collection(self.extraction_errors_collection_name)

        # Document ID combines run_id and trace_id
        doc_id = f"{error.run_id}:{error.source_trace_id}"
        doc_ref = collection.document(doc_id)
        doc_ref.set(error.to_dict())

        logger.info(
            "extraction_error_saved",
            extra={
                "event": "extraction_error_saved",
                "run_id": error.run_id,
                "source_trace_id": error.source_trace_id,
                "error_type": error.error_type.value,
            },
        )

    # ========================================================================
    # Health check helpers
    # ========================================================================

    def get_unprocessed_count(self) -> int:
        """Get count of unprocessed traces (for health endpoint).

        Returns:
            Number of traces with processed=false.
        """
        client = self._get_client()
        collection = client.collection(self.raw_traces_collection_name)

        # Count query
        query = collection.where("processed", "==", False)
        count = sum(1 for _ in query.stream())
        return count

    def get_last_run_summary(self) -> Optional[Dict[str, Any]]:
        """Get the most recent run summary (for health endpoint).

        Returns:
            Most recent run summary as dict, or None if no runs.
        """
        client = self._get_client()
        collection = client.collection(self.extraction_runs_collection_name)

        # Query for most recent run
        query = collection.order_by("started_at", direction="DESCENDING").limit(1)

        for doc in query.stream():
            return doc.to_dict()

        return None


def create_firestore_repository(config: FirestoreConfig) -> FirestoreRepository:
    """Factory function to create a FirestoreRepository.

    Args:
        config: Firestore configuration.

    Returns:
        Configured FirestoreRepository instance.
    """
    return FirestoreRepository(config)
