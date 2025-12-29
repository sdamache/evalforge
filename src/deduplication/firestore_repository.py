"""Firestore repository for suggestion CRUD operations.

Provides data access layer for the deduplication service, handling:
- Suggestion CRUD (create, read, update, list)
- Pending pattern queries (processed=false)
- Pattern processing status updates
- Merge operations (append to source_traces)

Per data-model.md:
- Collection: evalforge_suggestions
- Document ID: suggestion_id (format: sugg_{uuid})
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import logging
import uuid

import numpy as np

from src.common.config import FirestoreConfig, load_firestore_config
from src.common.firestore import (
    get_firestore_client,
    failure_patterns_collection,
    suggestions_collection,
)
from src.deduplication.models import (
    Suggestion,
    SuggestionType,
    SuggestionStatus,
    StatusHistoryEntry,
    SourceTraceEntry,
    PatternSummary,
)
from src.extraction.models import FailurePattern, FailureType, Severity

if TYPE_CHECKING:
    from google.cloud.firestore import Client as FirestoreClient

# Import FieldFilter for modern Firestore query syntax (avoids deprecation warnings)
try:
    from google.cloud.firestore_v1.base_query import FieldFilter
except ImportError:
    # Fallback for older versions
    FieldFilter = None

logger = logging.getLogger(__name__)


def _where_filter(query, field: str, op: str, value):
    """Apply a where filter using the modern FieldFilter syntax if available.

    This avoids the deprecation warning: "Detected filter using positional arguments."
    """
    if FieldFilter is not None:
        return query.where(filter=FieldFilter(field, op, value))
    else:
        # Fallback for older versions (will show warning)
        return query.where(field, op, value)


class SuggestionRepositoryError(Exception):
    """Base exception for suggestion repository errors."""

    pass


class SuggestionNotFoundError(SuggestionRepositoryError):
    """Raised when a suggestion is not found."""

    pass


class SuggestionRepository:
    """Repository for Suggestion and FailurePattern Firestore operations.

    Provides:
    - Suggestion CRUD operations (create, read, update, list)
    - Pending pattern queries for deduplication processing
    - Pattern processing status updates
    - Merge operations for deduplication
    """

    def __init__(
        self,
        client: Optional["FirestoreClient"] = None,
        config: Optional[FirestoreConfig] = None,
    ):
        """Initialize the repository.

        Args:
            client: Optional Firestore client. If not provided, creates one.
            config: Optional FirestoreConfig. If not provided, loads from environment.
        """
        self.config = config or load_firestore_config()
        self._client = client

    @property
    def client(self) -> "FirestoreClient":
        """Get or create Firestore client."""
        if self._client is None:
            self._client = get_firestore_client(self.config)
        return self._client

    @property
    def suggestions_ref(self):
        """Get reference to suggestions collection."""
        return self.client.collection(suggestions_collection(self.config.collection_prefix))

    @property
    def patterns_ref(self):
        """Get reference to failure patterns collection."""
        return self.client.collection(failure_patterns_collection(self.config.collection_prefix))

    # =========================================================================
    # Suggestion CRUD Operations (T010)
    # =========================================================================

    def create_suggestion(
        self,
        pattern: FailurePattern,
        embedding: List[float],
        suggestion_type: SuggestionType = SuggestionType.EVAL,
    ) -> Suggestion:
        """Create a new suggestion from a failure pattern.

        Creates a suggestion with:
        - pending status
        - single source trace entry
        - initial version history entry

        Args:
            pattern: Source FailurePattern to create suggestion from.
            embedding: 768-dimensional embedding vector.
            suggestion_type: Type of suggestion (default: eval).

        Returns:
            Created Suggestion instance.

        Raises:
            SuggestionRepositoryError: If creation fails.
        """
        now = datetime.now(timezone.utc)
        suggestion_id = f"sugg_{uuid.uuid4().hex[:12]}"
        similarity_group = f"group_{uuid.uuid4().hex[:8]}"

        suggestion = Suggestion(
            suggestion_id=suggestion_id,
            type=suggestion_type,
            status=SuggestionStatus.PENDING,
            severity=pattern.severity,
            source_traces=[
                SourceTraceEntry(
                    trace_id=pattern.source_trace_id,
                    pattern_id=pattern.pattern_id,
                    added_at=now,
                    similarity_score=None,  # First trace has no similarity
                )
            ],
            pattern=PatternSummary(
                failure_type=pattern.failure_type,
                trigger_condition=pattern.trigger_condition,
                title=pattern.title,
                summary=pattern.summary,
            ),
            embedding=embedding,
            similarity_group=similarity_group,
            suggestion_content=None,
            approval_metadata=None,
            version_history=[
                StatusHistoryEntry(
                    previous_status=None,
                    new_status=SuggestionStatus.PENDING,
                    actor="system",
                    timestamp=now,
                    notes=f"Created from {pattern.pattern_id}",
                )
            ],
            created_at=now,
            updated_at=now,
        )

        try:
            self.suggestions_ref.document(suggestion_id).set(suggestion.to_dict())
            logger.info(
                "Created suggestion",
                extra={
                    "suggestion_id": suggestion_id,
                    "pattern_id": pattern.pattern_id,
                    "type": suggestion_type.value,
                },
            )
            return suggestion
        except Exception as e:
            raise SuggestionRepositoryError(f"Failed to create suggestion: {e}") from e

    def get_suggestion(self, suggestion_id: str) -> Optional[Suggestion]:
        """Get a suggestion by ID.

        Args:
            suggestion_id: Unique suggestion identifier.

        Returns:
            Suggestion instance or None if not found.
        """
        doc = self.suggestions_ref.document(suggestion_id).get()
        if not doc.exists:
            return None
        return self._doc_to_suggestion(doc.to_dict())

    def get_suggestion_or_raise(self, suggestion_id: str) -> Suggestion:
        """Get a suggestion by ID, raising if not found.

        Args:
            suggestion_id: Unique suggestion identifier.

        Returns:
            Suggestion instance.

        Raises:
            SuggestionNotFoundError: If suggestion not found.
        """
        suggestion = self.get_suggestion(suggestion_id)
        if suggestion is None:
            raise SuggestionNotFoundError(f"Suggestion not found: {suggestion_id}")
        return suggestion

    def _doc_to_suggestion(self, data: Dict[str, Any]) -> Suggestion:
        """Convert Firestore document to Suggestion model.

        Args:
            data: Firestore document data.

        Returns:
            Suggestion instance.
        """
        # Parse source traces
        source_traces = [
            SourceTraceEntry(
                trace_id=st["trace_id"],
                pattern_id=st["pattern_id"],
                added_at=datetime.fromisoformat(st["added_at"]),
                similarity_score=st.get("similarity_score"),
            )
            for st in data["source_traces"]
        ]

        # Parse pattern summary
        pattern = PatternSummary(
            failure_type=FailureType(data["pattern"]["failure_type"]),
            trigger_condition=data["pattern"]["trigger_condition"],
            title=data["pattern"]["title"],
            summary=data["pattern"]["summary"],
        )

        # Parse version history
        version_history = [
            StatusHistoryEntry(
                previous_status=SuggestionStatus(vh["previous_status"]) if vh.get("previous_status") else None,
                new_status=SuggestionStatus(vh["new_status"]),
                actor=vh["actor"],
                timestamp=datetime.fromisoformat(vh["timestamp"]),
                notes=vh.get("notes"),
            )
            for vh in data["version_history"]
        ]

        # Parse suggestion_content if present
        suggestion_content = None
        if data.get("suggestion_content"):
            from src.deduplication.models import SuggestionContent
            sc_data = data["suggestion_content"]
            suggestion_content = SuggestionContent(
                eval_test=sc_data.get("eval_test"),
                guardrail_rule=sc_data.get("guardrail_rule"),
                runbook_snippet=sc_data.get("runbook_snippet"),
            )

        # Parse approval_metadata if present
        approval_metadata = None
        if data.get("approval_metadata"):
            from src.deduplication.models import ApprovalMetadata
            am_data = data["approval_metadata"]
            approval_metadata = ApprovalMetadata(
                actor=am_data["actor"],
                action=am_data["action"],
                notes=am_data.get("notes"),
                timestamp=datetime.fromisoformat(am_data["timestamp"]),
            )

        return Suggestion(
            suggestion_id=data["suggestion_id"],
            type=SuggestionType(data["type"]),
            status=SuggestionStatus(data["status"]),
            severity=Severity(data["severity"]),
            source_traces=source_traces,
            pattern=pattern,
            embedding=data["embedding"],
            similarity_group=data["similarity_group"],
            suggestion_content=suggestion_content,
            approval_metadata=approval_metadata,
            version_history=version_history,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    # =========================================================================
    # Merge Operations (T017 - for US1)
    # =========================================================================

    def merge_into_suggestion(
        self,
        suggestion_id: str,
        pattern: FailurePattern,
        similarity_score: float,
    ) -> Suggestion:
        """Merge a pattern into an existing suggestion.

        Appends to source_traces array (FR-012) and updates timestamp.
        Prevents duplicate trace_ids from being added (idempotent merge).

        Args:
            suggestion_id: ID of suggestion to merge into.
            pattern: FailurePattern to add.
            similarity_score: Similarity score that triggered the merge.

        Returns:
            Updated Suggestion instance.

        Raises:
            SuggestionNotFoundError: If suggestion not found.
            SuggestionRepositoryError: If merge fails.
        """
        now = datetime.now(timezone.utc)

        # Get existing suggestion
        suggestion = self.get_suggestion_or_raise(suggestion_id)

        # Check for duplicate trace_id (prevent re-merging same pattern)
        existing_trace_ids = {st.trace_id for st in suggestion.source_traces}
        if pattern.source_trace_id in existing_trace_ids:
            logger.warning(
                "Skipping duplicate trace merge",
                extra={
                    "suggestion_id": suggestion_id,
                    "trace_id": pattern.source_trace_id,
                    "pattern_id": pattern.pattern_id,
                },
            )
            return suggestion  # Return unchanged suggestion (idempotent)

        # Create new source trace entry
        new_trace = SourceTraceEntry(
            trace_id=pattern.source_trace_id,
            pattern_id=pattern.pattern_id,
            added_at=now,
            similarity_score=similarity_score,
        )

        # Update in Firestore using array union for atomicity
        try:
            from google.cloud.firestore import ArrayUnion

            self.suggestions_ref.document(suggestion_id).update({
                "source_traces": ArrayUnion([new_trace.to_dict()]),
                "updated_at": now.isoformat(),
            })

            # Return updated suggestion
            suggestion.source_traces.append(new_trace)
            suggestion.updated_at = now

            logger.info(
                "Merged pattern into suggestion",
                extra={
                    "suggestion_id": suggestion_id,
                    "pattern_id": pattern.pattern_id,
                    "similarity_score": similarity_score,
                    "total_traces": len(suggestion.source_traces),
                },
            )
            return suggestion

        except Exception as e:
            raise SuggestionRepositoryError(f"Failed to merge into suggestion: {e}") from e

    # =========================================================================
    # Pending Pattern Queries (T011)
    # =========================================================================

    def get_pending_patterns(
        self,
        limit: int = 20,
    ) -> List[FailurePattern]:
        """Get unprocessed failure patterns for deduplication.

        Queries patterns with processed=false (FR-015).

        Args:
            limit: Maximum patterns to return (default: 20, per FR-017).

        Returns:
            List of FailurePattern instances.
        """
        query = _where_filter(self.patterns_ref, "processed", "==", False).limit(limit)

        patterns = []
        for doc in query.stream():
            try:
                data = doc.to_dict()
                pattern = self._doc_to_pattern(data)
                patterns.append(pattern)
            except Exception as e:
                logger.warning(
                    "Failed to parse pattern document",
                    extra={"doc_id": doc.id, "error": str(e)},
                )

        logger.info(
            "Fetched pending patterns",
            extra={"count": len(patterns), "limit": limit},
        )
        return patterns

    def _doc_to_pattern(self, data: Dict[str, Any]) -> FailurePattern:
        """Convert Firestore document to FailurePattern model.

        Args:
            data: Firestore document data.

        Returns:
            FailurePattern instance.
        """
        from src.extraction.models import Evidence, ReproductionContext

        return FailurePattern(
            pattern_id=data["pattern_id"],
            source_trace_id=data["source_trace_id"],
            title=data["title"],
            failure_type=FailureType(data["failure_type"]),
            trigger_condition=data["trigger_condition"],
            summary=data["summary"],
            root_cause_hypothesis=data["root_cause_hypothesis"],
            evidence=Evidence(
                signals=data["evidence"]["signals"],
                excerpt=data["evidence"].get("excerpt"),
            ),
            recommended_actions=data["recommended_actions"],
            reproduction_context=ReproductionContext(
                input_pattern=data["reproduction_context"]["input_pattern"],
                required_state=data["reproduction_context"].get("required_state"),
                tools_involved=data["reproduction_context"].get("tools_involved", []),
            ),
            severity=Severity(data["severity"]),
            confidence=data["confidence"],
            confidence_rationale=data["confidence_rationale"],
            extracted_at=datetime.fromisoformat(data["extracted_at"]),
        )

    # =========================================================================
    # Pattern Processing Status (T012)
    # =========================================================================

    def mark_pattern_processed(self, pattern: FailurePattern) -> None:
        """Mark a pattern as processed after deduplication (FR-016).

        Note: Uses source_trace_id as document ID since extraction service
        stores patterns using source_trace_id (not pattern_id) as the doc ID.

        Args:
            pattern: The FailurePattern to mark as processed.

        Raises:
            SuggestionRepositoryError: If update fails.
        """
        try:
            # Use source_trace_id as that's the document ID in Firestore
            self.patterns_ref.document(pattern.source_trace_id).update({
                "processed": True,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.debug(
                "Marked pattern as processed",
                extra={
                    "pattern_id": pattern.pattern_id,
                    "source_trace_id": pattern.source_trace_id,
                },
            )
        except Exception as e:
            raise SuggestionRepositoryError(f"Failed to mark pattern processed: {e}") from e

    # =========================================================================
    # Embedding Retrieval for Similarity Comparison
    # =========================================================================

    def get_all_suggestion_embeddings(self) -> List[Tuple[str, np.ndarray]]:
        """Get all suggestion embeddings for similarity comparison.

        Returns:
            List of (suggestion_id, embedding) tuples.
        """
        embeddings = []
        for doc in self.suggestions_ref.stream():
            data = doc.to_dict()
            if "embedding" in data and "suggestion_id" in data:
                embedding = np.array(data["embedding"], dtype=np.float32)
                embeddings.append((data["suggestion_id"], embedding))

        logger.debug(
            "Fetched suggestion embeddings",
            extra={"count": len(embeddings)},
        )
        return embeddings

    def get_pending_suggestion_embeddings(self) -> List[Tuple[str, np.ndarray]]:
        """Get embeddings for pending suggestions only.

        Useful for comparing new patterns only against active suggestions.

        Returns:
            List of (suggestion_id, embedding) tuples for pending suggestions.
        """
        query = _where_filter(self.suggestions_ref, "status", "==", "pending")

        embeddings = []
        for doc in query.stream():
            data = doc.to_dict()
            if "embedding" in data and "suggestion_id" in data:
                embedding = np.array(data["embedding"], dtype=np.float32)
                embeddings.append((data["suggestion_id"], embedding))

        logger.debug(
            "Fetched pending suggestion embeddings",
            extra={"count": len(embeddings)},
        )
        return embeddings

    # =========================================================================
    # Status Update Operations (T031 - for US3)
    # =========================================================================

    def update_suggestion_status(
        self,
        suggestion_id: str,
        new_status: SuggestionStatus,
        actor: str,
        notes: Optional[str] = None,
    ) -> Tuple[Suggestion, StatusHistoryEntry]:
        """Update suggestion status with audit trail (T031 - FR-005).

        Validates status transition and appends to version_history.

        Allowed transitions per FR-011:
        - pending -> approved
        - pending -> rejected

        Args:
            suggestion_id: ID of suggestion to update.
            new_status: Target status (must be approved or rejected).
            actor: Who is making the change.
            notes: Optional reason for the change.

        Returns:
            Tuple of (updated Suggestion, new StatusHistoryEntry).

        Raises:
            SuggestionNotFoundError: If suggestion not found.
            SuggestionRepositoryError: If transition is invalid or update fails.
        """
        from src.deduplication.models import ApprovalMetadata

        now = datetime.now(timezone.utc)

        # Get existing suggestion
        suggestion = self.get_suggestion_or_raise(suggestion_id)

        # Validate transition (FR-011: only pending -> approved/rejected)
        if suggestion.status != SuggestionStatus.PENDING:
            raise SuggestionRepositoryError(
                f"Cannot change status from '{suggestion.status.value}'. "
                f"Only 'pending' suggestions can be updated."
            )

        if new_status == SuggestionStatus.PENDING:
            raise SuggestionRepositoryError(
                "Cannot transition to 'pending'. Only 'approved' or 'rejected' allowed."
            )

        # Create status history entry
        history_entry = StatusHistoryEntry(
            previous_status=suggestion.status,
            new_status=new_status,
            actor=actor,
            timestamp=now,
            notes=notes,
        )

        # Create approval metadata
        approval_metadata = ApprovalMetadata(
            actor=actor,
            action=new_status.value,
            notes=notes,
            timestamp=now,
        )

        # Update in Firestore
        try:
            from google.cloud.firestore import ArrayUnion

            self.suggestions_ref.document(suggestion_id).update({
                "status": new_status.value,
                "version_history": ArrayUnion([history_entry.to_dict()]),
                "approval_metadata": approval_metadata.to_dict(),
                "updated_at": now.isoformat(),
            })

            # Update local suggestion object
            suggestion.status = new_status
            suggestion.version_history.append(history_entry)
            suggestion.approval_metadata = approval_metadata
            suggestion.updated_at = now

            logger.info(
                "Updated suggestion status",
                extra={
                    "suggestion_id": suggestion_id,
                    "previous_status": history_entry.previous_status.value,
                    "new_status": new_status.value,
                    "actor": actor,
                },
            )

            return suggestion, history_entry

        except Exception as e:
            raise SuggestionRepositoryError(f"Failed to update suggestion status: {e}") from e

    # =========================================================================
    # List Suggestions with Filters (T028, T036 - for US2/US4)
    # =========================================================================

    def list_suggestions(
        self,
        status: Optional[SuggestionStatus] = None,
        suggestion_type: Optional[SuggestionType] = None,
        severity: Optional[Severity] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Tuple[List[Suggestion], Optional[str], int]:
        """List suggestions with optional filters and pagination.

        Args:
            status: Filter by status (pending, approved, rejected).
            suggestion_type: Filter by type (eval, guardrail, runbook).
            severity: Filter by severity.
            limit: Maximum results per page (default 50, max 100).
            cursor: Document ID to start after for pagination.

        Returns:
            Tuple of (suggestions, next_cursor, page_count).
            - suggestions: List of Suggestion objects for this page
            - next_cursor: Document ID for next page, or None if no more results
            - page_count: Number of suggestions returned in this page (NOT total count).
              Note: Firestore doesn't support efficient COUNT queries, so we return
              page size. Use next_cursor presence to determine if more results exist.
        """
        # Build query with filters
        query = self.suggestions_ref

        if status:
            query = _where_filter(query, "status", "==", status.value)
        if suggestion_type:
            query = _where_filter(query, "type", "==", suggestion_type.value)
        if severity:
            query = _where_filter(query, "severity", "==", severity.value)

        # Order by created_at for consistent pagination
        query = query.order_by("created_at", direction="DESCENDING")

        # Apply cursor-based pagination
        if cursor:
            cursor_doc = self.suggestions_ref.document(cursor).get()
            if cursor_doc.exists:
                query = query.start_after(cursor_doc)

        # Limit results (+1 to detect if more exist)
        query = query.limit(limit + 1)

        # Execute query
        suggestions = []
        docs = list(query.stream())

        for doc in docs[:limit]:
            try:
                suggestions.append(self._doc_to_suggestion(doc.to_dict()))
            except Exception as e:
                logger.warning(
                    "Failed to parse suggestion document",
                    extra={"doc_id": doc.id, "error": str(e)},
                )

        # Determine next cursor
        next_cursor = None
        if len(docs) > limit:
            # More results exist
            next_cursor = suggestions[-1].suggestion_id if suggestions else None

        # Return page count (not total matching records)
        # Firestore doesn't support efficient COUNT queries
        # Use next_cursor presence to determine if more results exist
        page_count = len(suggestions)

        logger.info(
            "Listed suggestions",
            extra={
                "count": len(suggestions),
                "filters": {
                    "status": status.value if status else None,
                    "type": suggestion_type.value if suggestion_type else None,
                    "severity": severity.value if severity else None,
                },
                "has_more": next_cursor is not None,
            },
        )

        return suggestions, next_cursor, page_count

    def count_suggestions(
        self,
        status: Optional[SuggestionStatus] = None,
        suggestion_type: Optional[SuggestionType] = None,
        severity: Optional[Severity] = None,
    ) -> int:
        """Count suggestions matching filters.

        Note: Uses aggregation query for efficiency (Firestore 2023+).

        Args:
            status: Filter by status.
            suggestion_type: Filter by type.
            severity: Filter by severity.

        Returns:
            Count of matching suggestions.
        """
        query = self.suggestions_ref

        if status:
            query = _where_filter(query, "status", "==", status.value)
        if suggestion_type:
            query = _where_filter(query, "type", "==", suggestion_type.value)
        if severity:
            query = _where_filter(query, "severity", "==", severity.value)

        try:
            # Try aggregation query (Firestore 2023+)
            from google.cloud.firestore_v1.aggregation import CountAggregation
            from google.cloud.firestore_v1.base_aggregation import AggregationQuery

            agg_query = AggregationQuery(query)
            agg_query.count(alias="count")
            results = agg_query.get()
            for result in results:
                return result[0].value
            return 0
        except Exception:
            # Fallback: count documents (less efficient)
            count = 0
            for _ in query.stream():
                count += 1
            return count
