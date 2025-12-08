"""Ingestion orchestrator and FastAPI app."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
try:
    from google.cloud import firestore
except ImportError:  # pragma: no cover - patched in tests
    firestore = None
from pydantic import BaseModel, Field, PositiveInt

from src.common.config import load_settings
from src.common.logging import get_logger, log_decision, log_error
from src.ingestion import datadog_client, pii_sanitizer
from src.ingestion.models import FailureCapture

app = FastAPI(title="Evalforge Datadog Ingestion")
logger = get_logger(__name__)
LAST_INGESTION_HEALTH: Dict[str, Any] = {
    "last_sync": None,
    "written_count": 0,
    "backlog_size": None,
    "last_error": None,
    "trace_lookback_hours": None,
    "quality_threshold": None,
    "rate_limit": None,
}


def get_firestore_client():
    if firestore is None:
        raise ImportError("google-cloud-firestore is not installed")
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
            first = dict(trace)
            first["recurrence_count"] = first.get("recurrence_count", 1)
            seen[tid] = first
    return list(seen.values())


def _write_failure(firestore_client, collection_name: str, capture: FailureCapture) -> None:
    doc_ref = firestore_client.collection(collection_name).document(capture.trace_id)
    try:
        existing = doc_ref.get()
        existing_data = existing.to_dict() if hasattr(existing, "to_dict") else None
    except Exception:
        existing_data = None

    if existing_data:
        capture.status = existing_data.get("status", capture.status)
        capture.status_history = existing_data.get("status_history", capture.status_history)
        capture.export_status = existing_data.get("export_status", capture.export_status)
        capture.export_destination = existing_data.get("export_destination", capture.export_destination)
        capture.export_reference = existing_data.get("export_reference", capture.export_reference)

    doc_ref.set(capture.to_dict())


def _compute_backlog_size(fs_client, collection_name: str) -> Optional[int]:
    collection = fs_client.collection(collection_name)
    # Prefer stream counting for compatibility with FakeFirestore in tests.
    try:
        return sum(1 for _ in collection.stream())
    except Exception:
        pass
    docs = getattr(collection, "docs", None)
    if isinstance(docs, dict):
        return len(docs)
    return None


def _update_health(
    *,
    last_sync: datetime,
    written_count: int,
    backlog_size: Optional[int],
    trace_lookback_hours: int,
    quality_threshold: float,
    last_error: Optional[str] = None,
) -> None:
    LAST_INGESTION_HEALTH.update(
        {
            "last_sync": last_sync.isoformat(),
            "written_count": written_count,
            "backlog_size": backlog_size,
            "last_error": last_error,
            "trace_lookback_hours": trace_lookback_hours,
            "quality_threshold": quality_threshold,
            "rate_limit": datadog_client.get_last_rate_limit_state(),
        }
    )


def run_ingestion(trace_lookback_hours: int, quality_threshold: float) -> int:
    settings = load_settings()
    fetch_start = time.perf_counter()
    events = datadog_client.fetch_recent_failures(
        trace_lookback_hours=trace_lookback_hours,
        quality_threshold=quality_threshold,
        service_name=None,
    )
    fetch_duration = time.perf_counter() - fetch_start

    events = deduplicate_by_trace_id(events)
    fs_client = get_firestore_client()
    collection_name = f"{settings.firestore.collection_prefix}raw_traces"

    written = 0
    last_error: Optional[str] = None
    process_start = time.perf_counter()
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
                status_history=[
                    {
                        "status": "new",
                        "actor": "ingestion",
                        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    }
                ],
            )
            _write_failure(fs_client, collection_name, capture)
            log_decision(logger, trace_id=trace_id, action="ingest", outcome="written")
            written += 1
        except Exception as exc:  # capture-level errors should not halt the batch
            log_error(logger, "Failed to process trace", error=exc, trace_id=trace_id)
            last_error = str(exc)
            continue
    process_duration = time.perf_counter() - process_start

    backlog_size = _compute_backlog_size(fs_client, collection_name)
    now = datetime.now(tz=timezone.utc)
    _update_health(
        last_sync=now,
        written_count=written,
        backlog_size=backlog_size,
        trace_lookback_hours=trace_lookback_hours,
        quality_threshold=quality_threshold,
        last_error=last_error,
    )

    logger.info(
        "ingestion_metrics",
        extra={
            "event": "ingestion_metrics",
            "fetched_count": len(events),
            "written_count": written,
            "fetch_duration_sec": round(fetch_duration, 3),
            "process_duration_sec": round(process_duration, 3),
            "backlog_size": backlog_size,
        },
    )
    return written


def _resolve_ingestion_params(body: RunOnceRequest | None) -> tuple[int, float]:
    settings = load_settings()
    lookback = body.traceLookbackHours if body and body.traceLookbackHours else settings.datadog.trace_lookback_hours
    quality = body.qualityThreshold if body and body.qualityThreshold is not None else settings.datadog.quality_threshold
    return lookback, quality


@app.post("/ingestion/run-once", status_code=202)
def run_once(body: RunOnceRequest | None = None):
    try:
        lookback_hours, quality_threshold = _resolve_ingestion_params(body)
        written = run_ingestion(trace_lookback_hours=lookback_hours, quality_threshold=quality_threshold)
    except Exception as exc:
        log_error(logger, "Ingestion failed", error=exc, trace_id=None)
        _update_health(
            last_sync=datetime.now(tz=timezone.utc),
            written_count=0,
            backlog_size=None,
            trace_lookback_hours=body.traceLookbackHours if body else load_settings().datadog.trace_lookback_hours,
            quality_threshold=body.qualityThreshold if body and body.qualityThreshold is not None else load_settings().datadog.quality_threshold,
            last_error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "startedAt": datetime.now(tz=timezone.utc).isoformat(),
        "estimatedTraceCount": written,
        "traceLookbackHours": lookback_hours,
        "qualityThreshold": quality_threshold,
    }


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
    return {
        "status": "ok" if LAST_INGESTION_HEALTH.get("last_error") is None else "degraded",
        "lastIngestion": LAST_INGESTION_HEALTH,
        "rateLimit": datadog_client.get_last_rate_limit_state(),
        "firestoreProject": get_firestore_client().project,
    }
