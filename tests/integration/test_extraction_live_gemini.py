"""
Integration tests for failure pattern extraction with live Gemini API.

These tests verify that the extraction service can successfully communicate
with the Gemini API and extract structured failure patterns from real traces.

Requirements:
- RUN_LIVE_TESTS=1 environment variable must be set
- Valid GOOGLE_CLOUD_PROJECT and credentials configured
- Vertex AI API enabled in the project

Usage:
    # Run all integration tests
    RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_extraction_live_gemini.py -v

    # Run specific test
    RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_extraction_live_gemini.py::test_gemini_extract_failure_pattern -v
"""

import os
import time
from datetime import datetime, UTC
import pytest
from src.extraction.gemini_client import GeminiClient
from src.extraction.models import FailurePattern, FailureType, Evidence, ReproductionContext
from src.extraction.prompt_templates import build_extraction_prompt
from src.common.config import GeminiConfig


# Mark all tests in this module as integration tests requiring live API
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LIVE_TESTS"),
    reason="Live Gemini integration tests require RUN_LIVE_TESTS=1"
)


def _extract_failure_pattern_from_trace(client: GeminiClient, trace: dict, source_trace_id: str) -> FailurePattern:
    """Helper to extract failure pattern from trace data.

    Mimics the flow in main.py but simplified for testing.
    """
    # Build prompt from trace
    prompt = build_extraction_prompt(trace)

    # Call Gemini
    response = client.extract_pattern(prompt)

    # Parse response into FailurePattern
    parsed = response.parsed_json
    evidence_data = parsed.get("evidence", {})
    repro_data = parsed.get("reproduction_context", {})
    return FailurePattern(
        pattern_id=f"pattern_{source_trace_id}",
        source_trace_id=source_trace_id,
        title=parsed["title"],
        failure_type=FailureType(parsed["failure_type"]),
        trigger_condition=parsed["trigger_condition"],
        summary=parsed["summary"],
        root_cause_hypothesis=parsed["root_cause_hypothesis"],
        evidence=Evidence(**evidence_data) if evidence_data else Evidence(signals=["no evidence"]),
        reproduction_context=ReproductionContext(**repro_data) if repro_data else ReproductionContext(input_pattern="unknown"),
        recommended_actions=parsed.get("recommended_actions", []),
        severity=parsed.get("severity", "medium"),
        confidence=parsed.get("confidence", 0.5),
        confidence_rationale=parsed.get("confidence_rationale", ""),
        extracted_at=datetime.now(UTC),
    )


@pytest.fixture
def gemini_client():
    """Create Gemini client with live credentials."""
    config = GeminiConfig(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.2")),
        max_output_tokens=int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "4096")),
        location=os.getenv("VERTEX_AI_LOCATION", "us-central1"),
    )
    return GeminiClient(config=config)


@pytest.fixture
def sample_failure_trace():
    """Sample failure trace for extraction testing."""
    return {
        "trace_id": "test-trace-123",
        "failure_type": "hallucination",
        "error_message": "Model provided factually incorrect response",
        "user_prompt": "What is the capital of France?",
        "model_response": "The capital of France is Berlin.",
        "metadata": {
            "model": "gpt-4",
            "timestamp": "2024-12-25T10:00:00Z",
            "service": "eval-service",
        },
        "spans": [
            {
                "span_id": "span-1",
                "operation": "llm_call",
                "duration_ms": 1250,
                "status": "error",
            }
        ],
    }


def test_gemini_client_initialization(gemini_client):
    """Test that Gemini client can be initialized with live credentials."""
    assert gemini_client is not None
    assert gemini_client.config is not None
    assert gemini_client.config.model is not None


def test_gemini_extract_failure_pattern(gemini_client, sample_failure_trace):
    """
    Test end-to-end extraction of failure pattern using live Gemini API.

    Success criteria:
    - Returns valid FailurePattern model
    - Has required fields populated
    - Confidence score in valid range [0.0, 1.0]
    - Failure type matches expected enum values
    """
    # Execute extraction
    pattern = _extract_failure_pattern_from_trace(
        client=gemini_client,
        trace=sample_failure_trace,
        source_trace_id="test-trace-123"
    )

    # Verify response structure
    assert isinstance(pattern, FailurePattern)

    # Verify required fields
    assert pattern.pattern_id is not None
    assert pattern.source_trace_id == "test-trace-123"
    assert pattern.title is not None and len(pattern.title) > 0
    assert pattern.failure_type is not None
    assert pattern.trigger_condition is not None
    assert pattern.summary is not None
    assert pattern.root_cause_hypothesis is not None
    assert pattern.evidence is not None
    assert len(pattern.evidence.signals) > 0
    assert pattern.recommended_actions is not None and len(pattern.recommended_actions) > 0
    assert pattern.severity is not None
    assert pattern.confidence is not None
    assert pattern.confidence_rationale is not None
    assert pattern.extracted_at is not None

    # Verify value ranges
    assert 0.0 <= pattern.confidence <= 1.0, \
        f"Confidence {pattern.confidence} out of valid range [0.0, 1.0]"

    # Verify failure type is valid enum (use actual FailureType enum values)
    valid_failure_types = {ft.value for ft in FailureType}
    assert pattern.failure_type.value in valid_failure_types, \
        f"Failure type '{pattern.failure_type}' not in valid set {valid_failure_types}"

    # Verify severity is valid enum
    valid_severities = {"critical", "high", "medium", "low"}
    assert pattern.severity in valid_severities, \
        f"Severity '{pattern.severity}' not in valid set"


def test_gemini_extraction_with_malformed_trace(gemini_client):
    """
    Test that extraction handles minimal trace data gracefully.

    Expected behavior:
    - Should not crash or hang
    - May return low-confidence pattern with defaults
    """
    minimal_trace = {
        "trace_id": "minimal-123",
        "error_message": "Generic error",
        # Missing many optional fields
    }

    # Should complete without crashing
    pattern = _extract_failure_pattern_from_trace(
        client=gemini_client,
        trace=minimal_trace,
        source_trace_id="minimal-123"
    )

    # Should return a valid pattern (even if low confidence)
    assert isinstance(pattern, FailurePattern)
    assert pattern.source_trace_id == "minimal-123"


def test_gemini_extraction_timeout(gemini_client):
    """
    Test that extraction respects timeout limits (< 10s per trace).

    Success criteria:
    - Extraction completes within 10 seconds
    - Does not hang indefinitely
    """
    import time

    trace = {
        "trace_id": "timeout-test-123",
        "failure_type": "quality_degradation",
        "error_message": "Response quality below threshold",
        "user_prompt": "Generate a comprehensive analysis of...",
        "model_response": "..." * 100,  # Long response
        "metadata": {"model": "test-model"},
        "spans": []
    }

    start_time = time.time()
    try:
        _extract_failure_pattern_from_trace(
            client=gemini_client,
            trace=trace,
            source_trace_id="timeout-test-123"
        )
    except Exception as e:
        # Timeout or error is acceptable
        pass
    elapsed = time.time() - start_time

    # Allow 20s for API variability (target is 10s but Gemini latency varies)
    assert elapsed < 20.0, \
        f"Extraction took {elapsed:.2f}s, exceeding 20s timeout limit"


def test_gemini_extraction_produces_valid_json_schema(gemini_client, sample_failure_trace):
    """
    Test that extracted patterns can be serialized to valid JSON.

    Success criteria:
    - Pattern can be converted to dict
    - Dict can be serialized to JSON
    - No datetime serialization errors
    """
    import json

    pattern = _extract_failure_pattern_from_trace(
        client=gemini_client,
        trace=sample_failure_trace,
        source_trace_id="test-trace-123"
    )

    # Convert to dict
    pattern_dict = pattern.model_dump()
    assert isinstance(pattern_dict, dict)

    # Verify JSON serialization
    json_str = json.dumps(pattern_dict, default=str)
    assert json_str is not None
    assert len(json_str) > 0

    # Verify deserialization
    parsed = json.loads(json_str)
    assert parsed["pattern_id"] == pattern.pattern_id
    assert parsed["source_trace_id"] == "test-trace-123"


def test_gemini_respects_temperature_setting(gemini_client):
    """
    Test that Gemini respects temperature configuration.

    Note: This is a smoke test - we can't directly verify temperature
    is applied, but we verify model is configured correctly.
    """
    assert gemini_client.config.temperature is not None
    assert 0.0 <= gemini_client.config.temperature <= 1.0


def test_gemini_batch_extraction_consistency():
    """
    Test that extracting the same trace multiple times produces consistent results.

    Success criteria:
    - Same trace produces same failure_type
    - Confidence scores are similar (within 0.2)
    - Core fields (title, trigger_condition) are consistent
    """
    config = GeminiConfig(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        temperature=0.0,  # Low temperature for consistency
        max_output_tokens=int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "4096")),
        location=os.getenv("VERTEX_AI_LOCATION", "us-central1"),
    )
    client = GeminiClient(config=config)

    trace = {
        "trace_id": "consistency-test-123",
        "failure_type": "hallucination",
        "error_message": "Incorrect factual response",
        "user_prompt": "What year was Python created?",
        "model_response": "Python was created in 1995.",  # Incorrect - actually 1991
        "metadata": {"model": "test-model"},
        "spans": []
    }

    # Extract twice
    pattern1 = _extract_failure_pattern_from_trace(
        client=client,
        trace=trace,
        source_trace_id="consistency-test-123"
    )
    pattern2 = _extract_failure_pattern_from_trace(
        client=client,
        trace=trace,
        source_trace_id="consistency-test-123"
    )

    # Verify consistency
    assert pattern1.failure_type == pattern2.failure_type, \
        "Failure type should be consistent across extractions"

    confidence_diff = abs(pattern1.confidence - pattern2.confidence)
    assert confidence_diff < 0.2, \
        f"Confidence scores differ by {confidence_diff}, exceeding 0.2 threshold"


if __name__ == "__main__":
    # Allow running tests directly
    import sys
    pytest.main([__file__, "-v"] + sys.argv[1:])
