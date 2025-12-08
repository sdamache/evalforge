"""Ingestion orchestrator and FastAPI app."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from google.cloud import firestore
from pydantic import BaseModel, Field, PositiveInt

from src.common.config import load_settings
from src.common.logging import get_logger, log_decision, log_error
from src.ingestion import datadog_client, pii_sanitizer
from src.ingestion.models import FailureCapture

app = FastAPI(title="Evalforge Datadog Ingestion")
logger = get_logger(__name__)


def get_firestore_client():
    return firestore.Client()


class RunOnceRequest(BaseModel):
    traceLookbackHours: Optional[PositiveInt] = Field(None, description="Override lookback window in hours")
    qualityThreshold: Optional[float] = Field(None, description="Override quality score threshold")


def deduplicate_by_trace_id(traces: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = {}
    for trace in traces:
        tid = trace.get("trace_id")
        if not tid:
            continue
        if tid in seen:
            seen[tid]["recurrence_count"] = seen[tid].get("recurrence_count", 1) + 1
        else:
            seen[tid] = trace
    return list(seen.values())


def _write_failure(firestore_client, collection_name: str, capture: FailureCapture) -> None:
    doc_ref = firestore_client.collection(collection_name).document(capture.trace_id)
    doc_ref.set(capture.to_dict())


def run_ingestion(trace_lookback_hours: int, quality_threshold: float) -> int:
    settings = load_settings()
    events = datadog_client.fetch_recent_failures(
        trace_lookback_hours=trace_lookback_hours,
        quality_threshold=quality_threshold,
        service_name=None,
    )
    events = deduplicate_by_trace_id(events)
    fs_client = get_firestore_client()
    collection_name = f"{settings.firestore.collection_prefix}raw_traces"

    written = 0
    for event in events:
        trace_id = event.get("trace_id") or event.get("id")
        if not trace_id:
            log_error(logger, "Skipping event without trace_id", trace_id=None)
            continue
        try:
            sanitized_payload, user_hash = pii_sanitizer.sanitize_trace(event)
            capture = FailureCapture(
                trace_id=trace_id,
                fetched_at=datetime.now(tz=timezone.utc),
                failure_type=event.get("failure_type", "unknown"),
                trace_payload=sanitized_payload,
                service_name=event.get("service_name", ""),
                severity=event.get("severity", ""),
                status_code=event.get("status_code"),
                quality_score=event.get("quality_score"),
                user_hash=user_hash if user_hash else None,
                processed=False,
                recurrence_count=event.get("recurrence_count", 1),
            )
            _write_failure(fs_client, collection_name, capture)
            log_decision(logger, trace_id=trace_id, action="ingest", outcome="written")
            written += 1
        except Exception as exc:  # capture-level errors should not halt the batch
            log_error(logger, "Failed to process trace", error=exc, trace_id=trace_id)
            continue
    return written


@app.post("/ingestion/run-once", status_code=202)
def run_once(body: RunOnceRequest | None = None):
    try:
        written = run_ingestion(
            trace_lookback_hours=body.traceLookbackHours if body and body.traceLookbackHours else load_settings().datadog.trace_lookback_hours,
            quality_threshold=body.qualityThreshold if body and body.qualityThreshold is not None else load_settings().datadog.quality_threshold,
        )
    except Exception as exc:
        log_error(logger, "Ingestion failed", error=exc, trace_id=None)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"startedAt": datetime.now(tz=timezone.utc).isoformat(), "estimatedTraceCount": written}


@app.get("/health")
def health():
    try:
        settings = load_settings()

        # Firestore client instantiation (no remote call).
        get_firestore_client().project

        # Datadog client instantiation (no remote call to avoid network dependency in health).
        datadog_client._create_api(settings)  # noqa: SLF001
    except Exception as exc:
        log_error(logger, "Health check failed", error=exc, trace_id=None)
        raise HTTPException(status_code=500, detail="unhealthy") from exc
    return {"status": "ok"}
