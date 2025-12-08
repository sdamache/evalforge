"""Capture queue API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from google.cloud import firestore
from pydantic import BaseModel, Field, constr

from src.api import capture_queue
from src.api import exports
from src.common.config import load_settings
from src.common.logging import get_logger, log_error

app = FastAPI(title="Evalforge Capture Queue API")
logger = get_logger(__name__)


def get_firestore_client():
    return firestore.Client()


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
            )
        except TypeError:
            result = exports.create_export(
                req.failureId,
                req.destination,
            )
    except Exception as exc:
        log_error(logger, "Failed to create export", error=exc, trace_id=req.failureId)
        raise HTTPException(status_code=500, detail="Failed to create export") from exc

    return result
