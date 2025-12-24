"""Unit tests for FailurePattern schema validation.

Tests validate that the Pydantic models enforce:
- Required fields
- Enum constraints
- Confidence range (0.0 to 1.0)
- Minimum list lengths
- Field types

Covers T025 requirements.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.extraction.models import (
    Evidence,
    FailurePattern,
    FailureType,
    ReproductionContext,
    Severity,
)


def test_failure_pattern_valid():
    """Test that a valid FailurePattern passes validation."""
    pattern = FailurePattern(
        pattern_id="pattern_test_001",
        source_trace_id="test_001",
        title="Test Hallucination Pattern",
        failure_type=FailureType.HALLUCINATION,
        trigger_condition="Factual error in date",
        summary="Model incorrectly stated the Eiffel Tower was built in 1920 instead of 1889.",
        root_cause_hypothesis="Training data contamination or retrieval error.",
        evidence=Evidence(
            signals=["status_code: 200", "latency_ms: 380"],
            excerpt="The Eiffel Tower was built in 1920...",
        ),
        recommended_actions=["Add fact-checking layer", "Update training data"],
        reproduction_context=ReproductionContext(
            input_pattern="Questions about construction dates of landmarks",
            required_state=None,
            tools_involved=[],
        ),
        severity=Severity.HIGH,
        confidence=0.85,
        confidence_rationale="Clear factual error with correct context",
        extracted_at=datetime.now(timezone.utc),
    )

    assert pattern.pattern_id == "pattern_test_001"
    assert pattern.failure_type == FailureType.HALLUCINATION
    assert pattern.confidence == 0.85
    assert len(pattern.evidence.signals) == 2
    assert len(pattern.recommended_actions) == 2


def test_failure_pattern_missing_required_field():
    """Test that missing required fields raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        FailurePattern(
            pattern_id="pattern_test_002",
            # Missing source_trace_id
            title="Test Pattern",
            failure_type=FailureType.TOXICITY,
            trigger_condition="Harmful content",
            summary="Test summary",
            root_cause_hypothesis="Test hypothesis",
            evidence=Evidence(signals=["test"]),
            recommended_actions=["action1"],
            reproduction_context=ReproductionContext(input_pattern="test"),
            severity=Severity.CRITICAL,
            confidence=0.9,
            confidence_rationale="Test",
            extracted_at=datetime.now(timezone.utc),
        )

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("source_trace_id",) for e in errors)


def test_failure_pattern_invalid_failure_type():
    """Test that invalid failure_type raises ValidationError."""
    with pytest.raises(ValidationError):
        FailurePattern(
            pattern_id="pattern_test_003",
            source_trace_id="test_003",
            title="Test Pattern",
            failure_type="invalid_type",  # Not in FailureType enum
            trigger_condition="Test",
            summary="Test summary",
            root_cause_hypothesis="Test",
            evidence=Evidence(signals=["test"]),
            recommended_actions=["action1"],
            reproduction_context=ReproductionContext(input_pattern="test"),
            severity=Severity.HIGH,
            confidence=0.8,
            confidence_rationale="Test",
            extracted_at=datetime.now(timezone.utc),
        )


def test_failure_pattern_invalid_severity():
    """Test that invalid severity raises ValidationError."""
    with pytest.raises(ValidationError):
        FailurePattern(
            pattern_id="pattern_test_004",
            source_trace_id="test_004",
            title="Test Pattern",
            failure_type=FailureType.WRONG_TOOL,
            trigger_condition="Test",
            summary="Test summary",
            root_cause_hypothesis="Test",
            evidence=Evidence(signals=["test"]),
            recommended_actions=["action1"],
            reproduction_context=ReproductionContext(input_pattern="test"),
            severity="super_critical",  # Not in Severity enum
            confidence=0.7,
            confidence_rationale="Test",
            extracted_at=datetime.now(timezone.utc),
        )


def test_failure_pattern_confidence_below_range():
    """Test that confidence < 0.0 raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        FailurePattern(
            pattern_id="pattern_test_005",
            source_trace_id="test_005",
            title="Test Pattern",
            failure_type=FailureType.RUNAWAY_LOOP,
            trigger_condition="Test",
            summary="Test summary",
            root_cause_hypothesis="Test",
            evidence=Evidence(signals=["test"]),
            recommended_actions=["action1"],
            reproduction_context=ReproductionContext(input_pattern="test"),
            severity=Severity.MEDIUM,
            confidence=-0.1,  # Below minimum
            confidence_rationale="Test",
            extracted_at=datetime.now(timezone.utc),
        )

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("confidence",) and "greater than or equal to 0" in str(e) for e in errors)


def test_failure_pattern_confidence_above_range():
    """Test that confidence > 1.0 raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        FailurePattern(
            pattern_id="pattern_test_006",
            source_trace_id="test_006",
            title="Test Pattern",
            failure_type=FailureType.PII_LEAK,
            trigger_condition="Test",
            summary="Test summary",
            root_cause_hypothesis="Test",
            evidence=Evidence(signals=["test"]),
            recommended_actions=["action1"],
            reproduction_context=ReproductionContext(input_pattern="test"),
            severity=Severity.CRITICAL,
            confidence=1.5,  # Above maximum
            confidence_rationale="Test",
            extracted_at=datetime.now(timezone.utc),
        )

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("confidence",) and "less than or equal to 1" in str(e) for e in errors)


def test_failure_pattern_confidence_boundary_values():
    """Test that confidence exactly 0.0 and 1.0 are valid."""
    # Test minimum boundary
    pattern_min = FailurePattern(
        pattern_id="pattern_test_007",
        source_trace_id="test_007",
        title="Test Pattern",
        failure_type=FailureType.STALE_DATA,
        trigger_condition="Test",
        summary="Test summary",
        root_cause_hypothesis="Test",
        evidence=Evidence(signals=["test"]),
        recommended_actions=["action1"],
        reproduction_context=ReproductionContext(input_pattern="test"),
        severity=Severity.LOW,
        confidence=0.0,
        confidence_rationale="Test",
        extracted_at=datetime.now(timezone.utc),
    )
    assert pattern_min.confidence == 0.0

    # Test maximum boundary
    pattern_max = FailurePattern(
        pattern_id="pattern_test_008",
        source_trace_id="test_008",
        title="Test Pattern",
        failure_type=FailureType.INFRASTRUCTURE_ERROR,
        trigger_condition="Test",
        summary="Test summary",
        root_cause_hypothesis="Test",
        evidence=Evidence(signals=["test"]),
        recommended_actions=["action1"],
        reproduction_context=ReproductionContext(input_pattern="test"),
        severity=Severity.CRITICAL,
        confidence=1.0,
        confidence_rationale="Test",
        extracted_at=datetime.now(timezone.utc),
    )
    assert pattern_max.confidence == 1.0


def test_evidence_requires_at_least_one_signal():
    """Test that Evidence requires at least one signal."""
    with pytest.raises(ValidationError) as exc_info:
        Evidence(
            signals=[],  # Empty list violates min_length=1
            excerpt="Test excerpt",
        )

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("signals",) for e in errors)


def test_evidence_valid_with_signals():
    """Test that Evidence with signals is valid."""
    evidence = Evidence(
        signals=["error_code: 429", "latency_ms: 12"],
        excerpt="Rate limit exceeded",
    )
    assert len(evidence.signals) == 2
    assert evidence.excerpt == "Rate limit exceeded"


def test_evidence_excerpt_is_optional():
    """Test that Evidence.excerpt is optional."""
    evidence = Evidence(
        signals=["test_signal"],
        excerpt=None,
    )
    assert evidence.signals == ["test_signal"]
    assert evidence.excerpt is None


def test_recommended_actions_requires_at_least_one():
    """Test that recommended_actions requires at least one action."""
    with pytest.raises(ValidationError) as exc_info:
        FailurePattern(
            pattern_id="pattern_test_009",
            source_trace_id="test_009",
            title="Test Pattern",
            failure_type=FailureType.CLIENT_ERROR,
            trigger_condition="Test",
            summary="Test summary",
            root_cause_hypothesis="Test",
            evidence=Evidence(signals=["test"]),
            recommended_actions=[],  # Empty list violates min_length=1
            reproduction_context=ReproductionContext(input_pattern="test"),
            severity=Severity.LOW,
            confidence=0.5,
            confidence_rationale="Test",
            extracted_at=datetime.now(timezone.utc),
        )

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("recommended_actions",) for e in errors)


def test_reproduction_context_required_fields():
    """Test that ReproductionContext.input_pattern is required."""
    with pytest.raises(ValidationError) as exc_info:
        ReproductionContext(
            # Missing input_pattern (required)
            required_state="Some state",
            tools_involved=["tool1"],
        )

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("input_pattern",) for e in errors)


def test_reproduction_context_optional_fields():
    """Test that ReproductionContext optional fields work correctly."""
    context = ReproductionContext(
        input_pattern="Test input pattern",
        required_state=None,
        tools_involved=[],
    )
    assert context.input_pattern == "Test input pattern"
    assert context.required_state is None
    assert context.tools_involved == []


def test_failure_pattern_to_dict_serialization():
    """Test that FailurePattern.to_dict() produces correct Firestore format."""
    now = datetime(2024, 12, 23, 10, 30, 0, tzinfo=timezone.utc)
    pattern = FailurePattern(
        pattern_id="pattern_test_010",
        source_trace_id="test_010",
        title="Serialization Test",
        failure_type=FailureType.HALLUCINATION,
        trigger_condition="Test trigger",
        summary="Test summary",
        root_cause_hypothesis="Test hypothesis",
        evidence=Evidence(
            signals=["signal1", "signal2"],
            excerpt="Test excerpt",
        ),
        recommended_actions=["action1", "action2"],
        reproduction_context=ReproductionContext(
            input_pattern="test pattern",
            required_state="test state",
            tools_involved=["tool1"],
        ),
        severity=Severity.HIGH,
        confidence=0.75,
        confidence_rationale="Test rationale",
        extracted_at=now,
    )

    result = pattern.to_dict()

    # Verify structure
    assert result["pattern_id"] == "pattern_test_010"
    assert result["source_trace_id"] == "test_010"
    assert result["title"] == "Serialization Test"
    assert result["failure_type"] == "hallucination"  # Enum value as string
    assert result["trigger_condition"] == "Test trigger"
    assert result["summary"] == "Test summary"
    assert result["root_cause_hypothesis"] == "Test hypothesis"

    # Verify nested evidence
    assert result["evidence"]["signals"] == ["signal1", "signal2"]
    assert result["evidence"]["excerpt"] == "Test excerpt"

    # Verify nested reproduction_context
    assert result["reproduction_context"]["input_pattern"] == "test pattern"
    assert result["reproduction_context"]["required_state"] == "test state"
    assert result["reproduction_context"]["tools_involved"] == ["tool1"]

    # Verify other fields
    assert result["recommended_actions"] == ["action1", "action2"]
    assert result["severity"] == "high"  # Enum value as string
    assert result["confidence"] == 0.75
    assert result["confidence_rationale"] == "Test rationale"
    assert result["extracted_at"] == "2024-12-23T10:30:00+00:00"  # ISO format


def test_all_failure_types_are_valid():
    """Test that all FailureType enum values are accepted."""
    failure_types = [
        FailureType.HALLUCINATION,
        FailureType.TOXICITY,
        FailureType.WRONG_TOOL,
        FailureType.RUNAWAY_LOOP,
        FailureType.PII_LEAK,
        FailureType.STALE_DATA,
        FailureType.INFRASTRUCTURE_ERROR,
        FailureType.CLIENT_ERROR,
    ]

    for ft in failure_types:
        pattern = FailurePattern(
            pattern_id=f"pattern_{ft.value}",
            source_trace_id=f"test_{ft.value}",
            title=f"Test {ft.value}",
            failure_type=ft,
            trigger_condition="Test",
            summary="Test",
            root_cause_hypothesis="Test",
            evidence=Evidence(signals=["test"]),
            recommended_actions=["test"],
            reproduction_context=ReproductionContext(input_pattern="test"),
            severity=Severity.MEDIUM,
            confidence=0.5,
            confidence_rationale="Test",
            extracted_at=datetime.now(timezone.utc),
        )
        assert pattern.failure_type == ft


def test_all_severity_levels_are_valid():
    """Test that all Severity enum values are accepted."""
    severities = [
        Severity.LOW,
        Severity.MEDIUM,
        Severity.HIGH,
        Severity.CRITICAL,
    ]

    for sev in severities:
        pattern = FailurePattern(
            pattern_id=f"pattern_{sev.value}",
            source_trace_id=f"test_{sev.value}",
            title=f"Test {sev.value}",
            failure_type=FailureType.HALLUCINATION,
            trigger_condition="Test",
            summary="Test",
            root_cause_hypothesis="Test",
            evidence=Evidence(signals=["test"]),
            recommended_actions=["test"],
            reproduction_context=ReproductionContext(input_pattern="test"),
            severity=sev,
            confidence=0.5,
            confidence_rationale="Test",
            extracted_at=datetime.now(timezone.utc),
        )
        assert pattern.severity == sev
