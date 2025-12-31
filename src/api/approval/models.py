"""Pydantic request/response models for approval workflow API.

Aligns with specs/008-approval-workflow-api/data-model.md and OpenAPI contract.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SuggestionStatus(str, Enum):
    """Status enum for suggestions."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SuggestionType(str, Enum):
    """Type enum for suggestions."""

    EVAL = "eval"
    GUARDRAIL = "guardrail"
    RUNBOOK = "runbook"


class ExportFormat(str, Enum):
    """Export format enum."""

    DEEPEVAL = "deepeval"
    PYTEST = "pytest"
    YAML = "yaml"


# =============================================================================
# Request Models
# =============================================================================


class ApproveRequest(BaseModel):
    """Request body for approving a suggestion."""

    notes: Optional[str] = Field(None, description="Optional notes for the approval")


class RejectRequest(BaseModel):
    """Request body for rejecting a suggestion."""

    reason: str = Field(..., min_length=1, description="Required explanation for rejection")


class WebhookTestRequest(BaseModel):
    """Request body for testing webhook delivery."""

    message: Optional[str] = Field(None, description="Custom test message")


# =============================================================================
# Response Models
# =============================================================================


class ApprovalResponse(BaseModel):
    """Response after approve/reject action."""

    status: str = Field(default="success")
    suggestion_id: str
    new_status: SuggestionStatus
    timestamp: datetime


class PatternSummary(BaseModel):
    """Summary of failure pattern embedded in suggestion."""

    failure_type: Optional[str] = None
    severity: Optional[str] = None
    trigger_condition: Optional[str] = None


class SuggestionSummary(BaseModel):
    """Summary view of a suggestion for list responses."""

    suggestion_id: str
    type: SuggestionType
    status: SuggestionStatus
    severity: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    pattern: Optional[PatternSummary] = None


class ApprovalMetadata(BaseModel):
    """Metadata recorded when a suggestion is approved/rejected."""

    actor: str
    action: str
    notes: Optional[str] = None
    reason: Optional[str] = None
    timestamp: datetime


class VersionHistoryEntry(BaseModel):
    """Entry in the version history audit trail."""

    status: str
    timestamp: datetime
    actor: str
    notes: Optional[str] = None


class SuggestionDetail(BaseModel):
    """Full detail view of a suggestion."""

    suggestion_id: str
    type: SuggestionType
    status: SuggestionStatus
    created_at: datetime
    updated_at: datetime
    pattern: Optional[PatternSummary] = None
    suggestion_content: Optional[dict[str, Any]] = None
    source_traces: list[str] = Field(default_factory=list)
    approval_metadata: Optional[ApprovalMetadata] = None
    version_history: list[VersionHistoryEntry] = Field(default_factory=list)


class SuggestionListResponse(BaseModel):
    """Response for listing suggestions with cursor-based pagination."""

    suggestions: list[SuggestionSummary]
    limit: int
    next_cursor: Optional[str] = Field(
        None,
        description="Cursor for next page (last suggestion ID), null if no more results"
    )
    has_more: bool = Field(
        description="Whether more results exist beyond this page"
    )


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(description="ok or degraded")
    firestoreProject: Optional[str] = None
    pendingCount: Optional[int] = None
    lastApprovalAt: Optional[datetime] = None


class WebhookTestResponse(BaseModel):
    """Response from webhook test endpoint."""

    status: str = Field(description="sent or failed")
    message: str


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str = Field(description="Human-readable error message")
