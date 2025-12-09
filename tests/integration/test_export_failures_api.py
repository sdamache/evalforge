import os

import pytest
from fastapi.testclient import TestClient

from src.common.testing import run_ingestion_once

pytestmark = pytest.mark.integration


def test_export_failure_live(monkeypatch):
    ctx = run_ingestion_once(monkeypatch, label="export")
    from src.api import main as api_main

    destination = os.getenv("LIVE_TEST_EXPORT_DESTINATION", "eval_backlog")
    trace_id = ctx["captures"][0]["data"]["trace_id"]

    client = TestClient(api_main.app)
    resp = client.post("/exports", json={"failureId": trace_id, "destination": destination})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["failure_trace_id"] == trace_id
    assert body["coverage"]["backfillStatus"] == "unknown"
    assert destination in body["coverage"]["message"]

    fs_client = ctx["firestore_client"]
    export_docs = list(fs_client.collection(f"{ctx['prefix']}exports").stream())
    if not export_docs:
        pytest.fail("Expected export record to be persisted in Firestore")
    assert any(doc.to_dict().get("failure_trace_id") == trace_id for doc in export_docs)

    capture_ref = fs_client.collection(f"{ctx['prefix']}raw_traces").document(trace_id)
    capture = capture_ref.get().to_dict()
    assert capture["status"] == "exported"
    assert capture.get("export_destination") == destination
    assert any(entry.get("status") == "exported" for entry in capture.get("status_history", []))
