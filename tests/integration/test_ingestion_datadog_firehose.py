from datetime import datetime

import pytest

from src.ingestion import pii_sanitizer
from src.common.testing import run_ingestion_once

pytestmark = pytest.mark.integration


def _has_dotted_field(payload: dict, dotted: str) -> bool:
    target = payload
    for part in dotted.split("."):
        if not isinstance(target, dict) or part not in target:
            return False
        target = target[part]
    return True


def test_run_once_writes_sanitized_failure_live(monkeypatch):
    ctx = run_ingestion_once(monkeypatch, label="firehose")
    capture = ctx["captures"][0]["data"]

    assert capture["trace_id"], "Expected Firestore capture to include a trace_id"
    fetched_at = capture.get("fetched_at")
    assert fetched_at, "Expected fetched_at timestamp on stored capture"
    datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))

    payload = capture.get("trace_payload", {})
    for dotted in pii_sanitizer.PII_FIELDS_TO_STRIP:
        assert not _has_dotted_field(payload, dotted), f"PII field {dotted} leaked into stored capture payload"
    for text_field in ("input", "output", "prompt", "response"):
        if text_field in payload:
            assert payload[text_field] == "[redacted]"

    history = capture.get("status_history")
    assert history, "Status history should record ingestion state"
    assert history[0]["status"] == "new"
    assert capture.get("status") in {"new", "triaged", "exported"}

    health = ctx["health"]
    assert health["status"] in {"ok", "degraded"}
    last = health["lastIngestion"]
    assert last["trace_lookback_hours"] is not None
    assert last["quality_threshold"] is not None
    assert last["written_count"] >= len(ctx["captures"])
    assert health["rateLimit"] is not None
