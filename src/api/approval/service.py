"""Business logic for approval workflow.

Implements approve, reject, export, and list operations for suggestions.
"""

from __future__ import annotations

import asyncio
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
from src.api.approval.exporters import (
    export_suggestion as exporter_export,
    ContentMissingError,
    ExportError,
)
from src.api.approval.webhook import send_approval_notification
from src.common.logging import get_logger, log_audit


class SuggestionNotApprovedError(Exception):
    """Raised when trying to export a non-approved suggestion."""

    def __init__(self, current_status: str):
        self.current_status = current_status
        super().__init__(f"Suggestion is not approved (current: {current_status})")

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

        # Trigger webhook notification (fire-and-forget, non-blocking)
        # Webhook failures must not block approval response
        asyncio.create_task(
            send_approval_notification(
                suggestion_id=suggestion_id,
                action="approved",
                actor=actor,
                suggestion_type=result.get("type"),
                notes=notes,
            )
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

        # Trigger webhook notification (fire-and-forget, non-blocking)
        # Webhook failures must not block rejection response
        asyncio.create_task(
            send_approval_notification(
                suggestion_id=suggestion_id,
                action="rejected",
                actor=actor,
                suggestion_type=result.get("type"),
                reason=reason,
            )
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

    def export_suggestion(
        self,
        suggestion_id: str,
        format: str = "deepeval",
    ) -> tuple[str, str]:
        """Export an approved suggestion in the requested format.

        Args:
            suggestion_id: The suggestion ID to export.
            format: Export format (deepeval, pytest, yaml).

        Returns:
            Tuple of (content, content_type).

        Raises:
            SuggestionNotFoundError: If suggestion doesn't exist.
            SuggestionNotApprovedError: If suggestion is not approved.
            ContentMissingError: If suggestion_content is missing required fields.
            ExportError: If export generation fails.
        """
        # Fetch the suggestion
        suggestion = get_suggestion(self.client, suggestion_id)
        if not suggestion:
            raise SuggestionNotFoundError(f"Suggestion {suggestion_id} not found")

        # Validate suggestion is approved
        status = suggestion.get("status", "unknown")
        if status != "approved":
            raise SuggestionNotApprovedError(status)

        # Generate export
        content, content_type = exporter_export(suggestion, format)

        # Log export action
        log_audit(
            logger,
            actor="api",
            action="export_suggestion",
            target=suggestion_id,
            format=format,
        )

        logger.info(
            "Suggestion exported",
            extra={
                "suggestion_id": suggestion_id,
                "format": format,
                "content_type": content_type,
            }
        )

        return content, content_type
