from src.ingestion.main import deduplicate_by_trace_id


def test_deduplicate_increments_recurrence_count():
    traces = [
        {"trace_id": "t1", "recurrence_count": 2},
        {"trace_id": "t1"},
        {"trace_id": "t2"},
    ]

    deduped = deduplicate_by_trace_id(traces)
    result = {t["trace_id"]: t for t in deduped}

    assert result["t1"]["recurrence_count"] == 3
    assert result["t2"]["recurrence_count"] == 1


def test_deduplicate_preserves_unique_traces():
    traces = [
        {"trace_id": "a"},
        {"trace_id": "b"},
    ]
    deduped = deduplicate_by_trace_id(traces)
    ids = {t["trace_id"] for t in deduped}
    assert ids == {"a", "b"}
