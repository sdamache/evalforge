"""Business logic for approval workflow.

Implements approve, reject, export, and list operations for suggestions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from google.cloud import firestore

from src.api.approval.repository import (
    InvalidStatusTransitionError,
    SuggestionNotFoundError,
    approve_suggestion as repo_approve,
    reject_suggestion as repo_reject,
    get_suggestion,
    list_suggestions as repo_list,
    count_pending_suggestions,
    get_last_approval_timestamp,
)
from src.api.approval.webhook import send_approval_notification
from src.common.logging import get_logger, log_audit

logger = get_logger(__name__)


class ApprovalService:
    """Service for managing suggestion approvals."""

    def __init__(self, client: firestore.Client):
        """Initialize the approval service.

        Args:
            client: Firestore client instance.
        """
        self.client = client

    async def approve_suggestion(
        self,
        suggestion_id: str,
        actor: str = "api",
        notes: Optional[str] = None,
    ) -> dict[str, Any]:
        """Approve a pending suggestion.

        Args:
            suggestion_id: The suggestion ID to approve.
            actor: Who is performing the approval.
            notes: Optional notes for the approval.

        Returns:
            Updated suggestion data with approval response fields.

        Raises:
            SuggestionNotFoundError: If suggestion doesn't exist.
            InvalidStatusTransitionError: If not in pending state.
        """
        # Perform atomic approval
        result = repo_approve(
            client=self.client,
            suggestion_id=suggestion_id,
            actor=actor,
            notes=notes,
        )

        # Log audit trail
        log_audit(
            logger,
            actor=actor,
            action="approve_suggestion",
            target=suggestion_id,
            status="approved",
            notes=notes,
        )

        logger.info(
            "Suggestion approved",
            extra={
                "suggestion_id": suggestion_id,
                "actor": actor,
            }
        )

        # Trigger webhook notification (fire-and-forget via BackgroundTasks)
        # This is called after the approval succeeds
        await send_approval_notification(
            suggestion_id=suggestion_id,
            action="approved",
            actor=actor,
            suggestion_type=result.get("type"),
            notes=notes,
        )

        return result

    async def reject_suggestion(
        self,
        suggestion_id: str,
        reason: str,
        actor: str = "api",
    ) -> dict[str, Any]:
        """Reject a pending suggestion.

        Args:
            suggestion_id: The suggestion ID to reject.
            reason: Required reason for rejection.
            actor: Who is performing the rejection.

        Returns:
            Updated suggestion data with rejection response fields.

        Raises:
            SuggestionNotFoundError: If suggestion doesn't exist.
            InvalidStatusTransitionError: If not in pending state.
        """
        # Perform atomic rejection
        result = repo_reject(
            client=self.client,
            suggestion_id=suggestion_id,
            actor=actor,
            reason=reason,
        )

        # Log audit trail
        log_audit(
            logger,
            actor=actor,
            action="reject_suggestion",
            target=suggestion_id,
            status="rejected",
            reason=reason,
        )

        logger.info(
            "Suggestion rejected",
            extra={
                "suggestion_id": suggestion_id,
                "actor": actor,
                "reason": reason,
            }
        )

        # Trigger webhook notification
        await send_approval_notification(
            suggestion_id=suggestion_id,
            action="rejected",
            actor=actor,
            suggestion_type=result.get("type"),
            reason=reason,
        )

        return result

    def get_suggestion(self, suggestion_id: str) -> Optional[dict[str, Any]]:
        """Get a single suggestion by ID.

        Args:
            suggestion_id: The suggestion ID to fetch.

        Returns:
            Suggestion data dict, or None if not found.
        """
        return get_suggestion(self.client, suggestion_id)

    def list_suggestions(
        self,
        status: Optional[str] = None,
        suggestion_type: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], Optional[str], bool]:
        """List suggestions with optional filters.

        Args:
            status: Filter by status (pending, approved, rejected).
            suggestion_type: Filter by type (eval, guardrail, runbook).
            limit: Maximum number of results.
            cursor: Pagination cursor.

        Returns:
            Tuple of (suggestions, next_cursor, has_more).
        """
        return repo_list(
            client=self.client,
            status=status,
            suggestion_type=suggestion_type,
            limit=limit,
            cursor=cursor,
        )

    def get_health_stats(self) -> dict[str, Any]:
        """Get health statistics for the approval workflow.

        Returns:
            Dict with pendingCount and lastApprovalAt.
        """
        pending_count = count_pending_suggestions(self.client)
        last_approval = get_last_approval_timestamp(self.client)

        return {
            "pendingCount": pending_count,
            "lastApprovalAt": last_approval,
        }
