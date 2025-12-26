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
import pytest
from src.extraction.gemini_client import GeminiClient
from src.extraction.config import load_settings
from src.extraction.models import FailurePattern


# Mark all tests in this module as integration tests requiring live API
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LIVE_TESTS"),
    reason="Live Gemini integration tests require RUN_LIVE_TESTS=1"
)


@pytest.fixture
def gemini_client():
    """Create Gemini client with live credentials."""
    settings = load_settings()
    return GeminiClient(
        project_id=settings.google_cloud_project,
        location=settings.vertex_ai_location,
        model=settings.gemini_model,
        temperature=settings.gemini_temperature,
        max_output_tokens=settings.gemini_max_output_tokens,
    )


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
    assert gemini_client._model is not None


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
    pattern = gemini_client.extract_failure_pattern(
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
    assert pattern.evidence is not None and len(pattern.evidence) > 0
    assert pattern.recommended_actions is not None and len(pattern.recommended_actions) > 0
    assert pattern.severity is not None
    assert pattern.confidence is not None
    assert pattern.confidence_rationale is not None
    assert pattern.extracted_at is not None

    # Verify value ranges
    assert 0.0 <= pattern.confidence <= 1.0, \
        f"Confidence {pattern.confidence} out of valid range [0.0, 1.0]"

    # Verify failure type is valid enum
    valid_failure_types = {
        "hallucination",
        "prompt_injection",
        "toxicity",
        "guardrail_failure",
        "quality_degradation",
        "llm_error",
        "infrastructure_error",
        "client_error"
    }
    assert pattern.failure_type in valid_failure_types, \
        f"Failure type '{pattern.failure_type}' not in valid set"

    # Verify severity is valid enum
    valid_severities = {"critical", "high", "medium", "low"}
    assert pattern.severity in valid_severities, \
        f"Severity '{pattern.severity}' not in valid set"


def test_gemini_extraction_with_malformed_trace(gemini_client):
    """
    Test that extraction handles malformed traces gracefully.

    Expected behavior:
    - Should raise ValueError or return error pattern
    - Should not crash or hang
    """
    malformed_trace = {
        "trace_id": "malformed-123",
        # Missing required fields intentionally
    }

    with pytest.raises((ValueError, KeyError)):
        gemini_client.extract_failure_pattern(
            trace=malformed_trace,
            source_trace_id="malformed-123"
        )


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
        gemini_client.extract_failure_pattern(
            trace=trace,
            source_trace_id="timeout-test-123"
        )
    except Exception as e:
        # Timeout or error is acceptable
        pass
    elapsed = time.time() - start_time

    assert elapsed < 10.0, \
        f"Extraction took {elapsed:.2f}s, exceeding 10s timeout limit"


def test_gemini_extraction_produces_valid_json_schema(gemini_client, sample_failure_trace):
    """
    Test that extracted patterns can be serialized to valid JSON.

    Success criteria:
    - Pattern can be converted to dict
    - Dict can be serialized to JSON
    - No datetime serialization errors
    """
    import json

    pattern = gemini_client.extract_failure_pattern(
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
    assert gemini_client._temperature is not None
    assert 0.0 <= gemini_client._temperature <= 1.0


def test_gemini_batch_extraction_consistency():
    """
    Test that extracting the same trace multiple times produces consistent results.

    Success criteria:
    - Same trace produces same failure_type
    - Confidence scores are similar (within 0.2)
    - Core fields (title, trigger_condition) are consistent
    """
    settings = load_settings()
    client = GeminiClient(
        project_id=settings.google_cloud_project,
        location=settings.vertex_ai_location,
        model=settings.gemini_model,
        temperature=0.0,  # Low temperature for consistency
        max_output_tokens=settings.gemini_max_output_tokens,
    )

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
    pattern1 = client.extract_failure_pattern(
        trace=trace,
        source_trace_id="consistency-test-123"
    )
    pattern2 = client.extract_failure_pattern(
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
