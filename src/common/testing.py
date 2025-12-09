"""Testing helpers for integration/smoke runs against live services."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

try:
    from google.cloud import firestore
except ImportError:  # pragma: no cover - optional dependency for live tests
    firestore = None

from src.common.config import ConfigError, load_settings

FIRESTORE_CREDENTIAL_HINTS = (
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_PROJECT",
    "FIRESTORE_EMULATOR_HOST",
)


def _require_firestore():
    if firestore is None:
        pytest.skip("google-cloud-firestore is required to run live integration tests.")


def require_live_services() -> None:
    """Skip the test unless live Datadog + Firestore credentials are configured."""
    if os.getenv("RUN_LIVE_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_TESTS=1 to enable live integration tests.")
    try:
        load_settings()
    except ConfigError as exc:
        pytest.skip(f"Live integration tests require valid configuration: {exc}")
    if not any(os.getenv(env) for env in FIRESTORE_CREDENTIAL_HINTS):
        pytest.skip(
            "Provide Firestore credentials via GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_CLOUD_PROJECT "
            "to run live integration tests."
        )
    _require_firestore()


def _parse_iso(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None
    ts = timestamp
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _ensure_firestore_prefix(monkeypatch, *, label: str) -> str:
    base = os.getenv("LIVE_TEST_COLLECTION_PREFIX")
    suffix = uuid4().hex[:6]
    prefix = f"{base.rstrip('_')}_{label}_{suffix}_" if base else f"test_{label}_{suffix}_"
    monkeypatch.setenv("FIRESTORE_COLLECTION_PREFIX", prefix)
    return prefix


def _recent_captures(fs_client, collection_name: str, start_time: datetime, limit: int = 25) -> List[Dict[str, Any]]:
    tolerance = timedelta(minutes=int(os.getenv("LIVE_TEST_CAPTURE_TOLERANCE_MINUTES", "15")))
    collection = fs_client.collection(collection_name)
    query = collection.order_by("fetched_at", direction=firestore.Query.DESCENDING).limit(limit)  # type: ignore[arg-type]
    captures: List[Dict[str, Any]] = []
    for snapshot in query.stream():
        data = snapshot.to_dict() or {}
        fetched_at = _parse_iso(data.get("fetched_at"))
        if fetched_at and fetched_at >= start_time - tolerance:
            captures.append({"id": snapshot.id, "data": data})
    return captures


def run_ingestion_once(
    monkeypatch,
    *,
    label: str,
    trace_lookback_hours: int | None = None,
    quality_threshold: float | None = None,
) -> Dict[str, Any]:
    """
    Trigger /ingestion/run-once against live Datadog + Firestore and return captured docs.
    """
    require_live_services()
    prefix = _ensure_firestore_prefix(monkeypatch, label=label)
    from src.ingestion import main as ingestion_main  # imported lazily to use patched env

    client = TestClient(ingestion_main.app)
    payload: Dict[str, Any] = {}
    if trace_lookback_hours is not None:
        payload["traceLookbackHours"] = trace_lookback_hours
    if quality_threshold is not None:
        payload["qualityThreshold"] = quality_threshold
    body = payload or None

    start_time = datetime.now(tz=timezone.utc)
    response = client.post("/ingestion/run-once", json=body)
    if response.status_code == 401:
        pytest.skip("Datadog credentials rejected; provide valid live credentials to run integration tests.")
    if response.status_code == 429:
        pytest.skip("Datadog rate limit reached; retry the live integration test later.")
    assert response.status_code == 202, response.text

    health_resp = client.get("/health")
    assert health_resp.status_code == 200, health_resp.text

    fs_client = ingestion_main.get_firestore_client()
    collection_name = f"{prefix}raw_traces"
    captures = _recent_captures(fs_client, collection_name, start_time=start_time)
    if not captures:
        pytest.skip(
            "No Datadog failure traces were ingested during the test window. "
            "Trigger a failure trace and rerun RUN_LIVE_TESTS."
        )

    return {
        "prefix": prefix,
        "captures": captures,
        "firestore_client": fs_client,
        "collection_name": collection_name,
        "ingestion_response": response.json(),
        "health": health_resp.json(),
    }


def prepare_empty_prefix(monkeypatch, *, label: str) -> str:
    """Set a unique Firestore prefix for empty-state tests."""
    require_live_services()
    return _ensure_firestore_prefix(monkeypatch, label=label)
