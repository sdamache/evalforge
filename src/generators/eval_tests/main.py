"""FastAPI service for generating eval test drafts.

Endpoints (see specs/004-eval-test-case-generator/contracts/eval-generator-openapi.yaml):
- GET /health
- POST /eval-tests/run-once
- POST /eval-tests/generate/{suggestionId}
- GET /eval-tests/{suggestionId}
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi import HTTPException

from src.common.config import load_eval_test_generator_settings
from src.common.logging import get_logger
from src.generators.eval_tests.eval_test_service import EvalTestService
from src.generators.eval_tests.firestore_repository import FirestoreRepository
from src.generators.eval_tests.gemini_client import GeminiClient
from src.generators.eval_tests.models import (
    ApprovalMetadata,
    EvalTestArtifactResponse,
    EvalTestDraft,
    EvalTestGenerateRequest,
    EvalTestOutcomeStatus,
    EvalTestRunRequest,
    SuggestionStatus,
    TriggeredBy,
)

VERSION = "0.1.0"

logger = get_logger(__name__)

app = FastAPI(
    title="Evalforge Eval Test Generator",
    description="Generates eval test drafts from eval-type suggestions.",
    version=VERSION,
)

_service: Optional[EvalTestService] = None
_service_key: Optional[tuple] = None


def get_service() -> EvalTestService:
    global _service, _service_key

    settings = load_eval_test_generator_settings()
    key = (
        settings.firestore.project_id,
        settings.firestore.database_id,
        settings.firestore.collection_prefix,
        settings.gemini.model,
        settings.gemini.location,
        settings.gemini.temperature,
        settings.gemini.max_output_tokens,
        settings.batch_size,
        settings.per_suggestion_timeout_sec,
        settings.cost_budget_usd_per_suggestion,
        settings.run_cost_budget_usd,
    )

    if _service is None or _service_key != key:
        repository = FirestoreRepository(settings.firestore)
        gemini_client = GeminiClient(settings.gemini)
        _service = EvalTestService(settings=settings, repository=repository, gemini_client=gemini_client)
        _service_key = key
    return _service


@app.post("/eval-tests/run-once")
def run_once(body: EvalTestRunRequest | None = None):
    """Trigger a single batch run to generate eval test drafts."""
    try:
        settings = load_eval_test_generator_settings()
        request = body or EvalTestRunRequest()

        batch_size = request.batch_size or settings.batch_size
        dry_run = bool(request.dry_run) if request.dry_run is not None else False
        suggestion_ids = request.suggestion_ids
        triggered_by = request.triggered_by or TriggeredBy.MANUAL

        service = get_service()
        summary = service.run_batch(
            batch_size=batch_size,
            triggered_by=triggered_by,
            dry_run=dry_run,
            suggestion_ids=suggestion_ids,
        )

        return summary.model_dump(by_alias=True, mode="json")
    except Exception as exc:
        logger.exception("eval_tests_run_once_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="eval test run failed") from exc


@app.post("/eval-tests/generate/{suggestion_id}")
def generate_one(suggestion_id: str, body: EvalTestGenerateRequest | None = None):
    """Generate or regenerate an eval test draft for a single suggestion."""
    try:
        request = body or EvalTestGenerateRequest()
        dry_run = bool(request.dry_run) if request.dry_run is not None else False
        force_overwrite = bool(request.force_overwrite) if request.force_overwrite is not None else False
        triggered_by = request.triggered_by or TriggeredBy.MANUAL

        service = get_service()
        result = service.generate_one(
            suggestion_id=suggestion_id,
            triggered_by=triggered_by,
            dry_run=dry_run,
            force_overwrite=force_overwrite,
        )

        if result.status == EvalTestOutcomeStatus.ERROR and result.error_reason == "not_found":
            raise HTTPException(status_code=404, detail="suggestion not found")
        if result.status == EvalTestOutcomeStatus.SKIPPED and result.error_reason == "overwrite_blocked":
            raise HTTPException(status_code=409, detail="overwrite blocked")
        if result.status == EvalTestOutcomeStatus.ERROR and result.error_reason == "rate_limit":
            raise HTTPException(status_code=429, detail="rate limited by Gemini")
        if result.status == EvalTestOutcomeStatus.ERROR:
            raise HTTPException(status_code=500, detail=result.error_reason or "generation failed")

        payload = {"suggestionId": suggestion_id, "status": result.status.value}
        if result.eval_test is not None:
            payload["evalTest"] = result.eval_test.model_dump(mode="json")
        return payload
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("eval_tests_generate_failed", extra={"suggestion_id": suggestion_id, "error": str(exc)})
        raise HTTPException(status_code=500, detail="eval test generation failed") from exc


@app.get("/eval-tests/{suggestion_id}")
def get_eval_test(suggestion_id: str):
    """Get the current eval test draft plus suggestion approval metadata."""
    try:
        service = get_service()
        suggestion = service.repository.get_suggestion(suggestion_id)
        if suggestion is None:
            raise HTTPException(status_code=404, detail="not found")

        eval_test_payload = ((suggestion.get("suggestion_content") or {}).get("eval_test")) or None
        if eval_test_payload is None:
            raise HTTPException(status_code=404, detail="not found")

        approval_payload = suggestion.get("approval_metadata")
        approval_metadata = ApprovalMetadata.model_validate(approval_payload) if approval_payload else None

        response = EvalTestArtifactResponse(
            suggestion_id=suggestion_id,
            suggestion_status=SuggestionStatus(suggestion.get("status", "pending")),
            approval_metadata=approval_metadata,
            eval_test=EvalTestDraft.model_validate(eval_test_payload),
        )
        return response.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("eval_tests_get_failed", extra={"suggestion_id": suggestion_id, "error": str(exc)})
        raise HTTPException(status_code=500, detail="eval test retrieval failed") from exc


@app.get("/health")
def health():
    """Health check endpoint - always returns 200.

    Uses graceful degradation if backend queries fail.
    """
    status = "ok"
    backlog_pending = None
    last_run = None
    config = None

    try:
        settings = load_eval_test_generator_settings()
        config = {
            "model": settings.gemini.model,
            "batchSize": settings.batch_size,
            "perSuggestionTimeoutSec": settings.per_suggestion_timeout_sec,
            "costBudgetUsdPerSuggestion": settings.cost_budget_usd_per_suggestion,
            "runCostBudgetUsd": settings.run_cost_budget_usd,
        }

        # Optional Firestore queries - fail gracefully
        try:
            service = get_service()
            repository = service.repository
            backlog_pending = repository.get_pending_eval_suggestions_count()
            last_run = repository.get_last_run_summary()
        except Exception as e:
            logger.warning(f"Health check: Firestore query failed: {e}")
            status = "degraded"

    except Exception as e:
        logger.warning(f"Health check: Settings load failed: {e}")
        status = "degraded"

    return {
        "status": status,
        "version": VERSION,
        "backlog": {"pendingEvalSuggestions": backlog_pending},
        "lastPersistentRun": last_run,
        "config": config,
    }
