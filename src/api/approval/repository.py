"""Firestore repository for approval workflow.

Provides atomic operations for suggestion status transitions.
Uses cursor-based pagination per research.md findings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.transforms import ArrayUnion

from src.common.config import load_approval_config
from src.common.logging import get_logger

logger = get_logger(__name__)


class SuggestionNotFoundError(Exception):
    """Raised when a suggestion is not found."""

    pass


class InvalidStatusTransitionError(Exception):
    """Raised when a status transition is not valid."""

    def __init__(self, current_status: str, target_status: str):
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            f"Cannot transition from '{current_status}' to '{target_status}'"
        )


def get_firestore_client() -> firestore.Client:
    """Get a Firestore client with approval workflow configuration."""
    config = load_approval_config()
    kwargs = {}
    if config.firestore.project_id:
        kwargs["project"] = config.firestore.project_id
    if config.firestore.database_id:
        kwargs["database"] = config.firestore.database_id
    return firestore.Client(**kwargs)


def get_suggestions_collection(client: firestore.Client) -> firestore.CollectionReference:
    """Get the suggestions collection reference."""
    config = load_approval_config()
    collection_name = f"{config.firestore.collection_prefix}suggestions"
    return client.collection(collection_name)


def get_suggestion(
    client: firestore.Client,
    suggestion_id: str,
) -> Optional[dict[str, Any]]:
    """Get a single suggestion by ID.

    Args:
        client: Firestore client.
        suggestion_id: The suggestion ID to fetch.

    Returns:
        Suggestion data dict, or None if not found.
    """
    collection = get_suggestions_collection(client)
    doc = collection.document(suggestion_id).get()

    if not doc.exists:
        return None

    data = doc.to_dict()
    data["suggestion_id"] = doc.id
    return data


@firestore.transactional
def _approve_in_transaction(
    transaction: firestore.Transaction,
    doc_ref: firestore.DocumentReference,
    actor: str,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """Atomically approve a suggestion within a transaction.

    Args:
        transaction: Firestore transaction.
        doc_ref: Reference to the suggestion document.
        actor: Who is performing the approval.
        notes: Optional notes for the approval.

    Returns:
        Updated suggestion data.

    Raises:
        SuggestionNotFoundError: If suggestion doesn't exist.
        InvalidStatusTransitionError: If not in pending state.
    """
    # Step 1: Read current state (MUST happen before writes)
    snapshot = doc_ref.get(transaction=transaction)

    if not snapshot.exists:
        raise SuggestionNotFoundError(f"Suggestion {doc_ref.id} not found")

    data = snapshot.to_dict()
    current_status = data.get("status", "unknown")

    if current_status != "pending":
        raise InvalidStatusTransitionError(current_status, "approved")

    # Step 2: Prepare update data
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    history_entry = {
        "status": "approved",
        "timestamp": now_iso,
        "actor": actor,
        "notes": notes,
    }

    approval_metadata = {
        "actor": actor,
        "action": "approved",
        "notes": notes,
        "timestamp": now_iso,
    }

    # Step 3: Atomic update
    transaction.update(doc_ref, {
        "status": "approved",
        "updated_at": now_iso,
        "approval_metadata": approval_metadata,
        "version_history": ArrayUnion([history_entry]),
    })

    # Return updated data
    data["status"] = "approved"
    data["updated_at"] = now_iso
    data["approval_metadata"] = approval_metadata
    data["suggestion_id"] = doc_ref.id
    return data


def approve_suggestion(
    client: firestore.Client,
    suggestion_id: str,
    actor: str,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """Approve a pending suggestion atomically.

    Args:
        client: Firestore client.
        suggestion_id: The suggestion ID to approve.
        actor: Who is performing the approval.
        notes: Optional notes for the approval.

    Returns:
        Updated suggestion data.

    Raises:
        SuggestionNotFoundError: If suggestion doesn't exist.
        InvalidStatusTransitionError: If not in pending state.
    """
    collection = get_suggestions_collection(client)
    doc_ref = collection.document(suggestion_id)
    transaction = client.transaction()

    return _approve_in_transaction(transaction, doc_ref, actor, notes)


@firestore.transactional
def _reject_in_transaction(
    transaction: firestore.Transaction,
    doc_ref: firestore.DocumentReference,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Atomically reject a suggestion within a transaction.

    Args:
        transaction: Firestore transaction.
        doc_ref: Reference to the suggestion document.
        actor: Who is performing the rejection.
        reason: Required reason for rejection.

    Returns:
        Updated suggestion data.

    Raises:
        SuggestionNotFoundError: If suggestion doesn't exist.
        InvalidStatusTransitionError: If not in pending state.
    """
    # Step 1: Read current state
    snapshot = doc_ref.get(transaction=transaction)

    if not snapshot.exists:
        raise SuggestionNotFoundError(f"Suggestion {doc_ref.id} not found")

    data = snapshot.to_dict()
    current_status = data.get("status", "unknown")

    if current_status != "pending":
        raise InvalidStatusTransitionError(current_status, "rejected")

    # Step 2: Prepare update data
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    history_entry = {
        "status": "rejected",
        "timestamp": now_iso,
        "actor": actor,
        "notes": reason,
    }

    approval_metadata = {
        "actor": actor,
        "action": "rejected",
        "reason": reason,
        "timestamp": now_iso,
    }

    # Step 3: Atomic update
    transaction.update(doc_ref, {
        "status": "rejected",
        "updated_at": now_iso,
        "approval_metadata": approval_metadata,
        "version_history": ArrayUnion([history_entry]),
    })

    # Return updated data
    data["status"] = "rejected"
    data["updated_at"] = now_iso
    data["approval_metadata"] = approval_metadata
    data["suggestion_id"] = doc_ref.id
    return data


def reject_suggestion(
    client: firestore.Client,
    suggestion_id: str,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Reject a pending suggestion atomically.

    Args:
        client: Firestore client.
        suggestion_id: The suggestion ID to reject.
        actor: Who is performing the rejection.
        reason: Required reason for rejection.

    Returns:
        Updated suggestion data.

    Raises:
        SuggestionNotFoundError: If suggestion doesn't exist.
        InvalidStatusTransitionError: If not in pending state.
    """
    collection = get_suggestions_collection(client)
    doc_ref = collection.document(suggestion_id)
    transaction = client.transaction()

    return _reject_in_transaction(transaction, doc_ref, actor, reason)


def list_suggestions(
    client: firestore.Client,
    status: Optional[str] = None,
    suggestion_type: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> tuple[list[dict[str, Any]], Optional[str], bool]:
    """List suggestions with optional filters and cursor-based pagination.

    Uses start_after() for efficient pagination (no billing for skipped docs).

    Args:
        client: Firestore client.
        status: Filter by status (pending, approved, rejected).
        suggestion_type: Filter by type (eval, guardrail, runbook).
        limit: Maximum number of results (1-100).
        cursor: Last suggestion ID from previous page.

    Returns:
        Tuple of (suggestions list, next_cursor, has_more).
    """
    collection = get_suggestions_collection(client)

    # Build query with filters
    query = collection

    if status:
        query = query.where(filter=FieldFilter("status", "==", status))

    if suggestion_type:
        query = query.where(filter=FieldFilter("type", "==", suggestion_type))

    # Order by created_at descending (newest first)
    query = query.order_by("created_at", direction=firestore.Query.DESCENDING)

    # Apply cursor-based pagination
    if cursor:
        cursor_doc = collection.document(cursor).get()
        if cursor_doc.exists:
            query = query.start_after(cursor_doc)

    # Use limit + 1 trick to detect if more results exist
    query = query.limit(limit + 1)

    # Execute query
    docs = list(query.stream())

    # Check if there are more results
    has_more = len(docs) > limit
    results = docs[:limit]

    # Convert to dicts
    suggestions = []
    for doc in results:
        data = doc.to_dict()
        data["suggestion_id"] = doc.id
        suggestions.append(data)

    # Get next cursor (last doc ID)
    next_cursor = results[-1].id if results and has_more else None

    return suggestions, next_cursor, has_more


def count_pending_suggestions(client: firestore.Client) -> int:
    """Count the number of pending suggestions.

    Args:
        client: Firestore client.

    Returns:
        Count of pending suggestions.
    """
    collection = get_suggestions_collection(client)
    query = collection.where(filter=FieldFilter("status", "==", "pending"))

    # Count documents
    count = 0
    for _ in query.stream():
        count += 1
    return count


def get_last_approval_timestamp(client: firestore.Client) -> Optional[str]:
    """Get the timestamp of the most recent approval.

    Args:
        client: Firestore client.

    Returns:
        ISO timestamp of last approval, or None if no approvals.
    """
    collection = get_suggestions_collection(client)
    query = (
        collection
        .where(filter=FieldFilter("status", "==", "approved"))
        .order_by("updated_at", direction=firestore.Query.DESCENDING)
        .limit(1)
    )

    docs = list(query.stream())
    if docs:
        data = docs[0].to_dict()
        return data.get("updated_at")

    return None
