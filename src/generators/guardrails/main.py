"""FastAPI service for generating guardrail rule drafts.

Endpoints (see specs/005-guardrail-generation/contracts/guardrail-generator-openapi.yaml):
- GET /health
- POST /guardrails/run-once
- POST /guardrails/generate/{suggestionId}
- GET /guardrails/{suggestionId}
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response

from src.common.config import load_guardrail_generator_settings
from src.common.logging import get_logger
from src.generators.guardrails.firestore_repository import FirestoreRepository
from src.generators.guardrails.gemini_client import GeminiClient
from src.generators.guardrails.guardrail_service import GuardrailService
from src.generators.guardrails.models import (
    ApprovalMetadata,
    GuardrailArtifactResponse,
    GuardrailDraft,
    GuardrailGenerateRequest,
    GuardrailOutcomeStatus,
    GuardrailRunRequest,
    SuggestionStatus,
    TriggeredBy,
)
from src.generators.guardrails.yaml_export import guardrail_to_yaml


class ExportFormat(str, Enum):
    """Supported export formats for guardrail drafts."""

    JSON = "json"
    YAML = "yaml"

VERSION = "0.1.0"

logger = get_logger(__name__)


def _snake_to_camel(s: str) -> str:
    """Convert snake_case to camelCase."""
    parts = s.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def _convert_keys_to_camel(data: dict) -> dict:
    """Convert all dict keys from snake_case to camelCase."""
    if data is None:
        return None
    result = {}
    for key, value in data.items():
        camel_key = _snake_to_camel(key)
        if isinstance(value, dict):
            result[camel_key] = _convert_keys_to_camel(value)
        elif isinstance(value, list):
            result[camel_key] = [
                _convert_keys_to_camel(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[camel_key] = value
    return result

app = FastAPI(
    title="Evalforge Guardrail Generator",
    description="Generates guardrail rule drafts from guardrail-type suggestions.",
    version=VERSION,
)

_service: Optional[GuardrailService] = None
_service_key: Optional[tuple] = None


def get_service() -> GuardrailService:
    """Get or create a singleton GuardrailService instance.

    The service is re-created if settings change (e.g., different model config).
    """
    global _service, _service_key

    settings = load_guardrail_generator_settings()
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
        _service = GuardrailService(
            settings=settings,
            repository=repository,
            gemini_client=gemini_client,
        )
        _service_key = key
    return _service


@app.post("/guardrails/run-once")
def run_once(body: GuardrailRunRequest | None = None):
    """Trigger a single batch run to generate guardrail drafts.

    Queries pending guardrail-type suggestions and generates drafts for each.
    Returns a summary of the batch run with per-suggestion outcomes.
    """
    try:
        settings = load_guardrail_generator_settings()
        request = body or GuardrailRunRequest()

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
        logger.exception("guardrails_run_once_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="guardrail run failed") from exc


@app.post("/guardrails/generate/{suggestion_id}")
def generate_one(suggestion_id: str, body: GuardrailGenerateRequest | None = None):
    """Generate or regenerate a guardrail draft for a single suggestion.

    Use force_overwrite=true to regenerate drafts that have been human-edited.
    """
    try:
        request = body or GuardrailGenerateRequest()
        dry_run = bool(request.dry_run) if request.dry_run is not None else False
        force_overwrite = (
            bool(request.force_overwrite)
            if request.force_overwrite is not None
            else False
        )
        triggered_by = request.triggered_by or TriggeredBy.MANUAL

        service = get_service()
        result = service.generate_one(
            suggestion_id=suggestion_id,
            triggered_by=triggered_by,
            dry_run=dry_run,
            force_overwrite=force_overwrite,
        )

        if (
            result.status == GuardrailOutcomeStatus.ERROR
            and result.error_reason == "not_found"
        ):
            raise HTTPException(status_code=404, detail="suggestion not found")
        if (
            result.status == GuardrailOutcomeStatus.SKIPPED
            and result.error_reason == "overwrite_blocked"
        ):
            raise HTTPException(status_code=409, detail="overwrite blocked")
        if (
            result.status == GuardrailOutcomeStatus.ERROR
            and result.error_reason == "rate_limit"
        ):
            raise HTTPException(status_code=429, detail="rate limited by Gemini")
        if result.status == GuardrailOutcomeStatus.ERROR:
            raise HTTPException(
                status_code=500, detail=result.error_reason or "generation failed"
            )

        payload = {"suggestionId": suggestion_id, "status": result.status.value}
        if result.guardrail is not None:
            payload["guardrail"] = result.guardrail.model_dump(mode="json")
        return payload
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "guardrails_generate_failed",
            extra={"suggestion_id": suggestion_id, "error": str(exc)},
        )
        raise HTTPException(
            status_code=500, detail="guardrail generation failed"
        ) from exc


@app.get("/guardrails/{suggestion_id}")
def get_guardrail(
    suggestion_id: str,
    format: ExportFormat = Query(
        default=ExportFormat.JSON,
        description="Output format: json (default) or yaml for Datadog AI Guard",
    ),
):
    """Get the current guardrail draft plus suggestion approval metadata.

    Returns the guardrail draft with full lineage information for reviewer approval.
    Use format=yaml for Datadog AI Guard compatible output.
    """
    try:
        service = get_service()
        suggestion = service.repository.get_suggestion(suggestion_id)
        if suggestion is None:
            raise HTTPException(status_code=404, detail="not found")

        guardrail_payload = (
            (suggestion.get("suggestion_content") or {}).get("guardrail")
        ) or None
        if guardrail_payload is None:
            raise HTTPException(status_code=404, detail="not found")

        guardrail = GuardrailDraft.model_validate(guardrail_payload)

        # T018: YAML export support for Datadog AI Guard
        if format == ExportFormat.YAML:
            yaml_content = guardrail_to_yaml(guardrail)
            return Response(
                content=yaml_content,
                media_type="application/x-yaml",
                headers={"Content-Disposition": f"inline; filename={suggestion_id}.yaml"},
            )

        # Default JSON response with full context
        approval_payload = suggestion.get("approval_metadata")
        approval_metadata = (
            ApprovalMetadata.model_validate(approval_payload)
            if approval_payload
            else None
        )

        response = GuardrailArtifactResponse(
            suggestion_id=suggestion_id,
            suggestion_status=SuggestionStatus(suggestion.get("status", "pending")),
            approval_metadata=approval_metadata,
            guardrail=guardrail,
        )
        return response.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "guardrails_get_failed",
            extra={"suggestion_id": suggestion_id, "error": str(exc)},
        )
        raise HTTPException(
            status_code=500, detail="guardrail retrieval failed"
        ) from exc


@app.get("/health")
def health():
    """Health check endpoint with backlog count and configuration summary."""
    try:
        settings = load_guardrail_generator_settings()
        service = get_service()
        repository = service.repository

        backlog_pending = repository.get_pending_guardrail_suggestions_count()
        last_run_raw = repository.get_last_run_summary()
        # Convert snake_case keys to camelCase for API contract compliance
        last_run = _convert_keys_to_camel(last_run_raw) if last_run_raw else None

        return {
            "status": "ok",
            "version": VERSION,
            "backlog": {"pendingGuardrailSuggestions": backlog_pending},
            "lastPersistentRun": last_run,
            "config": {
                "model": settings.gemini.model,
                "batchSize": settings.batch_size,
                "perSuggestionTimeoutSec": settings.per_suggestion_timeout_sec,
                "costBudgetUsdPerSuggestion": settings.cost_budget_usd_per_suggestion,
                "runCostBudgetUsd": settings.run_cost_budget_usd,
            },
        }
    except Exception as exc:
        logger.exception("guardrails_health_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="unhealthy") from exc
