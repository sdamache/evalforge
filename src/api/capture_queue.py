"""Firestore query helper for failure capture queue."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import firestore

from src.common.config import load_settings
from src.common.logging import get_logger, log_error

logger = get_logger(__name__)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def query_failure_captures(
    firestore_client: firestore.Client,
    *,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    severity: Optional[str] = None,
    agent: Optional[str] = None,
    page_size: int = 50,
    page_cursor: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Read FailureCapture documents with filters and pagination.

    Returns (records, next_cursor) where cursor is the last fetched_at ISO string.
    """
    settings = load_settings()
    collection = firestore_client.collection(f"{settings.firestore.collection_prefix}raw_traces")

    query = collection.order_by("fetched_at", direction=firestore.Query.DESCENDING)

    if start_time:
        query = query.where("fetched_at", ">=", _iso(start_time))
    if end_time:
        query = query.where("fetched_at", "<=", _iso(end_time))
    if severity:
        query = query.where("severity", "==", severity)
    if agent:
        query = query.where("service_name", "==", agent)
    if page_cursor:
        query = query.start_after(page_cursor)

    query = query.limit(page_size)

    try:
        docs = list(query.stream())
    except Exception as exc:
        log_error(
            logger,
            "Failed to query capture queue",
            error=exc,
            trace_id=None,
        )
        raise

    records = []
    next_cursor = None
    for doc in docs:
        data = doc.to_dict()
        if not data:
            continue
        records.append(data)
    if records:
        next_cursor = records[-1].get("fetched_at")

    return records, next_cursor


def group_failures(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Group failures by signature (failure_type, service_name, severity) and sum recurrence.
    """
    grouped: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for rec in records:
        key = (
            rec.get("failure_type", ""),
            rec.get("service_name", ""),
            rec.get("severity", ""),
        )
        entry = grouped.setdefault(
            key,
            {
                "failure_type": rec.get("failure_type", ""),
                "service_name": rec.get("service_name", ""),
                "severity": rec.get("severity", ""),
                "recurrence_count": 0,
                "latest_fetched_at": rec.get("fetched_at"),
                "trace_ids": [],
            },
        )
        entry["recurrence_count"] += rec.get("recurrence_count", 1)
        fetched_at = rec.get("fetched_at")
        if fetched_at and (entry["latest_fetched_at"] is None or fetched_at > entry["latest_fetched_at"]):
            entry["latest_fetched_at"] = fetched_at
        trace_id = rec.get("trace_id")
        if trace_id:
            entry["trace_ids"].append(trace_id)

    return list(grouped.values())
