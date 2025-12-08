from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


def test_capture_queue_filters(monkeypatch):
    from src.api import main as api_main

    calls = []

    def fake_query(
        client,
        *,
        start_time=None,
        end_time=None,
        severity=None,
        agent=None,
        page_size=50,
        page_cursor=None,
    ):
        calls.append(
            {
                "start_time": start_time,
                "end_time": end_time,
                "severity": severity,
                "agent": agent,
                "page_size": page_size,
                "page_cursor": page_cursor,
            }
        )
        return (
            [
                {
                    "trace_id": "t1",
                    "fetched_at": "2025-01-02T00:00:00+00:00",
                    "severity": "high",
                    "service_name": "agent-a",
                    "failure_type": "hallucination",
                    "recurrence_count": 1,
                },
                {
                    "trace_id": "t2",
                    "fetched_at": "2025-01-01T18:00:00+00:00",
                    "severity": "high",
                    "service_name": "agent-a",
                    "failure_type": "hallucination",
                    "recurrence_count": 2,
                },
            ],
            "cursor-123",
        )

    monkeypatch.setattr(api_main, "get_firestore_client", lambda: "fake-client")
    monkeypatch.setattr(api_main.capture_queue, "query_failure_captures", fake_query)

    client = TestClient(api_main.app)

    start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2025, 1, 3, 0, 0, tzinfo=timezone.utc)

    resp = client.get(
        "/capture-queue",
        params={
            "startTime": start.isoformat(),
            "endTime": end.isoformat(),
            "severity": "high",
            "agent": "agent-a",
            "pageSize": 10,
            "cursor": "prev-cursor",
        },
    )

    # Endpoint should succeed and return grouped items + cursor.
    assert resp.status_code == 200
    body = resp.json()
    item = body["items"][0]
    assert item["failure_type"] == "hallucination"
    assert item["service_name"] == "agent-a"
    assert item["severity"] == "high"
    assert item["recurrence_count"] == 3
    assert set(item["trace_ids"]) == {"t1", "t2"}
    assert body["nextCursor"] == "cursor-123"

    call = calls[0]
    assert call["severity"] == "high"
    assert call["agent"] == "agent-a"
    assert call["page_size"] == 10
    assert call["page_cursor"] == "prev-cursor"
    assert call["start_time"] == start
    assert call["end_time"] == end
