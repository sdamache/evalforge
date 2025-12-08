from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


def test_run_once_writes_sanitized_failure(monkeypatch):
    # Import inside test to allow TDD development of ingestion.main.
    from src.ingestion import main as ingestion_main

    captured = []

    class FakeDoc:
        def __init__(self, doc_id: str):
            self.doc_id = doc_id

        def set(self, data):
            captured.append({"doc_id": self.doc_id, "data": data})

    class FakeCollection:
        def __init__(self):
            self.docs = {}

        def document(self, doc_id: str):
            doc = FakeDoc(doc_id)
            self.docs[doc_id] = doc
            return doc

    class FakeFirestore:
        def __init__(self):
            self.collections = {}

        def collection(self, name: str):
            if name not in self.collections:
                self.collections[name] = FakeCollection()
            return self.collections[name]

    # Patch env and Firestore client factory to use in-memory sink.
    monkeypatch.setenv("DATADOG_API_KEY", "test-key")
    monkeypatch.setenv("DATADOG_APP_KEY", "test-app")
    monkeypatch.setenv("DATADOG_SITE", "datadoghq.com")
    monkeypatch.setenv("TRACE_LOOKBACK_HOURS", "24")
    monkeypatch.setenv("QUALITY_THRESHOLD", "0.5")
    monkeypatch.setenv("FIRESTORE_COLLECTION_PREFIX", "evalforge_")

    monkeypatch.setattr(ingestion_main, "get_firestore_client", lambda: FakeFirestore())

    # Simulate Datadog trace payload containing PII that must be stripped/hashed.
    raw_trace = {
        "trace_id": "trace-001",
        "fetched_at": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "failure_type": "hallucination",
        "trace_payload": {
            "user": {"email": "pii@example.com", "id": "user-123"},
            "input": "sensitive prompt",
            "output": "bad response",
        },
        "service_name": "llm-agent",
        "severity": "high",
        "processed": False,
        "recurrence_count": 1,
        "status_code": 500,
        "quality_score": 0.2,
    }

    def fake_fetch_recent_failures(*_, **__):
        return [raw_trace]

    monkeypatch.setattr(ingestion_main.datadog_client, "fetch_recent_failures", fake_fetch_recent_failures)

    def fake_sanitize_trace(payload):
        assert "user" in payload.get("trace_payload", {})  # ensure sanitizer sees raw PII
        return {"input": "[redacted]", "output": "[redacted]"}, "hashed-user-123"

    monkeypatch.setattr(ingestion_main.pii_sanitizer, "sanitize_trace", fake_sanitize_trace)

    client = TestClient(ingestion_main.app)
    resp = client.post(
        "/ingestion/run-once",
        json={"traceLookbackHours": 12, "qualityThreshold": 0.4},
    )

    assert resp.status_code == 202
    assert captured, "expected Firestore writes"
    saved = captured[0]["data"]

    assert saved["trace_id"] == "trace-001"
    assert saved["service_name"] == "llm-agent"
    assert saved["severity"] == "high"
    assert saved["recurrence_count"] == 1

    # Sanitized payload should contain redactions and hashed user ID.
    assert saved["trace_payload"]["input"] == "[redacted]"
    assert saved["trace_payload"]["output"] == "[redacted]"
    assert saved["user_hash"] == "hashed-user-123"
    assert "user" not in saved["trace_payload"]  # no raw PII fields

    # Date-time should be ISO formatted to match contract (parseable).
    datetime.fromisoformat(saved["fetched_at"])
