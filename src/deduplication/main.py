"""FastAPI service for suggestion deduplication.

Provides REST API endpoints for:
- Health checks (Cloud Run compatibility)
- Batch deduplication processing
- Suggestion queries (future phases)

Per contracts/deduplication-openapi.yaml:
- GET /health: Service health status
- POST /dedup/run-once: Process batch of patterns

Service runs on port 8003 (distinct from ingestion:8001, extraction:8002, api:8000).
"""

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from src.deduplication.deduplication_service import DeduplicationService
from src.deduplication.embedding_client import EmbeddingClient
from src.deduplication.firestore_repository import SuggestionRepository, SuggestionNotFoundError
from src.deduplication.models import (
    DeduplicationRunRequest,
    DeduplicationRunSummary,
    ErrorResponse,
    HealthResponse,
    SuggestionResponse,
    SuggestionListResponse,
    SuggestionStatus,
    SuggestionType,
    TriggeredBy,
)
from src.extraction.models import Severity

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Service version
VERSION = "1.0.0"

# Create FastAPI app
app = FastAPI(
    title="EvalForge Deduplication Service",
    description="Deduplicates failure patterns into suggestions using semantic similarity.",
    version=VERSION,
)

# Lazy-initialized service (to avoid connection issues at import time)
_service: Optional[DeduplicationService] = None
_embedding_client: Optional[EmbeddingClient] = None
_repository: Optional[SuggestionRepository] = None


def get_embedding_client() -> EmbeddingClient:
    """Get or create the embedding client singleton."""
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = EmbeddingClient()
    return _embedding_client


def get_repository() -> SuggestionRepository:
    """Get or create the suggestion repository singleton."""
    global _repository
    if _repository is None:
        _repository = SuggestionRepository()
    return _repository


def get_service() -> DeduplicationService:
    """Get or create the deduplication service singleton."""
    global _service
    if _service is None:
        _service = DeduplicationService(
            embedding_client=get_embedding_client(),
            repository=get_repository(),
        )
    return _service


# ============================================================================
# Health Check Endpoint (T021)
# ============================================================================


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check endpoint",
    description="Returns service health status for Cloud Run health checks.",
)
async def health_check() -> HealthResponse:
    """Check service health and embedding service availability.

    Returns:
        HealthResponse with status, version, and embedding service availability.
    """
    embedding_status = "unavailable"

    try:
        client = get_embedding_client()
        if client.is_available():
            embedding_status = "available"
    except Exception as e:
        logger.warning(f"Embedding service check failed: {e}")

    return HealthResponse(
        status="healthy",
        version=VERSION,
        embedding_service=embedding_status,
    )


# ============================================================================
# Deduplication Endpoint (T022)
# ============================================================================


@app.post(
    "/dedup/run-once",
    response_model=DeduplicationRunSummary,
    responses={
        429: {"model": ErrorResponse, "description": "Rate limited by embedding service"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
    summary="Run one batch of deduplication",
    description="""
    Fetches up to `batchSize` unprocessed failure patterns from Firestore,
    computes embeddings, and either merges into existing suggestions or
    creates new ones. Marks processed patterns as processed=true.
    """,
)
async def run_deduplication(
    request: Optional[DeduplicationRunRequest] = None,
) -> DeduplicationRunSummary:
    """Process a batch of failure patterns for deduplication.

    Args:
        request: Optional configuration for this run (batch size, dry run, etc.)

    Returns:
        DeduplicationRunSummary with processing statistics.

    Raises:
        HTTPException: On rate limiting (429) or internal errors (500).
    """
    try:
        service = get_service()

        # Parse request parameters
        batch_size = None
        dry_run = False
        triggered_by = TriggeredBy.MANUAL

        if request:
            batch_size = request.batch_size
            dry_run = request.dry_run or False
            triggered_by = request.triggered_by or TriggeredBy.MANUAL

        logger.info(
            "Deduplication run requested",
            extra={
                "batch_size": batch_size,
                "dry_run": dry_run,
                "triggered_by": triggered_by.value,
            },
        )

        # Process batch
        summary = service.process_batch(
            batch_size=batch_size,
            triggered_by=triggered_by,
            dry_run=dry_run,
        )

        return summary

    except Exception as e:
        error_str = str(e).lower()

        # Check for rate limiting
        if "429" in str(e) or "rate" in error_str or "quota" in error_str:
            logger.warning(f"Rate limited during deduplication: {e}")
            raise HTTPException(
                status_code=429,
                detail=ErrorResponse(
                    error="rate_limit",
                    message="Rate limited by embedding service. Try again later.",
                    details={"original_error": str(e)},
                ).model_dump(),
            )

        # Other errors
        logger.error(f"Deduplication run failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error="internal_error",
                message="Deduplication processing failed.",
                details={"original_error": str(e)},
            ).model_dump(),
        )


# ============================================================================
# Suggestion Endpoints (T027, T028 - User Story 2)
# ============================================================================


@app.get(
    "/suggestions/{suggestion_id}",
    response_model=SuggestionResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Suggestion not found"},
    },
    summary="Get suggestion by ID",
    description="Returns full suggestion details including lineage (source traces).",
)
async def get_suggestion(suggestion_id: str) -> SuggestionResponse:
    """Get a suggestion by ID with full lineage information (T027 - US2).

    Args:
        suggestion_id: The unique suggestion identifier.

    Returns:
        SuggestionResponse with full details and source traces.

    Raises:
        HTTPException: 404 if suggestion not found.
    """
    try:
        repository = get_repository()
        suggestion = repository.get_suggestion(suggestion_id)

        if suggestion is None:
            raise HTTPException(
                status_code=404,
                detail=ErrorResponse(
                    error="not_found",
                    message=f"Suggestion not found: {suggestion_id}",
                ).model_dump(),
            )

        return SuggestionResponse.from_suggestion(suggestion)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get suggestion {suggestion_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error="internal_error",
                message="Failed to retrieve suggestion.",
                details={"original_error": str(e)},
            ).model_dump(),
        )


@app.get(
    "/suggestions",
    response_model=SuggestionListResponse,
    summary="List suggestions with filters",
    description="Returns paginated list of suggestions filtered by status, type, or severity.",
)
async def list_suggestions(
    status: Optional[str] = None,
    type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> SuggestionListResponse:
    """List suggestions with optional filters and pagination (T028 - US2).

    Args:
        status: Filter by status (pending, approved, rejected).
        type: Filter by suggestion type (eval, guardrail, runbook).
        severity: Filter by severity (low, medium, high, critical).
        limit: Maximum results per page (1-100, default 50).
        cursor: Pagination cursor from previous response.

    Returns:
        SuggestionListResponse with suggestions and pagination info.
    """
    try:
        repository = get_repository()

        # Parse and validate filters
        status_filter = None
        if status:
            try:
                status_filter = SuggestionStatus(status)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=ErrorResponse(
                        error="invalid_parameter",
                        message=f"Invalid status: {status}. Must be one of: pending, approved, rejected",
                    ).model_dump(),
                )

        type_filter = None
        if type:
            try:
                type_filter = SuggestionType(type)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=ErrorResponse(
                        error="invalid_parameter",
                        message=f"Invalid type: {type}. Must be one of: eval, guardrail, runbook",
                    ).model_dump(),
                )

        severity_filter = None
        if severity:
            try:
                severity_filter = Severity(severity)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=ErrorResponse(
                        error="invalid_parameter",
                        message=f"Invalid severity: {severity}. Must be one of: low, medium, high, critical",
                    ).model_dump(),
                )

        # Validate limit
        if limit < 1 or limit > 100:
            limit = min(max(limit, 1), 100)

        # Query suggestions
        suggestions, next_cursor, total = repository.list_suggestions(
            status=status_filter,
            suggestion_type=type_filter,
            severity=severity_filter,
            limit=limit,
            cursor=cursor,
        )

        # Convert to response format
        return SuggestionListResponse(
            suggestions=[SuggestionResponse.from_suggestion(s) for s in suggestions],
            total=total,
            next_cursor=next_cursor,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list suggestions: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error="internal_error",
                message="Failed to list suggestions.",
                details={"original_error": str(e)},
            ).model_dump(),
        )


# ============================================================================
# Error Handlers
# ============================================================================


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for unhandled errors."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_error",
            message="An unexpected error occurred.",
            details={"type": type(exc).__name__},
        ).model_dump(),
    )


# ============================================================================
# Main Entry Point
# ============================================================================


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.deduplication.main:app",
        host="0.0.0.0",
        port=8003,
        reload=True,
    )
