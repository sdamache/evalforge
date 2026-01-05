"""FastAPI router for approval workflow endpoints.

Implements /suggestions/* endpoints per OpenAPI contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
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
    SuggestionListResponse,
    SuggestionSummary,
    SuggestionDetail,
    PatternSummary,
    ApprovalMetadata,
    VersionHistoryEntry,
    WebhookTestRequest,
    WebhookTestResponse,
    HealthResponse,
)
from fastapi.responses import PlainTextResponse, Response
from src.api.approval.repository import (
    get_firestore_client,
    SuggestionNotFoundError,
    InvalidStatusTransitionError,
)
from src.api.approval.service import ApprovalService, SuggestionNotApprovedError
from src.api.approval.exporters import ContentMissingError, ExportError
from src.api.approval.webhook import send_test_notification
from src.common.logging import get_logger

logger = get_logger(__name__)


def _parse_datetime(value: Any) -> datetime:
    """Parse datetime from various formats (Firestore Timestamp, ISO string, datetime).

    Firestore returns Timestamp objects for datetime fields, but we might also
    receive ISO strings from some sources.
    """
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    # Firestore Timestamp object has a to_datetime() method
    if hasattr(value, "to_datetime"):
        return value.to_datetime()
    # Fallback - try to convert from timestamp
    if hasattr(value, "timestamp"):
        return datetime.fromtimestamp(value.timestamp(), tz=timezone.utc)
    # Last resort
    return datetime.now(timezone.utc)


router = APIRouter(tags=["approval"])


def get_service() -> ApprovalService:
    """Dependency to get ApprovalService with Firestore client."""
    client = get_firestore_client()
    return ApprovalService(client)


# =============================================================================
# Health Check Endpoint
# =============================================================================


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["health"],
)
def health_check(
    service: ApprovalService = Depends(get_service),
) -> HealthResponse:
    """Health check endpoint for the approval workflow service.

    Returns service status and operational metrics:
    - pendingCount: Number of suggestions awaiting approval
    - lastApprovalAt: Timestamp of most recent approval action

    No authentication required for health checks.
    """
    try:
        stats = service.get_health_stats()

        return HealthResponse(
            status="ok",
            pendingCount=stats.get("pendingCount"),
            lastApprovalAt=stats.get("lastApprovalAt"),
        )
    except Exception as e:
        logger.error("Health check failed", extra={"error": str(e)})
        return HealthResponse(
            status="degraded",
            pendingCount=None,
            lastApprovalAt=None,
        )


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
        401: {"description": "Invalid or missing API key"},
        404: {"description": "Suggestion not found"},
        409: {"description": "Suggestion is not in pending state"},
        422: {"description": "Missing or invalid reason field"},
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


# =============================================================================
# Export Endpoint (User Story 3)
# =============================================================================


@router.get(
    "/suggestions/{suggestionId}/export",
    responses={
        200: {
            "description": "Exported content",
            "content": {
                "application/json": {"schema": {"type": "object"}},
                "text/x-python": {"schema": {"type": "string"}},
                "application/x-yaml": {"schema": {"type": "string"}},
            },
        },
        401: {"description": "Invalid or missing API key"},
        404: {"description": "Suggestion not found"},
        409: {"description": "Suggestion is not approved (cannot export)"},
        422: {"description": "Suggestion content missing or invalid for export"},
    },
)
def export_suggestion_endpoint(
    suggestionId: str,
    format: ExportFormat = Query(
        default=ExportFormat.DEEPEVAL,
        description="Export format (deepeval, pytest, yaml)",
    ),
    api_key: str = Depends(verify_api_key),
    service: ApprovalService = Depends(get_service),
) -> Response:
    """Export an approved suggestion in the requested format.

    Generates and returns the suggestion content in the requested format.
    Only approved suggestions can be exported.
    Returns 409 if suggestion is not approved.
    Returns 422 if suggestion content is missing required fields.
    """
    try:
        content, content_type = service.export_suggestion(
            suggestion_id=suggestionId,
            format=format.value,
        )

        return Response(
            content=content,
            media_type=content_type,
        )

    except SuggestionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggestion not found",
        )

    except SuggestionNotApprovedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Suggestion is not approved (current: {e.current_status})",
        )

    except ContentMissingError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Suggestion content invalid: {e}",
        )

    except ExportError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Export generation failed: {e}",
        )


# =============================================================================
# Browse Queue Endpoints (User Story 4)
# =============================================================================


@router.get(
    "/suggestions",
    response_model=SuggestionListResponse,
    responses={
        401: {"description": "Invalid or missing API key"},
    },
)
def list_suggestions(
    status_filter: Optional[SuggestionStatus] = Query(
        None,
        alias="status",
        description="Filter by suggestion status",
    ),
    type_filter: Optional[SuggestionType] = Query(
        None,
        alias="type",
        description="Filter by suggestion type",
    ),
    limit: int = Query(
        50,
        ge=1,
        le=100,
        description="Maximum number of suggestions to return",
    ),
    cursor: Optional[str] = Query(
        None,
        description="Cursor for pagination (last suggestion ID from previous page)",
    ),
    api_key: str = Depends(verify_api_key),
    service: ApprovalService = Depends(get_service),
) -> SuggestionListResponse:
    """List suggestions with optional filters.

    Returns paginated list of suggestions. Supports filtering by status and type.
    Results are ordered by created_at descending (newest first).
    Uses cursor-based pagination for efficient traversal.
    """
    suggestions, next_cursor, has_more = service.list_suggestions(
        status=status_filter.value if status_filter else None,
        suggestion_type=type_filter.value if type_filter else None,
        limit=limit,
        cursor=cursor,
    )

    # Convert to response model
    summaries = []
    for s in suggestions:
        pattern = None
        if s.get("pattern"):
            pattern = PatternSummary(
                failure_type=s["pattern"].get("failure_type"),
                trigger_condition=s["pattern"].get("trigger_condition"),
            )

        # Severity lives at suggestion level (top-level), not inside pattern
        severity = s.get("severity")

        # TODO: Future data should have pattern.title and pattern.summary populated
        # by the deduplication service. Current data was created from external sources
        # (e.g., AgentErrorBench) without these fields. This fallback chain handles both.
        # Priority: top-level > pattern > suggestion_content (type-specific)
        title = s.get("title") or (s.get("pattern") or {}).get("title")
        description = s.get("description") or (s.get("pattern") or {}).get("summary")

        # Fallback to suggestion_content if still missing
        if not title or not description:
            content = s.get("suggestion_content") or {}
            # Map suggestion type to content key
            content_key = {"eval": "eval_test", "guardrail": "guardrail", "runbook": "runbook_snippet"}.get(s.get("type"))
            if content_key and content.get(content_key):
                artifact = content[content_key]
                if not title:
                    title = artifact.get("rule_name") or artifact.get("test_name") or artifact.get("title")
                if not description:
                    description = artifact.get("description")

        summaries.append(
            SuggestionSummary(
                suggestion_id=s["suggestion_id"],
                type=SuggestionType(s.get("type", "eval")),
                status=SuggestionStatus(s.get("status", "pending")),
                severity=severity,
                title=title,
                description=description,
                created_at=_parse_datetime(s.get("created_at")),
                pattern=pattern,
            )
        )

    return SuggestionListResponse(
        suggestions=summaries,
        limit=limit,
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/suggestions/{suggestionId}",
    response_model=SuggestionDetail,
    responses={
        401: {"description": "Invalid or missing API key"},
        404: {"description": "Suggestion not found"},
    },
)
def get_suggestion_detail(
    suggestionId: str,
    api_key: str = Depends(verify_api_key),
    service: ApprovalService = Depends(get_service),
) -> SuggestionDetail:
    """Get a single suggestion by ID.

    Returns full suggestion details including version_history.
    """
    suggestion = service.get_suggestion(suggestionId)

    if not suggestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suggestion not found",
        )

    # Build pattern (severity is at suggestion level, not inside pattern)
    pattern = None
    if suggestion.get("pattern"):
        pattern = PatternSummary(
            failure_type=suggestion["pattern"].get("failure_type"),
            trigger_condition=suggestion["pattern"].get("trigger_condition"),
        )

    # Build approval_metadata
    approval_metadata = None
    if suggestion.get("approval_metadata"):
        am = suggestion["approval_metadata"]
        approval_metadata = ApprovalMetadata(
            actor=am.get("actor", ""),
            action=am.get("action", ""),
            notes=am.get("notes"),
            reason=am.get("reason"),
            timestamp=datetime.fromisoformat(am["timestamp"]) if am.get("timestamp") else datetime.now(),
        )

    # Build version_history (new_status is canonical, fallback to status for compat)
    version_history = []
    for entry in suggestion.get("version_history", []):
        version_history.append(
            VersionHistoryEntry(
                status=entry.get("new_status", entry.get("status", "")),
                timestamp=datetime.fromisoformat(entry["timestamp"]) if entry.get("timestamp") else datetime.now(),
                actor=entry.get("actor", ""),
                notes=entry.get("notes"),
            )
        )

    # Normalize source_traces: deduplication service stores structured objects
    # {trace_id, pattern_id, added_at, similarity_score}, but API returns list[str]
    raw_source_traces = suggestion.get("source_traces", [])
    source_traces: list[str] = []
    for item in raw_source_traces:
        if isinstance(item, dict):
            # Structured entry from deduplication service
            source_traces.append(item.get("trace_id", ""))
        else:
            # Already a string (test data or legacy format)
            source_traces.append(str(item))

    return SuggestionDetail(
        suggestion_id=suggestion["suggestion_id"],
        type=SuggestionType(suggestion.get("type", "eval")),
        status=SuggestionStatus(suggestion.get("status", "pending")),
        created_at=datetime.fromisoformat(suggestion["created_at"]),
        updated_at=datetime.fromisoformat(suggestion["updated_at"]),
        pattern=pattern,
        suggestion_content=suggestion.get("suggestion_content"),
        source_traces=source_traces,
        approval_metadata=approval_metadata,
        version_history=version_history,
    )


# =============================================================================
# Webhook Endpoints (User Story 5)
# =============================================================================


@router.post(
    "/webhooks/test",
    response_model=WebhookTestResponse,
    responses={
        401: {"description": "Invalid or missing API key"},
        503: {"description": "Webhook not configured or delivery failed"},
    },
)
async def test_webhook(
    request: Optional[WebhookTestRequest] = None,
    api_key: str = Depends(verify_api_key),
) -> WebhookTestResponse:
    """Test webhook delivery to configured Slack channel.

    Sends a test message to verify webhook configuration is working.
    Returns success/failure status and a message.
    """
    message = request.message if request else None
    success, status_message = await send_test_notification(message)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=status_message,
        )

    return WebhookTestResponse(
        status="sent",
        message=status_message,
    )
