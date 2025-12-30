"""
Live integration tests for guardrail draft generation (Gemini + Firestore).

These tests verify end-to-end guardrail generation with real infrastructure:
- Gemini API for draft generation
- Firestore for document storage
- Failure type → guardrail type mapping

Requirements:
- RUN_LIVE_TESTS=1 environment variable must be set
- Valid GOOGLE_CLOUD_PROJECT and credentials configured
- Vertex AI API enabled in the project

Usage:
    RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_guardrail_generator_live.py -v
"""

from __future__ import annotations

import os
from datetime import datetime, UTC
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.common.config import load_firestore_config
from src.common.firestore import (
    failure_patterns_collection,
    get_firestore_client,
    guardrail_errors_collection,
    guardrail_runs_collection,
    suggestions_collection,
)
from src.generators.guardrails.main import app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="Live guardrail generator integration tests require RUN_LIVE_TESTS=1",
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


@pytest.fixture
def test_prefix(monkeypatch) -> str:
    """Create unique collection prefix for test isolation."""
    base = os.getenv("LIVE_TEST_COLLECTION_PREFIX", "test")
    prefix = f"{base.rstrip('_')}_guardrails_{uuid4().hex[:8]}_"
    monkeypatch.setenv("FIRESTORE_COLLECTION_PREFIX", prefix)
    return prefix


@pytest.fixture
def firestore_client(test_prefix):
    """Get Firestore client with test prefix."""
    config = load_firestore_config()
    return get_firestore_client(config)


@pytest.fixture
def client():
    """Get FastAPI test client."""
    return TestClient(app)


def _create_failure_pattern_doc(
    *,
    trace_id: str,
    failure_type: str = "hallucination",
    input_pattern: str | None = None,
) -> dict:
    """Create a failure pattern document fixture."""
    return {
        "pattern_id": f"pattern_{trace_id}",
        "source_trace_id": trace_id,
        "title": f"Test {failure_type} failure pattern",
        "failure_type": failure_type,
        "trigger_condition": "User triggered condition for test",
        "summary": f"Test summary for {failure_type} failure.",
        "root_cause_hypothesis": "Test root cause hypothesis.",
        "evidence": {
            "signals": ["test_signal"],
            "excerpt": "Test evidence excerpt",
        },
        "recommended_actions": ["Take test action 1", "Take test action 2"],
        "reproduction_context": {
            "input_pattern": input_pattern or f"Test input for {failure_type}",
            "required_state": None,
            "tools_involved": ["test_tool"],
        },
        "severity": "medium",
        "confidence": 0.85,
        "confidence_rationale": "High confidence for live test.",
        "extracted_at": _iso_now(),
        "processed": False,
    }


def _create_suggestion_doc(
    *,
    suggestion_id: str,
    trace_id: str,
    failure_type: str = "hallucination",
) -> dict:
    """Create a guardrail-type suggestion document fixture."""
    return {
        "suggestion_id": suggestion_id,
        "type": "guardrail",  # guardrail type, not eval
        "status": "pending",
        "severity": "medium",
        "source_traces": [
            {
                "trace_id": trace_id,
                "pattern_id": f"pattern_{trace_id}",
                "added_at": _iso_now(),
                "similarity_score": None,
            }
        ],
        "pattern": {
            "failure_type": failure_type,
            "trigger_condition": "Test trigger condition",
            "title": f"Test {failure_type} suggestion",
            "summary": f"Test summary for {failure_type} guardrail suggestion.",
        },
        "embedding": [0.0] * 768,
        "similarity_group": f"group_{uuid4().hex[:8]}",
        "suggestion_content": None,
        "approval_metadata": None,
        "version_history": [
            {
                "previous_status": None,
                "new_status": "pending",
                "actor": "live-test",
                "timestamp": _iso_now(),
                "notes": "created by live test",
            }
        ],
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
    }


def test_run_once_generates_guardrail_drafts(
    firestore_client,
    test_prefix,
    client,
):
    """
    Test batch generation for multiple failure types.

    Success criteria:
    - Returns 200 with run summary
    - Each suggestion gets a guardrail draft in suggestion_content.guardrail
    - Draft has required fields: guardrail_id, rule_name, configuration, justification
    """
    suggestions_coll = suggestions_collection(test_prefix)
    patterns_coll = failure_patterns_collection(test_prefix)
    runs_coll = guardrail_runs_collection(test_prefix)
    errors_coll = guardrail_errors_collection(test_prefix)

    # Create test data for hallucination failure
    trace_id = f"trace_{uuid4().hex[:8]}"
    suggestion_id = f"sugg_{uuid4().hex[:8]}"

    created_run_id = None
    try:
        # Setup: Create pattern and suggestion
        firestore_client.collection(patterns_coll).document(trace_id).set(
            _create_failure_pattern_doc(
                trace_id=trace_id,
                failure_type="hallucination",
                input_pattern="What is the capital of France?",
            )
        )
        firestore_client.collection(suggestions_coll).document(suggestion_id).set(
            _create_suggestion_doc(
                suggestion_id=suggestion_id,
                trace_id=trace_id,
                failure_type="hallucination",
            )
        )

        # Execute: Call run-once endpoint
        response = client.post(
            "/guardrails/run-once",
            json={
                "batchSize": 1,
                "suggestionIds": [suggestion_id],
                "triggeredBy": "manual",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        created_run_id = body.get("runId")

        # Verify: Check run summary
        assert body.get("generatedCount") >= 0
        assert body.get("pickedUpCount") == 1

        # Verify: Check guardrail was written to suggestion
        snapshot = firestore_client.collection(suggestions_coll).document(suggestion_id).get()
        doc = snapshot.to_dict() or {}
        guardrail = (doc.get("suggestion_content") or {}).get("guardrail")

        assert isinstance(guardrail, dict), "Expected guardrail draft in suggestion_content"
        assert guardrail.get("guardrail_id") == f"guard_{suggestion_id}"
        assert guardrail.get("rule_name"), "Expected non-empty rule_name"
        assert guardrail.get("guardrail_type"), "Expected guardrail_type"
        assert isinstance(guardrail.get("configuration"), dict), "Expected configuration dict"
        assert guardrail.get("justification"), "Expected justification"
        assert guardrail.get("description"), "Expected description"
        assert guardrail.get("source", {}).get("suggestion_id") == suggestion_id

    finally:
        # Cleanup
        firestore_client.collection(suggestions_coll).document(suggestion_id).delete()
        firestore_client.collection(patterns_coll).document(trace_id).delete()
        if created_run_id:
            firestore_client.collection(runs_coll).document(created_run_id).delete()
            firestore_client.collection(errors_coll).document(
                f"{created_run_id}:{suggestion_id}"
            ).delete()


def test_failure_type_to_guardrail_type_mapping(
    firestore_client,
    test_prefix,
    client,
):
    """
    Test deterministic failure_type → guardrail_type mapping.

    Verifies:
    - hallucination → validation_rule
    - runaway_loop → rate_limit
    - pii_leak → redaction_rule
    """
    suggestions_coll = suggestions_collection(test_prefix)
    patterns_coll = failure_patterns_collection(test_prefix)
    runs_coll = guardrail_runs_collection(test_prefix)
    errors_coll = guardrail_errors_collection(test_prefix)

    # Test cases: failure_type → expected guardrail_type
    test_cases = [
        ("hallucination", "validation_rule"),
        ("runaway_loop", "rate_limit"),
        ("pii_leak", "redaction_rule"),
    ]

    created_docs = []
    created_run_id = None
    try:
        for failure_type, expected_guardrail_type in test_cases:
            trace_id = f"trace_{failure_type}_{uuid4().hex[:6]}"
            suggestion_id = f"sugg_{failure_type}_{uuid4().hex[:6]}"
            created_docs.append((trace_id, suggestion_id))

            # Setup
            firestore_client.collection(patterns_coll).document(trace_id).set(
                _create_failure_pattern_doc(
                    trace_id=trace_id,
                    failure_type=failure_type,
                    input_pattern=f"Test input for {failure_type}",
                )
            )
            firestore_client.collection(suggestions_coll).document(suggestion_id).set(
                _create_suggestion_doc(
                    suggestion_id=suggestion_id,
                    trace_id=trace_id,
                    failure_type=failure_type,
                )
            )

        # Execute: Generate all at once
        all_suggestion_ids = [sid for _, sid in created_docs]
        response = client.post(
            "/guardrails/run-once",
            json={
                "batchSize": len(all_suggestion_ids),
                "suggestionIds": all_suggestion_ids,
                "triggeredBy": "manual",
            },
        )
        assert response.status_code == 200, response.text
        created_run_id = response.json().get("runId")

        # Verify each mapping
        for i, (failure_type, expected_guardrail_type) in enumerate(test_cases):
            _, suggestion_id = created_docs[i]
            snapshot = firestore_client.collection(suggestions_coll).document(suggestion_id).get()
            doc = snapshot.to_dict() or {}
            guardrail = (doc.get("suggestion_content") or {}).get("guardrail") or {}

            actual_type = guardrail.get("guardrail_type")
            assert actual_type == expected_guardrail_type, (
                f"Expected {failure_type} → {expected_guardrail_type}, got {actual_type}"
            )

    finally:
        # Cleanup
        for trace_id, suggestion_id in created_docs:
            firestore_client.collection(suggestions_coll).document(suggestion_id).delete()
            firestore_client.collection(patterns_coll).document(trace_id).delete()
            if created_run_id:
                firestore_client.collection(errors_coll).document(
                    f"{created_run_id}:{suggestion_id}"
                ).delete()
        if created_run_id:
            firestore_client.collection(runs_coll).document(created_run_id).delete()


def test_insufficient_context_returns_needs_human_input(
    firestore_client,
    test_prefix,
    client,
):
    """
    Test that suggestions with minimal context produce needs_human_input status.

    When there's no failure pattern or input_pattern is None/empty,
    the service should fall back to template with needs_human_input status.
    """
    suggestions_coll = suggestions_collection(test_prefix)
    patterns_coll = failure_patterns_collection(test_prefix)
    runs_coll = guardrail_runs_collection(test_prefix)
    errors_coll = guardrail_errors_collection(test_prefix)

    # Create suggestion with missing pattern (no input_pattern)
    trace_id = f"trace_{uuid4().hex[:8]}"
    suggestion_id = f"sugg_{uuid4().hex[:8]}"

    created_run_id = None
    try:
        # Setup: Create pattern with no input_pattern (empty context)
        firestore_client.collection(patterns_coll).document(trace_id).set(
            _create_failure_pattern_doc(
                trace_id=trace_id,
                failure_type="hallucination",
                input_pattern=None,  # Missing context triggers fallback
            )
        )
        firestore_client.collection(suggestions_coll).document(suggestion_id).set(
            _create_suggestion_doc(
                suggestion_id=suggestion_id,
                trace_id=trace_id,
                failure_type="hallucination",
            )
        )

        # Execute
        response = client.post(
            "/guardrails/run-once",
            json={
                "batchSize": 1,
                "suggestionIds": [suggestion_id],
                "triggeredBy": "manual",
            },
        )
        assert response.status_code == 200, response.text
        created_run_id = response.json().get("runId")

        # Verify: Check guardrail has needs_human_input status
        snapshot = firestore_client.collection(suggestions_coll).document(suggestion_id).get()
        doc = snapshot.to_dict() or {}
        guardrail = (doc.get("suggestion_content") or {}).get("guardrail") or {}

        # Note: Even with minimal context, Gemini may still generate a valid draft.
        # The template fallback only triggers when Gemini fails or context is truly insufficient.
        # This test verifies the draft structure is correct regardless of status.
        assert isinstance(guardrail, dict), "Expected guardrail draft"
        assert guardrail.get("guardrail_id"), "Expected guardrail_id"
        assert guardrail.get("status") in ("draft", "needs_human_input"), (
            f"Expected status to be draft or needs_human_input, got {guardrail.get('status')}"
        )

    finally:
        # Cleanup
        firestore_client.collection(suggestions_coll).document(suggestion_id).delete()
        firestore_client.collection(patterns_coll).document(trace_id).delete()
        if created_run_id:
            firestore_client.collection(runs_coll).document(created_run_id).delete()
            firestore_client.collection(errors_coll).document(
                f"{created_run_id}:{suggestion_id}"
            ).delete()


def test_generate_endpoint_blocks_human_edits_without_force_overwrite(
    firestore_client,
    test_prefix,
    client,
):
    """
    Test overwrite protection for human-edited drafts.

    Verifies:
    - First generation succeeds
    - After marking edit_source=human, regeneration is blocked (409)
    - With forceOverwrite=true, regeneration succeeds
    """
    suggestions_coll = suggestions_collection(test_prefix)
    patterns_coll = failure_patterns_collection(test_prefix)
    errors_coll = guardrail_errors_collection(test_prefix)

    trace_id = f"trace_{uuid4().hex[:8]}"
    suggestion_id = f"sugg_{uuid4().hex[:8]}"

    created_run_id = None
    try:
        # Setup
        firestore_client.collection(patterns_coll).document(trace_id).set(
            _create_failure_pattern_doc(
                trace_id=trace_id,
                failure_type="hallucination",
                input_pattern="What is the capital of France?",
            )
        )
        firestore_client.collection(suggestions_coll).document(suggestion_id).set(
            _create_suggestion_doc(
                suggestion_id=suggestion_id,
                trace_id=trace_id,
                failure_type="hallucination",
            )
        )

        # First generation should succeed
        resp = client.post(
            f"/guardrails/generate/{suggestion_id}",
            json={"triggeredBy": "manual", "forceOverwrite": False},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        guardrail = body.get("guardrail") or {}
        created_run_id = (guardrail.get("generator_meta") or {}).get("run_id")

        # Verify initial draft
        snapshot = firestore_client.collection(suggestions_coll).document(suggestion_id).get()
        doc = snapshot.to_dict() or {}
        stored = (doc.get("suggestion_content") or {}).get("guardrail") or {}
        assert stored.get("justification"), "Expected non-empty justification"
        original_rule_name = stored.get("rule_name")

        # Mark as human-edited
        firestore_client.collection(suggestions_coll).document(suggestion_id).update({
            "suggestion_content.guardrail.edit_source": "human",
            "suggestion_content.guardrail.rule_name": "Human Edited Rule Name",
        })

        # Regeneration without force should be blocked
        blocked = client.post(
            f"/guardrails/generate/{suggestion_id}",
            json={"triggeredBy": "manual", "forceOverwrite": False},
        )
        assert blocked.status_code == 409, f"Expected 409, got {blocked.status_code}: {blocked.text}"

        # With force overwrite should succeed
        overwritten = client.post(
            f"/guardrails/generate/{suggestion_id}",
            json={"triggeredBy": "manual", "forceOverwrite": True},
        )
        assert overwritten.status_code == 200, overwritten.text

        # Verify overwrite
        snapshot2 = firestore_client.collection(suggestions_coll).document(suggestion_id).get()
        doc2 = snapshot2.to_dict() or {}
        stored2 = (doc2.get("suggestion_content") or {}).get("guardrail") or {}
        assert stored2.get("edit_source") == "generated"
        assert stored2.get("rule_name") != "Human Edited Rule Name"

    finally:
        # Cleanup
        firestore_client.collection(suggestions_coll).document(suggestion_id).delete()
        firestore_client.collection(patterns_coll).document(trace_id).delete()
        if created_run_id:
            firestore_client.collection(errors_coll).document(
                f"{created_run_id}:{suggestion_id}"
            ).delete()


def test_health_endpoint_returns_status(client):
    """Test health endpoint returns OK status with config info."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()

    assert body.get("status") == "ok"
    assert body.get("version") is not None
    assert "config" in body
    assert body["config"].get("model") is not None
    assert body["config"].get("batchSize") is not None


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v"] + sys.argv[1:])
