"""Contract test asserting stored FailurePattern payload matches OpenAPI schema.

This test validates that the FailurePattern.to_dict() output:
- Contains all required fields from the OpenAPI contract
- Uses correct field types
- Properly serializes nested objects
- Matches the exact schema expected by downstream consumers

Covers T026 requirements.
"""

import pathlib
from datetime import datetime, timezone

import yaml

from src.extraction.models import (
    Evidence,
    FailurePattern,
    FailureType,
    ReproductionContext,
    Severity,
)


def load_failure_pattern_schema():
    """Load FailurePattern schema from OpenAPI contract."""
    spec_path = pathlib.Path("specs/002-extract-failure-patterns/contracts/extraction-openapi.yaml")
    spec = yaml.safe_load(spec_path.read_text())
    return spec["components"]["schemas"]["FailurePattern"]


def test_failure_pattern_matches_contract_required_fields():
    """Test that FailurePattern.to_dict() contains all required fields from OpenAPI contract."""
    schema = load_failure_pattern_schema()
    required_fields = set(schema.get("required", []))
    required_properties = schema.get("properties", {})

    # Create a sample FailurePattern with all fields populated
    sample = FailurePattern(
        pattern_id="pattern_contract_test_001",
        source_trace_id="contract_test_001",
        title="Contract Test Pattern",
        failure_type=FailureType.HALLUCINATION,
        trigger_condition="Factual error in date",
        summary="Model stated incorrect construction date for the Eiffel Tower.",
        root_cause_hypothesis="Training data contamination or retrieval error.",
        evidence=Evidence(
            signals=["status_code: 200", "latency_ms: 380", "tokens_used: 45"],
            excerpt="The Eiffel Tower was built in 1920...",
        ),
        recommended_actions=[
            "Add fact-checking layer for historical dates",
            "Update training data sources",
        ],
        reproduction_context=ReproductionContext(
            input_pattern="Questions about construction dates of famous landmarks",
            required_state="No specific state required",
            tools_involved=["llm_call", "retrieval"],
        ),
        severity=Severity.HIGH,
        confidence=0.85,
        confidence_rationale="Clear factual error with sufficient context",
        extracted_at=datetime(2024, 12, 23, 10, 30, 0, tzinfo=timezone.utc),
    ).to_dict()

    # Verify all required fields are present
    assert required_fields.issubset(sample.keys()), f"Missing required fields: {required_fields - sample.keys()}"

    # Verify top-level field types match schema expectations
    assert isinstance(sample["pattern_id"], str)
    assert isinstance(sample["source_trace_id"], str)
    assert isinstance(sample["title"], str)
    assert isinstance(sample["failure_type"], str)
    assert isinstance(sample["trigger_condition"], str)
    assert isinstance(sample["summary"], str)
    assert isinstance(sample["root_cause_hypothesis"], str)
    assert isinstance(sample["evidence"], dict)
    assert isinstance(sample["recommended_actions"], list)
    assert isinstance(sample["reproduction_context"], dict)
    assert isinstance(sample["severity"], str)
    assert isinstance(sample["confidence"], (int, float))
    assert isinstance(sample["confidence_rationale"], str)
    assert isinstance(sample["extracted_at"], str)

    # Verify failure_type is a valid enum value
    assert sample["failure_type"] in [
        "hallucination",
        "toxicity",
        "wrong_tool",
        "runaway_loop",
        "pii_leak",
        "stale_data",
        "infrastructure_error",
        "client_error",
    ]

    # Verify severity is a valid enum value
    assert sample["severity"] in ["low", "medium", "high", "critical"]

    # Verify confidence is in valid range
    assert 0.0 <= sample["confidence"] <= 1.0

    # Verify extracted_at is valid ISO 8601 format
    datetime.fromisoformat(sample["extracted_at"])

    # Verify evidence nested structure
    assert "signals" in sample["evidence"]
    assert isinstance(sample["evidence"]["signals"], list)
    assert len(sample["evidence"]["signals"]) >= 1  # minItems: 1 in schema
    assert all(isinstance(s, str) for s in sample["evidence"]["signals"])
    if "excerpt" in sample["evidence"]:
        assert isinstance(sample["evidence"]["excerpt"], str)

    # Verify recommended_actions list constraints
    assert isinstance(sample["recommended_actions"], list)
    assert len(sample["recommended_actions"]) >= 1  # minItems: 1 in schema
    assert all(isinstance(a, str) for a in sample["recommended_actions"])

    # Verify reproduction_context nested structure
    assert "input_pattern" in sample["reproduction_context"]
    assert isinstance(sample["reproduction_context"]["input_pattern"], str)
    assert "tools_involved" in sample["reproduction_context"]
    assert isinstance(sample["reproduction_context"]["tools_involved"], list)
    if "required_state" in sample["reproduction_context"]:
        assert isinstance(sample["reproduction_context"]["required_state"], str)

    # Ensure no unexpected fields beyond the contract
    # (All fields in sample should be defined in the schema)
    unexpected = set(sample.keys()) - set(required_properties.keys())
    assert not unexpected, f"Unexpected fields not in contract: {unexpected}"


def test_failure_pattern_serialization_stability():
    """Test that FailurePattern serialization produces consistent output structure."""
    # Create two identical patterns
    kwargs = {
        "pattern_id": "pattern_stability_test",
        "source_trace_id": "stability_test",
        "title": "Stability Test",
        "failure_type": FailureType.WRONG_TOOL,
        "trigger_condition": "Wrong tool selected",
        "summary": "Test summary",
        "root_cause_hypothesis": "Test hypothesis",
        "evidence": Evidence(signals=["signal1"]),
        "recommended_actions": ["action1"],
        "reproduction_context": ReproductionContext(
            input_pattern="test pattern",
            tools_involved=["tool1"],
        ),
        "severity": Severity.MEDIUM,
        "confidence": 0.7,
        "confidence_rationale": "Test rationale",
        "extracted_at": datetime(2024, 12, 23, 12, 0, 0, tzinfo=timezone.utc),
    }

    pattern1 = FailurePattern(**kwargs).to_dict()
    pattern2 = FailurePattern(**kwargs).to_dict()

    # Serialization should be deterministic
    assert pattern1 == pattern2

    # Verify all keys are strings (Firestore compatibility)
    assert all(isinstance(k, str) for k in pattern1.keys())

    # Verify nested dicts also have string keys
    assert all(isinstance(k, str) for k in pattern1["evidence"].keys())
    assert all(isinstance(k, str) for k in pattern1["reproduction_context"].keys())


def test_failure_pattern_enum_serialization():
    """Test that enum fields are serialized as string values, not enum objects."""
    pattern = FailurePattern(
        pattern_id="pattern_enum_test",
        source_trace_id="enum_test",
        title="Enum Test",
        failure_type=FailureType.TOXICITY,
        trigger_condition="Test",
        summary="Test",
        root_cause_hypothesis="Test",
        evidence=Evidence(signals=["test"]),
        recommended_actions=["test"],
        reproduction_context=ReproductionContext(
            input_pattern="test",
            tools_involved=[],
        ),
        severity=Severity.CRITICAL,
        confidence=0.9,
        confidence_rationale="Test",
        extracted_at=datetime.now(timezone.utc),
    ).to_dict()

    # Enums must be serialized as their string values
    assert pattern["failure_type"] == "toxicity"
    assert pattern["severity"] == "critical"
    assert isinstance(pattern["failure_type"], str)
    assert isinstance(pattern["severity"], str)


def test_failure_pattern_optional_fields():
    """Test that optional fields are handled correctly in serialization."""
    # Create pattern with minimal required fields (optional fields set to None/empty)
    pattern = FailurePattern(
        pattern_id="pattern_optional_test",
        source_trace_id="optional_test",
        title="Optional Fields Test",
        failure_type=FailureType.CLIENT_ERROR,
        trigger_condition="Test",
        summary="Test",
        root_cause_hypothesis="Test",
        evidence=Evidence(
            signals=["test"],
            excerpt=None,  # Optional field
        ),
        recommended_actions=["test"],
        reproduction_context=ReproductionContext(
            input_pattern="test",
            required_state=None,  # Optional field
            tools_involved=[],
        ),
        severity=Severity.LOW,
        confidence=0.5,
        confidence_rationale="Test",
        extracted_at=datetime.now(timezone.utc),
    ).to_dict()

    # Optional fields with None values should still be in the output
    # (Firestore stores None as null)
    assert "excerpt" in pattern["evidence"]
    assert pattern["evidence"]["excerpt"] is None

    assert "required_state" in pattern["reproduction_context"]
    assert pattern["reproduction_context"]["required_state"] is None


def test_failure_pattern_nested_list_validation():
    """Test that nested lists maintain correct types after serialization."""
    pattern = FailurePattern(
        pattern_id="pattern_list_test",
        source_trace_id="list_test",
        title="List Test",
        failure_type=FailureType.RUNAWAY_LOOP,
        trigger_condition="Test",
        summary="Test",
        root_cause_hypothesis="Test",
        evidence=Evidence(
            signals=["signal1", "signal2", "signal3"],
        ),
        recommended_actions=["action1", "action2"],
        reproduction_context=ReproductionContext(
            input_pattern="test",
            tools_involved=["tool1", "tool2", "tool3"],
        ),
        severity=Severity.HIGH,
        confidence=0.8,
        confidence_rationale="Test",
        extracted_at=datetime.now(timezone.utc),
    ).to_dict()

    # Verify evidence.signals list
    assert isinstance(pattern["evidence"]["signals"], list)
    assert len(pattern["evidence"]["signals"]) == 3
    assert all(isinstance(s, str) for s in pattern["evidence"]["signals"])

    # Verify recommended_actions list
    assert isinstance(pattern["recommended_actions"], list)
    assert len(pattern["recommended_actions"]) == 2
    assert all(isinstance(a, str) for a in pattern["recommended_actions"])

    # Verify reproduction_context.tools_involved list
    assert isinstance(pattern["reproduction_context"]["tools_involved"], list)
    assert len(pattern["reproduction_context"]["tools_involved"]) == 3
    assert all(isinstance(t, str) for t in pattern["reproduction_context"]["tools_involved"])
