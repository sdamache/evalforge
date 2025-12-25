"""Live integration test for Gemini extraction.

This test calls the REAL Gemini API to verify:
- Successful authentication and API connectivity
- Valid JSON response with structured failure pattern
- Schema compliance of extracted patterns
- Reasonable extraction quality (confidence > 0.5)

Run with: RUN_LIVE_TESTS=1 PYTHONPATH=src pytest tests/integration/test_extraction_live_gemini.py -v

Requires:
- Valid GCP credentials (GOOGLE_APPLICATION_CREDENTIALS or ADC)
- GOOGLE_CLOUD_PROJECT environment variable
- Vertex AI API enabled
- RUN_LIVE_TESTS=1 environment variable
"""

import json
import os
from datetime import datetime, timezone

import pytest

from src.extraction.gemini_client import GeminiClient
from src.extraction.models import FailurePattern, FailureType, Severity
from src.extraction.prompt_templates import build_extraction_prompt

# Skip this test unless explicitly enabled
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="Live Gemini tests require RUN_LIVE_TESTS=1 environment variable"
)


@pytest.fixture
def gemini_client():
    """Create a real Gemini client using environment credentials."""
    # Requires GOOGLE_CLOUD_PROJECT and credentials
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        pytest.skip("GOOGLE_CLOUD_PROJECT environment variable not set")

    location = os.getenv("VERTEX_AI_LOCATION", "us-central1")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    return GeminiClient(
        project_id=project_id,
        location=location,
        model_name=model,
        temperature=0.2,
        max_output_tokens=4096,
    )


@pytest.fixture
def sample_hallucination_span():
    """Sample failure span for testing extraction."""
    return {
        "trace_id": "test_live_hallucination_001",
        "failure_type": "llm_error",  # Ingestion's initial classification
        "severity": "high",
        "service_name": "chat-assistant",
        "trace_payload": {
            "model": "gpt-4",
            "prompt": "What year was the Eiffel Tower built?",
            "response": "The Eiffel Tower was built in 1920 for the World's Fair in Paris.",
            "actual_answer": "1889",
            "latency_ms": 380,
            "tokens_used": 45,
            "status_code": 200,
        },
    }


def test_live_gemini_extraction_returns_valid_json(gemini_client, sample_hallucination_span):
    """Test that live Gemini API returns valid JSON matching our schema."""
    # Build prompt
    prompt = build_extraction_prompt(sample_hallucination_span)

    # Call real Gemini API
    response_text = gemini_client.extract_failure_pattern(prompt)

    # Verify response is valid JSON
    parsed = json.loads(response_text)
    assert isinstance(parsed, dict), "Gemini response should be a JSON object"

    # Verify top-level fields exist
    assert "title" in parsed, "Response should have 'title' field"
    assert "failure_type" in parsed, "Response should have 'failure_type' field"
    assert "trigger_condition" in parsed, "Response should have 'trigger_condition' field"
    assert "summary" in parsed, "Response should have 'summary' field"
    assert "root_cause_hypothesis" in parsed, "Response should have 'root_cause_hypothesis' field"
    assert "evidence" in parsed, "Response should have 'evidence' field"
    assert "recommended_actions" in parsed, "Response should have 'recommended_actions' field"
    assert "reproduction_context" in parsed, "Response should have 'reproduction_context' field"
    assert "severity" in parsed, "Response should have 'severity' field"
    assert "confidence" in parsed, "Response should have 'confidence' field"
    assert "confidence_rationale" in parsed, "Response should have 'confidence_rationale' field"


def test_live_gemini_extraction_validates_against_schema(gemini_client, sample_hallucination_span):
    """Test that Gemini output validates against FailurePattern Pydantic schema."""
    # Build prompt
    prompt = build_extraction_prompt(sample_hallucination_span)

    # Call real Gemini API
    response_text = gemini_client.extract_failure_pattern(prompt)
    parsed = json.loads(response_text)

    # Add required fields for FailurePattern model
    parsed["pattern_id"] = f"pattern_live_test_{datetime.now(timezone.utc).timestamp()}"
    parsed["source_trace_id"] = sample_hallucination_span["trace_id"]
    parsed["extracted_at"] = datetime.now(timezone.utc)

    # Validate against Pydantic schema
    pattern = FailurePattern(**parsed)

    # Verify basic constraints
    assert pattern.confidence >= 0.0, "Confidence should be >= 0.0"
    assert pattern.confidence <= 1.0, "Confidence should be <= 1.0"
    assert pattern.failure_type in FailureType, "failure_type should be valid enum"
    assert pattern.severity in Severity, "severity should be valid enum"
    assert len(pattern.evidence.signals) >= 1, "evidence.signals should have at least 1 item"
    assert len(pattern.recommended_actions) >= 1, "recommended_actions should have at least 1 item"


def test_live_gemini_extraction_quality_hallucination_case(gemini_client, sample_hallucination_span):
    """Test extraction quality for hallucination case (should identify factual error)."""
    # Build prompt
    prompt = build_extraction_prompt(sample_hallucination_span)

    # Call real Gemini API
    response_text = gemini_client.extract_failure_pattern(prompt)
    parsed = json.loads(response_text)

    # Verify failure_type is correctly identified
    # Expected: "hallucination" (not the ingestion's initial "llm_error")
    assert parsed["failure_type"] == "hallucination", \
        f"Expected 'hallucination', got '{parsed['failure_type']}'"

    # Verify trigger_condition mentions the factual error
    trigger = parsed["trigger_condition"].lower()
    assert any(keyword in trigger for keyword in ["date", "year", "factual", "incorrect", "wrong"]), \
        f"trigger_condition should mention factual error, got: {parsed['trigger_condition']}"

    # Verify reasonable confidence (should be high for clear hallucination)
    assert parsed["confidence"] >= 0.6, \
        f"Expected confidence >= 0.6 for clear hallucination, got {parsed['confidence']}"


def test_live_gemini_extraction_retry_mechanism(gemini_client):
    """Test that retry mechanism works for transient failures."""
    # This test verifies the retry logic exists but doesn't force failures
    # (forcing failures would require mocking, which defeats live test purpose)

    # Just verify client has retry config
    assert gemini_client.max_retries > 0, "Client should have retry mechanism configured"

    # Simple smoke test: call with minimal payload
    minimal_span = {
        "trace_id": "test_retry_001",
        "failure_type": "llm_error",
        "trace_payload": {
            "model": "test",
            "prompt": "test",
            "response": "test error",
        },
    }

    prompt = build_extraction_prompt(minimal_span)
    response = gemini_client.extract_failure_pattern(prompt)

    # Just verify we got a response (retries handled internally)
    assert response, "Should receive response even with minimal input"
    assert isinstance(response, str), "Response should be string"


def test_live_gemini_extraction_pii_redaction_preserved(gemini_client):
    """Test that PII redaction markers in input are preserved in evidence excerpts."""
    span_with_pii_markers = {
        "trace_id": "test_pii_redaction_001",
        "failure_type": "pii_leak",
        "severity": "critical",
        "trace_payload": {
            "model": "gpt-4",
            "prompt": "User [EMAIL_REDACTED] requested account deletion.",
            "response": "I'll delete the account for [EMAIL_REDACTED] right away.",
            "status_code": 200,
        },
    }

    prompt = build_extraction_prompt(span_with_pii_markers)
    response_text = gemini_client.extract_failure_pattern(prompt)
    parsed = json.loads(response_text)

    # Verify evidence excerpt doesn't contain raw PII
    # (Input already had [EMAIL_REDACTED], output should preserve or further redact)
    if "excerpt" in parsed["evidence"] and parsed["evidence"]["excerpt"]:
        excerpt = parsed["evidence"]["excerpt"]
        # Verify no email patterns leaked
        assert "@" not in excerpt or "[EMAIL_REDACTED]" in excerpt, \
            "Evidence excerpt should not contain unredacted email addresses"


def test_live_gemini_api_connectivity(gemini_client):
    """Smoke test to verify Gemini API is accessible with current credentials."""
    # Minimal test to catch auth/connectivity issues early
    simple_span = {
        "trace_id": "test_connectivity_001",
        "failure_type": "llm_error",
        "trace_payload": {
            "model": "test-model",
            "prompt": "Test prompt",
            "response": "Test response with error",
            "error": "Rate limit exceeded",
        },
    }

    prompt = build_extraction_prompt(simple_span)

    # This will raise if there are auth/connectivity issues
    response = gemini_client.extract_failure_pattern(prompt)

    assert response, "Should receive response from Gemini API"
    assert len(response) > 0, "Response should not be empty"

    # Verify it's valid JSON
    parsed = json.loads(response)
    assert isinstance(parsed, dict), "Response should be JSON object"
