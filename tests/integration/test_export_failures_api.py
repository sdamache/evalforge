from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.mark.xfail(reason="export API not implemented yet")
def test_export_failure(monkeypatch):
    from src.api import main as api_main

    captured = []

    class FakeExports:
        def create_export(self, failure_id: str, destination: str):
            captured.append({"failure_id": failure_id, "destination": destination})
            return {
                "failure_trace_id": failure_id,
                "exported_at": datetime.now(tz=timezone.utc).isoformat(),
                "destination": destination,
                "status": "succeeded",
            }

    monkeypatch.setattr(api_main, "get_firestore_client", lambda: "fake-firestore")
    monkeypatch.setattr(api_main, "exports", FakeExports())

    client = TestClient(api_main.app)
    resp = client.post(
        "/exports",
        json={"failureId": "trace-123", "destination": "eval_backlog"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["failure_trace_id"] == "trace-123"
    assert captured[0]["destination"] == "eval_backlog"
