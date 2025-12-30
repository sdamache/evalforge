"""Firestore repository for guardrail draft generation.

Handles:
- Reading guardrail-type suggestions (type=="guardrail")
- Reading failure patterns for canonical source selection
- Writing guardrail drafts to suggestion_content.guardrail
- Writing run summaries and error records
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.common.config import FirestoreConfig
from src.common.firestore import (
    FirestoreError,
    failure_patterns_collection,
    get_firestore_client,
    guardrail_errors_collection,
    guardrail_runs_collection,
    suggestions_collection,
)
from src.generators.guardrails.models import GuardrailError, GuardrailRunSummary


FirestoreRepositoryError = FirestoreError


class FirestoreRepository:
    """Repository for guardrail generator Firestore operations."""

    def __init__(self, config: FirestoreConfig):
        self.config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = get_firestore_client(self.config)
        return self._client

    @property
    def suggestions_collection_name(self) -> str:
        return suggestions_collection(self.config.collection_prefix)

    @property
    def failure_patterns_collection_name(self) -> str:
        return failure_patterns_collection(self.config.collection_prefix)

    @property
    def guardrail_runs_collection_name(self) -> str:
        return guardrail_runs_collection(self.config.collection_prefix)

    @property
    def guardrail_errors_collection_name(self) -> str:
        return guardrail_errors_collection(self.config.collection_prefix)

    def get_suggestions(
        self,
        *,
        batch_size: int,
        suggestion_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get pending guardrail-type suggestions for generation.

        Args:
            batch_size: Maximum number of suggestions to return
            suggestion_ids: Optional list of specific suggestion IDs to fetch

        Returns:
            List of suggestion documents with suggestion_id field set
        """
        client = self._get_client()
        collection = client.collection(self.suggestions_collection_name)

        # If specific IDs requested, fetch those directly
        if suggestion_ids:
            suggestions: List[Dict[str, Any]] = []
            for suggestion_id in suggestion_ids[:batch_size]:
                snapshot = collection.document(suggestion_id).get()
                if not snapshot.exists:
                    continue
                data = snapshot.to_dict() or {}
                data.setdefault("suggestion_id", snapshot.id)
                suggestions.append(data)
            return suggestions

        # Query for pending guardrail-type suggestions
        try:
            from google.cloud.firestore import Query  # type: ignore[import-not-found]

            query = (
                collection.where("type", "==", "guardrail")
                .where("status", "==", "pending")
                .order_by("created_at", direction=Query.DESCENDING)
                .limit(batch_size)
            )
        except Exception:
            # Fallback without ordering if Query import fails
            query = (
                collection.where("type", "==", "guardrail")
                .where("status", "==", "pending")
                .limit(batch_size)
            )

        suggestions: List[Dict[str, Any]] = []
        for snapshot in query.stream():
            data = snapshot.to_dict() or {}
            data.setdefault("suggestion_id", snapshot.id)
            suggestions.append(data)
        return suggestions

    def get_suggestion(self, suggestion_id: str) -> Optional[Dict[str, Any]]:
        """Get a single suggestion by ID.

        Args:
            suggestion_id: The suggestion document ID

        Returns:
            Suggestion document dict or None if not found
        """
        client = self._get_client()
        collection = client.collection(self.suggestions_collection_name)
        snapshot = collection.document(suggestion_id).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        data.setdefault("suggestion_id", snapshot.id)
        return data

    def get_failure_patterns(self, pattern_ids: List[str]) -> List[Dict[str, Any]]:
        """Get failure patterns by IDs for canonical source selection.

        Args:
            pattern_ids: List of pattern IDs to fetch

        Returns:
            List of pattern documents with pattern_id field set
        """
        client = self._get_client()
        collection = client.collection(self.failure_patterns_collection_name)

        patterns: List[Dict[str, Any]] = []
        for pattern_id in pattern_ids:
            # Handle pattern_ prefix normalization
            doc_id = pattern_id
            if pattern_id.startswith("pattern_"):
                doc_id = pattern_id[len("pattern_") :]
            snapshot = collection.document(doc_id).get()
            if not snapshot.exists:
                continue
            data = snapshot.to_dict() or {}
            data.setdefault("pattern_id", pattern_id)
            data.setdefault("source_trace_id", snapshot.id)
            patterns.append(data)
        return patterns

    def write_guardrail_draft(
        self, *, suggestion_id: str, guardrail: Dict[str, Any]
    ) -> None:
        """Write a guardrail draft to a suggestion document.

        Args:
            suggestion_id: The suggestion document ID
            guardrail: The guardrail draft dict to write

        Raises:
            FirestoreRepositoryError: If suggestion not found
        """
        client = self._get_client()
        collection = client.collection(self.suggestions_collection_name)

        doc_ref = collection.document(suggestion_id)
        snapshot = doc_ref.get()
        if not snapshot.exists:
            raise FirestoreRepositoryError(f"Suggestion not found: {suggestion_id}")

        doc_ref.update(
            {
                "suggestion_content.guardrail": guardrail,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def save_run_summary(self, summary: GuardrailRunSummary) -> None:
        """Save a batch run summary document.

        Args:
            summary: The run summary to save
        """
        client = self._get_client()
        collection = client.collection(self.guardrail_runs_collection_name)
        collection.document(summary.run_id).set(summary.to_dict())

    def save_error(self, error: GuardrailError) -> None:
        """Save a per-suggestion error document.

        Args:
            error: The error record to save
        """
        client = self._get_client()
        collection = client.collection(self.guardrail_errors_collection_name)
        doc_id = f"{error.run_id}:{error.suggestion_id}"
        collection.document(doc_id).set(error.to_dict())

    def get_last_run_summary(self) -> Optional[Dict[str, Any]]:
        """Get the most recent run summary for health check.

        Returns:
            Last run summary dict or None if no runs exist
        """
        client = self._get_client()
        collection = client.collection(self.guardrail_runs_collection_name)
        try:
            from google.cloud.firestore import Query  # type: ignore[import-not-found]

            query = collection.order_by(
                "started_at", direction=Query.DESCENDING
            ).limit(1)
        except Exception:
            query = collection.limit(1)

        for snapshot in query.stream():
            data = snapshot.to_dict() or {}
            data.setdefault("run_id", snapshot.id)
            return data
        return None

    def get_pending_guardrail_suggestions_count(self) -> int:
        """Count pending guardrail-type suggestions for health check.

        Returns:
            Number of pending guardrail suggestions
        """
        client = self._get_client()
        collection = client.collection(self.suggestions_collection_name)
        query = (
            collection.where("type", "==", "guardrail")
            .where("status", "==", "pending")
        )
        return sum(1 for _ in query.stream())
