"""FastAPI router for approval workflow endpoints.

Implements /suggestions/* endpoints per OpenAPI contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.auth import verify_api_key
from src.api.approval.models import (
    ApproveRequest,
    ApprovalResponse,
    RejectRequest,
    SuggestionStatus,
    SuggestionType,
    ExportFormat,
)
from src.api.approval.repository import (
    get_firestore_client,
    SuggestionNotFoundError,
    InvalidStatusTransitionError,
)
from src.api.approval.service import ApprovalService
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["approval"])


def get_service() -> ApprovalService:
    """Dependency to get ApprovalService with Firestore client."""
    client = get_firestore_client()
    return ApprovalService(client)


# =============================================================================
# Approval Endpoints (User Story 1 + 2)
# =============================================================================


@router.post(
    "/suggestions/{suggestionId}/approve",
    response_model=ApprovalResponse,
    responses={
        401: {"description": "Invalid or missing API key"},
        404: {"description": "Suggestion not found"},
        409: {"description": "Suggestion is not in pending state"},
    },
)
async def approve_suggestion(
    suggestionId: str,
    request: Optional[ApproveRequest] = None,
    api_key: str = Depends(verify_api_key),
    service: ApprovalService = Depends(get_service),
) -> ApprovalResponse:
    """Approve a pending suggestion.

    Transitions a pending suggestion to approved status.
    Triggers Slack webhook notification on success.
    Returns 409 if suggestion is not in pending state.
    """
    try:
        notes = request.notes if request else None

        result = await service.approve_suggestion(
            suggestion_id=suggestionId,
            actor="api",  # Could be extracted from API key in future
            notes=notes,
        )

        return ApprovalResponse(
            status="success",
            suggestion_id=suggestionId,
            new_status=SuggestionStatus.APPROVED,
            timestamp=datetime.fromisoformat(result["updated_at"]),
        )

    except SuggestionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggestion not found",
        )

    except InvalidStatusTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Suggestion is not in pending state (current: {e.current_status})",
        )


@router.post(
    "/suggestions/{suggestionId}/reject",
    response_model=ApprovalResponse,
    responses={
        400: {"description": "Missing required reason field"},
        401: {"description": "Invalid or missing API key"},
        404: {"description": "Suggestion not found"},
        409: {"description": "Suggestion is not in pending state"},
    },
)
async def reject_suggestion(
    suggestionId: str,
    request: RejectRequest,
    api_key: str = Depends(verify_api_key),
    service: ApprovalService = Depends(get_service),
) -> ApprovalResponse:
    """Reject a pending suggestion.

    Transitions a pending suggestion to rejected status.
    Requires a reason explaining why the suggestion was rejected.
    Triggers Slack webhook notification on success.
    Returns 409 if suggestion is not in pending state.
    """
    try:
        result = await service.reject_suggestion(
            suggestion_id=suggestionId,
            reason=request.reason,
            actor="api",
        )

        return ApprovalResponse(
            status="success",
            suggestion_id=suggestionId,
            new_status=SuggestionStatus.REJECTED,
            timestamp=datetime.fromisoformat(result["updated_at"]),
        )

    except SuggestionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggestion not found",
        )

    except InvalidStatusTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Suggestion is not in pending state (current: {e.current_status})",
        )
