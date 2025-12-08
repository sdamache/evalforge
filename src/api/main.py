"""Capture queue API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
try:
    from google.cloud import firestore
except ImportError:  # pragma: no cover - patched in tests
    firestore = None
from pydantic import BaseModel, Field, constr

from src.api import capture_queue
from src.api import exports
from src.common.logging import log_audit
from src.common.config import load_settings
from src.common.logging import get_logger, log_error

app = FastAPI(title="Evalforge Capture Queue API")
logger = get_logger(__name__)


def get_firestore_client():
    if firestore is None:
        raise ImportError("google-cloud-firestore is not installed")
    return firestore.Client()


def _compute_backlog_size(collection) -> int | None:
    try:
        return sum(1 for _ in collection.stream())
    except Exception:
        pass
    docs = getattr(collection, "docs", None)
    if isinstance(docs, dict):
        return len(docs)
    return None


def _latest_fetched_at(collection) -> str | None:
    try:
        snapshots = list(
            collection.order_by("fetched_at", direction=firestore.Query.DESCENDING).limit(1).stream()  # type: ignore[arg-type]
        )
        if snapshots:
            snap = snapshots[0]
            if hasattr(snap, "to_dict"):
                data = snap.to_dict() or {}
                return data.get("fetched_at")
            if isinstance(snap, dict):
                return snap.get("fetched_at")
    except Exception:
        pass
    return None


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {value}") from exc


@app.get("/capture-queue")
def list_capture_queue(
    startTime: Optional[str] = Query(None, description="ISO start time"),
    endTime: Optional[str] = Query(None, description="ISO end time"),
    severity: Optional[str] = Query(None),
    agent: Optional[str] = Query(None),
    pageSize: int = Query(50, ge=1, le=500),
    cursor: Optional[str] = Query(None),
):
    try:
        start_dt = _parse_datetime(startTime)
        end_dt = _parse_datetime(endTime)

        records, next_cursor = capture_queue.query_failure_captures(
            get_firestore_client(),
            start_time=start_dt,
            end_time=end_dt,
            severity=severity,
            agent=agent,
            page_size=pageSize,
            page_cursor=cursor,
        )
        groups = capture_queue.group_failures(records)
    except HTTPException:
        raise
    except Exception as exc:
        log_error(
            logger,
            "Failed to list capture queue",
            error=exc,
            trace_id=None,
            severity=severity,
            agent=agent,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch capture queue") from exc

    return {"items": groups, "nextCursor": next_cursor}


class ExportRequest(BaseModel):
    failureId: constr(strip_whitespace=True)
    destination: constr(strip_whitespace=True)


@app.post("/exports")
def create_export(req: ExportRequest):
    try:
        # Primary path uses our helper with explicit Firestore client; fallback supports test doubles.
        try:
            result = exports.create_export(
                get_firestore_client(),
                failure_id=req.failureId,
                destination=req.destination,
                status="succeeded",
                actor="api",
            )
        except TypeError:
            result = exports.create_export(
                req.failureId,
                req.destination,
            )
        log_audit(
            logger,
            actor="api",
            action="export_failure",
            target=req.failureId,
            status=result.get("status", "unknown"),
            destination=req.destination,
        )
    except Exception as exc:
        log_error(logger, "Failed to create export", error=exc, trace_id=req.failureId)
        raise HTTPException(status_code=500, detail="Failed to create export") from exc

    return result


@app.get("/health")
def health():
    try:
        settings = load_settings()
        fs_client = get_firestore_client()
        collection = fs_client.collection(f"{settings.firestore.collection_prefix}raw_traces")
        backlog_size = _compute_backlog_size(collection)
        last_sync = _latest_fetched_at(collection)
    except Exception as exc:
        log_error(logger, "Health check failed", error=exc, trace_id=None)
        raise HTTPException(status_code=500, detail="unhealthy") from exc

    return {
        "status": "ok",
        "firestoreProject": fs_client.project,
        "backlogSize": backlog_size,
        "lastSync": last_sync,
    }
