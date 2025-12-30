"""Firestore repository for eval test draft generation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.common.config import FirestoreConfig
from src.common.firestore import (
    FirestoreError,
    eval_test_errors_collection,
    eval_test_runs_collection,
    failure_patterns_collection,
    get_firestore_client,
    suggestions_collection,
)
from src.generators.eval_tests.models import EvalTestError, EvalTestRunSummary


FirestoreRepositoryError = FirestoreError


class FirestoreRepository:
    """Repository for eval test generator Firestore operations."""

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
    def eval_test_runs_collection_name(self) -> str:
        return eval_test_runs_collection(self.config.collection_prefix)

    @property
    def eval_test_errors_collection_name(self) -> str:
        return eval_test_errors_collection(self.config.collection_prefix)

    def get_suggestions(
        self,
        *,
        batch_size: int,
        suggestion_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
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
                collection.where("type", "==", "eval")
                .where("status", "==", "pending")
                .order_by("created_at", direction=Query.DESCENDING)
                .limit(batch_size)
            )
        except Exception:
            query = (
                collection.where("type", "==", "eval").where("status", "==", "pending").limit(batch_size)
            )

        suggestions: List[Dict[str, Any]] = []
        for snapshot in query.stream():
            data = snapshot.to_dict() or {}
            data.setdefault("suggestion_id", snapshot.id)
            suggestions.append(data)
        return suggestions

    def get_suggestion(self, suggestion_id: str) -> Optional[Dict[str, Any]]:
        client = self._get_client()
        collection = client.collection(self.suggestions_collection_name)
        snapshot = collection.document(suggestion_id).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        data.setdefault("suggestion_id", snapshot.id)
        return data

    def get_failure_patterns(self, pattern_ids: List[str]) -> List[Dict[str, Any]]:
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

    def write_eval_test_draft(self, *, suggestion_id: str, eval_test: Dict[str, Any]) -> None:
        client = self._get_client()
        collection = client.collection(self.suggestions_collection_name)

        doc_ref = collection.document(suggestion_id)
        snapshot = doc_ref.get()
        if not snapshot.exists:
            raise FirestoreRepositoryError(f"Suggestion not found: {suggestion_id}")

        doc_ref.update(
            {
                "suggestion_content.eval_test": eval_test,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def save_run_summary(self, summary: EvalTestRunSummary) -> None:
        client = self._get_client()
        collection = client.collection(self.eval_test_runs_collection_name)
        collection.document(summary.run_id).set(summary.to_dict())

    def save_error(self, error: EvalTestError) -> None:
        client = self._get_client()
        collection = client.collection(self.eval_test_errors_collection_name)
        doc_id = f"{error.run_id}:{error.suggestion_id}"
        collection.document(doc_id).set(error.to_dict())

    def get_last_run_summary(self) -> Optional[Dict[str, Any]]:
        client = self._get_client()
        collection = client.collection(self.eval_test_runs_collection_name)
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

    def get_pending_eval_suggestions_count(self) -> int:
        client = self._get_client()
        collection = client.collection(self.suggestions_collection_name)
        query = collection.where("type", "==", "eval").where("status", "==", "pending")
        return sum(1 for _ in query.stream())
