"""Capture queue API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from google.cloud import firestore

from src.api import capture_queue
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
    except HTTPException:
        raise
    except Exception as exc:
        log_error(logger, "Failed to list capture queue", error=exc, trace_id=None)
        raise HTTPException(status_code=500, detail="Failed to fetch capture queue") from exc

    return {"items": records, "nextCursor": next_cursor}
