import pytest
from fastapi.testclient import TestClient

from src.common.testing import prepare_empty_prefix, run_ingestion_once

pytestmark = pytest.mark.integration


def test_capture_queue_filters_live(monkeypatch):
    run_ingestion_once(monkeypatch, label="queue")
    from src.api import main as api_main

    client = TestClient(api_main.app)
    resp = client.get("/capture-queue", params={"pageSize": 10})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    if not body["items"]:
        pytest.skip("Capture queue empty; ensure Datadog has recent failures to ingest.")

    first = body["items"][0]
    assert first["trace_ids"], "Grouped capture should include trace IDs"
    assert first["recurrence_count"] >= 1
    coverage = body["coverage"]
    assert coverage["backfillStatus"] in {"complete", "partial"}

    severity = first.get("severity")
    agent = first.get("service_name")
    filters = {"pageSize": 5}
    if severity:
        filters["severity"] = severity
    if agent:
        filters["agent"] = agent

    if len(filters) > 1:
        filtered_resp = client.get("/capture-queue", params=filters)
        assert filtered_resp.status_code == 200
        filtered = filtered_resp.json()
        assert filtered["items"], "Expected filtered queue results"
        filtered_ids = {tid for group in filtered["items"] for tid in group.get("trace_ids", [])}
        assert any(tid in filtered_ids for tid in first.get("trace_ids", [])), "Filters should retain related traces"


def test_capture_queue_empty_state_live(monkeypatch):
    prepare_empty_prefix(monkeypatch, label="queue_empty")
    from src.api import main as api_main

    client = TestClient(api_main.app)
    resp = client.get("/capture-queue")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["coverage"]["empty"] is True
    assert "No incidents" in body["coverage"]["message"]
