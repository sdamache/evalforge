"""Firestore repository for runbook draft generation.

Handles storage and retrieval of runbook drafts embedded on Suggestion documents
at `suggestion_content.runbook_snippet`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.common.config import FirestoreConfig
from src.common.firestore import (
    FirestoreError,
    failure_patterns_collection,
    get_firestore_client,
    runbook_errors_collection,
    runbook_runs_collection,
    suggestions_collection,
)
from src.generators.runbooks.models import RunbookError, RunbookRunSummary


FirestoreRepositoryError = FirestoreError


class FirestoreRepository:
    """Repository for runbook generator Firestore operations.

    Queries for type="runbook" suggestions and writes to
    suggestion_content.runbook_snippet.
    """

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
    def runbook_runs_collection_name(self) -> str:
        return runbook_runs_collection(self.config.collection_prefix)

    @property
    def runbook_errors_collection_name(self) -> str:
        return runbook_errors_collection(self.config.collection_prefix)

    def get_suggestions(
        self,
        *,
        batch_size: int,
        suggestion_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get pending runbook-type suggestions for generation.

        Args:
            batch_size: Maximum number of suggestions to return
            suggestion_ids: Optional specific IDs to fetch

        Returns:
            List of suggestion documents
        """
        client = self._get_client()
        collection = client.collection(self.suggestions_collection_name)

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

        try:
            from google.cloud.firestore import Query  # type: ignore[import-not-found]

            query = (
                collection.where("type", "==", "runbook")
                .where("status", "==", "pending")
                .order_by("created_at", direction=Query.DESCENDING)
                .limit(batch_size)
            )
        except Exception:
            query = (
                collection.where("type", "==", "runbook").where("status", "==", "pending").limit(batch_size)
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
            Suggestion document or None if not found
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
        """Get failure patterns by IDs for runbook context.

        Args:
            pattern_ids: List of pattern IDs to fetch

        Returns:
            List of failure pattern documents
        """
        client = self._get_client()
        collection = client.collection(self.failure_patterns_collection_name)

        patterns: List[Dict[str, Any]] = []
        for pattern_id in pattern_ids:
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

    def write_runbook_draft(self, *, suggestion_id: str, runbook: Dict[str, Any]) -> None:
        """Write runbook draft to suggestion document.

        Updates suggestion_content.runbook_snippet with the generated runbook.

        Args:
            suggestion_id: Target suggestion document ID
            runbook: Runbook draft data to embed

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
                "suggestion_content.runbook_snippet": runbook,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def save_run_summary(self, summary: RunbookRunSummary) -> None:
        """Save batch run summary for observability (FR-008).

        Args:
            summary: Run summary to persist
        """
        client = self._get_client()
        collection = client.collection(self.runbook_runs_collection_name)
        collection.document(summary.run_id).set(summary.to_dict())

    def save_error(self, error: RunbookError) -> None:
        """Save per-suggestion error for diagnostics (FR-008).

        Args:
            error: Error record to persist
        """
        client = self._get_client()
        collection = client.collection(self.runbook_errors_collection_name)
        doc_id = f"{error.run_id}:{error.suggestion_id}"
        collection.document(doc_id).set(error.to_dict())

    def get_last_run_summary(self) -> Optional[Dict[str, Any]]:
        """Get the most recent run summary for health check.

        Returns:
            Last run summary or None if no runs exist
        """
        client = self._get_client()
        collection = client.collection(self.runbook_runs_collection_name)
        try:
            from google.cloud.firestore import Query  # type: ignore[import-not-found]

            query = collection.order_by("started_at", direction=Query.DESCENDING).limit(1)
        except Exception:
            query = collection.limit(1)

        for snapshot in query.stream():
            data = snapshot.to_dict() or {}
            data.setdefault("run_id", snapshot.id)
            return data
        return None

    def get_pending_runbook_suggestions_count(self) -> int:
        """Count pending runbook suggestions for health check.

        Returns:
            Number of pending runbook-type suggestions
        """
        client = self._get_client()
        collection = client.collection(self.suggestions_collection_name)
        query = collection.where("type", "==", "runbook").where("status", "==", "pending")
        return sum(1 for _ in query.stream())

    def get_runbook_artifact(self, suggestion_id: str) -> Optional[Dict[str, Any]]:
        """Get runbook artifact with approval metadata for retrieval endpoint.

        Args:
            suggestion_id: Target suggestion ID

        Returns:
            Dict with suggestion_status, approval_metadata, and runbook_snippet
            or None if suggestion not found
        """
        suggestion = self.get_suggestion(suggestion_id)
        if not suggestion:
            return None

        suggestion_content = suggestion.get("suggestion_content", {}) or {}
        runbook_snippet = suggestion_content.get("runbook_snippet")

        if not runbook_snippet:
            return None

        return {
            "suggestion_id": suggestion_id,
            "suggestion_status": suggestion.get("status", "pending"),
            "approval_metadata": suggestion.get("approval_metadata"),
            "runbook": runbook_snippet,
        }
