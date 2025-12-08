import pathlib
from datetime import datetime, timezone

import yaml

from src.ingestion.models import FailureCapture


def load_failure_capture_schema():
    spec_path = pathlib.Path("specs/001-capture-datadog-failures/contracts/ingestion-openapi.yaml")
    spec = yaml.safe_load(spec_path.read_text())
    return spec["components"]["schemas"]["FailureCapture"]


def test_failure_capture_matches_contract_required_fields():
    schema = load_failure_capture_schema()
    required_fields = set(schema.get("required", []))
    required_properties = schema.get("properties", {})

    sample = FailureCapture(
        trace_id="trace-123",
        fetched_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        failure_type="hallucination",
        trace_payload={"input": "hi", "output": "bye"},
        service_name="llm-agent",
        severity="high",
        processed=False,
        recurrence_count=1,
        status_code=500,
        quality_score=0.2,
        user_hash="abc123",
    ).to_dict()

    # Required keys should all be present in the serialized payload
    assert required_fields.issubset(sample.keys())

    # Check basic type expectations from the schema for required fields
    assert isinstance(sample["trace_id"], str)
    assert isinstance(sample["failure_type"], str)
    assert isinstance(sample["trace_payload"], dict)
    assert isinstance(sample["service_name"], str)
    assert isinstance(sample["severity"], str)
    assert isinstance(sample["processed"], bool)
    assert isinstance(sample["recurrence_count"], int)

    # fetched_at should be an ISO 8601 string (OpenAPI date-time)
    datetime.fromisoformat(sample["fetched_at"])

    # Optional fields included in sample should have expected types when present
    assert isinstance(sample["status_code"], int)
    assert isinstance(sample["quality_score"], float)
    assert isinstance(sample["user_hash"], str)

    # Ensure we don't emit unexpected properties beyond the schema
    assert set(sample.keys()).issubset(set(required_properties.keys()))
