"""
Live integration tests for runbook draft generation (Gemini + Firestore).

These tests are skipped unless RUN_LIVE_TESTS=1.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, UTC
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.common.config import load_firestore_config
from src.common.firestore import (
    failure_patterns_collection,
    get_firestore_client,
    runbook_errors_collection,
    runbook_runs_collection,
    suggestions_collection,
)
from src.generators.runbooks.main import app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="Live runbook generator integration tests require RUN_LIVE_TESTS=1",
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


@pytest.fixture
def test_prefix(monkeypatch) -> str:
    base = os.getenv("LIVE_TEST_COLLECTION_PREFIX", "test")
    prefix = f"{base.rstrip('_')}_runbooks_{uuid4().hex[:8]}_"
    monkeypatch.setenv("FIRESTORE_COLLECTION_PREFIX", prefix)
    return prefix


@pytest.fixture
def firestore_client(test_prefix):
    config = load_firestore_config()
    return get_firestore_client(config)


@pytest.fixture
def client():
    return TestClient(app)


def _create_failure_pattern_doc(*, trace_id: str, input_pattern: str | None) -> dict:
    return {
        "pattern_id": f"pattern_{trace_id}",
        "source_trace_id": trace_id,
        "title": "Stale product recommendations",
        "failure_type": "stale_data",
        "trigger_condition": "Product recommendation without inventory check",
        "summary": "LLM agent recommended discontinued products due to stale inventory cache.",
        "root_cause_hypothesis": "Cache TTL too long, inventory sync delayed.",
        "evidence": {"signals": ["product_unavailable", "customer_complaint"], "excerpt": "Item XYZ is no longer available."},
        "recommended_actions": ["Reduce cache TTL", "Implement real-time sync"],
        "reproduction_context": {
            "input_pattern": input_pattern or "",
            "required_state": "Stale product catalog in cache",
            "tools_involved": ["product_search", "inventory_api"],
        },
        "severity": "medium",
        "confidence": 0.9,
        "confidence_rationale": "High confidence for live test.",
        "extracted_at": _iso_now(),
        "processed": False,
    }


def _create_suggestion_doc(*, suggestion_id: str, trace_id: str) -> dict:
    return {
        "suggestion_id": suggestion_id,
        "type": "runbook",  # Changed from "eval" to "runbook"
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
            "failure_type": "stale_data",
            "trigger_condition": "Product recommendation without inventory check",
            "title": "Stale Product Recommendations",
            "summary": "LLM agent recommended discontinued products.",
            "severity": "medium",
        },
        "embedding": [0.0] * 768,
        "similarity_group": f"group_{uuid4().hex[:8]}",
        "suggestion_content": {},
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


def test_run_once_generates_runbook_with_all_sections(
    firestore_client,
    test_prefix,
    client,
):
    """Test batch generation creates runbook with all 6 required sections."""
    suggestions = suggestions_collection(test_prefix)
    patterns = failure_patterns_collection(test_prefix)
    runs = runbook_runs_collection(test_prefix)
    errors = runbook_errors_collection(test_prefix)

    trace_id = f"trace_{uuid4().hex[:8]}"
    suggestion_id = f"sugg_{uuid4().hex[:8]}"

    created_run_id = None
    try:
        # Create test data
        firestore_client.collection(patterns).document(trace_id).set(
            _create_failure_pattern_doc(trace_id=trace_id, input_pattern="User asks for product recommendations")
        )
        firestore_client.collection(suggestions).document(suggestion_id).set(
            _create_suggestion_doc(suggestion_id=suggestion_id, trace_id=trace_id)
        )

        # Trigger batch generation
        response = client.post(
            "/runbooks/run-once",
            json={"batchSize": 1, "suggestionIds": [suggestion_id], "triggeredBy": "manual"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        created_run_id = body.get("runId")

        assert body.get("generatedCount") == 1, f"Expected 1 generated, got {body}"

        # Verify runbook was embedded on suggestion
        snapshot = firestore_client.collection(suggestions).document(suggestion_id).get()
        doc = snapshot.to_dict() or {}
        assert doc["status"] == "pending"  # Status not modified by generator

        runbook = (doc.get("suggestion_content") or {}).get("runbook_snippet")
        assert isinstance(runbook, dict), "runbook_snippet should be a dict"

        # Verify required fields
        assert runbook.get("runbook_id") == f"runbook_{suggestion_id}"
        assert runbook.get("title"), "title should not be empty"
        assert runbook.get("rationale"), "rationale should not be empty"
        assert runbook.get("markdown_content"), "markdown_content should not be empty"

        # Verify structured fields
        assert isinstance(runbook.get("symptoms"), list), "symptoms should be a list"
        assert len(runbook.get("symptoms", [])) >= 1, "should have at least 1 symptom"

        assert isinstance(runbook.get("diagnosis_commands"), list), "diagnosis_commands should be a list"
        assert len(runbook.get("diagnosis_commands", [])) >= 2, "should have at least 2 diagnosis commands"

        assert isinstance(runbook.get("mitigation_steps"), list), "mitigation_steps should be a list"
        assert runbook.get("escalation_criteria"), "escalation_criteria should not be empty"

        # Verify lineage tracking (FR-007)
        source = runbook.get("source", {})
        assert source.get("suggestion_id") == suggestion_id
        assert source.get("trace_ids") == [trace_id]
        assert source.get("pattern_ids") == [f"pattern_{trace_id}"]

        # Verify generator meta (FR-008)
        meta = runbook.get("generator_meta", {})
        assert meta.get("model"), "model should be set"
        assert meta.get("prompt_hash"), "prompt_hash should be set"
        assert meta.get("response_sha256"), "response_sha256 should be set"

        # Verify markdown contains all 6 sections
        markdown = runbook.get("markdown_content", "")
        required_sections = ["Summary", "Symptoms", "Diagnosis", "Mitigation", "Root Cause", "Escalation"]
        for section in required_sections:
            assert section.lower() in markdown.lower(), f"Markdown should contain {section} section"

    finally:
        firestore_client.collection(suggestions).document(suggestion_id).delete()
        firestore_client.collection(patterns).document(trace_id).delete()
        if created_run_id:
            firestore_client.collection(runs).document(created_run_id).delete()
            firestore_client.collection(errors).document(f"{created_run_id}:{suggestion_id}").delete()


def test_template_fallback_for_missing_context(
    firestore_client,
    test_prefix,
    client,
):
    """Test that missing reproduction context triggers template fallback."""
    suggestions = suggestions_collection(test_prefix)
    patterns = failure_patterns_collection(test_prefix)
    runs = runbook_runs_collection(test_prefix)

    trace_id = f"trace_{uuid4().hex[:8]}"
    suggestion_id = f"sugg_{uuid4().hex[:8]}"

    created_run_id = None
    try:
        # Create pattern with empty input_pattern
        firestore_client.collection(patterns).document(trace_id).set(
            _create_failure_pattern_doc(trace_id=trace_id, input_pattern=None)
        )
        firestore_client.collection(suggestions).document(suggestion_id).set(
            _create_suggestion_doc(suggestion_id=suggestion_id, trace_id=trace_id)
        )

        response = client.post(
            "/runbooks/run-once",
            json={"batchSize": 1, "suggestionIds": [suggestion_id], "triggeredBy": "manual"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        created_run_id = body.get("runId")

        snapshot = firestore_client.collection(suggestions).document(suggestion_id).get()
        doc = snapshot.to_dict() or {}
        runbook = (doc.get("suggestion_content") or {}).get("runbook_snippet")

        assert runbook.get("status") == "needs_human_input"
        assert "TODO" in runbook.get("markdown_content", "")
        assert runbook.get("generator_meta", {}).get("model", "").startswith("template_")

    finally:
        firestore_client.collection(suggestions).document(suggestion_id).delete()
        firestore_client.collection(patterns).document(trace_id).delete()
        if created_run_id:
            firestore_client.collection(runs).document(created_run_id).delete()


def test_generate_endpoint_blocks_human_edits_without_force_overwrite(
    firestore_client,
    test_prefix,
    client,
):
    """Test human edit protection and forceOverwrite behavior."""
    suggestions = suggestions_collection(test_prefix)
    patterns = failure_patterns_collection(test_prefix)
    errors = runbook_errors_collection(test_prefix)

    trace_id = f"trace_{uuid4().hex[:8]}"
    suggestion_id = f"sugg_{uuid4().hex[:8]}"

    created_run_ids = []
    try:
        firestore_client.collection(patterns).document(trace_id).set(
            _create_failure_pattern_doc(trace_id=trace_id, input_pattern="User asks for recommendations")
        )
        firestore_client.collection(suggestions).document(suggestion_id).set(
            _create_suggestion_doc(suggestion_id=suggestion_id, trace_id=trace_id)
        )

        # Generate initial runbook
        resp = client.post(
            f"/runbooks/generate/{suggestion_id}",
            json={"triggeredBy": "manual", "forceOverwrite": False},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        runbook = body.get("runbook") or {}
        run_id = runbook.get("generator_meta", {}).get("run_id")
        if run_id:
            created_run_ids.append(run_id)

        # Verify lineage in stored runbook
        snapshot = firestore_client.collection(suggestions).document(suggestion_id).get()
        doc = snapshot.to_dict() or {}
        stored = (doc.get("suggestion_content") or {}).get("runbook_snippet") or {}
        assert stored.get("rationale"), "expected non-empty rationale"
        assert stored.get("source", {}).get("trace_ids") == [trace_id]

        # Simulate human edit
        firestore_client.collection(suggestions).document(suggestion_id).update(
            {
                "suggestion_content.runbook_snippet.edit_source": "human",
                "suggestion_content.runbook_snippet.title": "Human edited title",
            }
        )

        # Should be blocked without forceOverwrite
        blocked = client.post(
            f"/runbooks/generate/{suggestion_id}",
            json={"triggeredBy": "manual", "forceOverwrite": False},
        )
        assert blocked.status_code == 409, f"Expected 409, got {blocked.status_code}: {blocked.text}"

        # Should succeed with forceOverwrite
        overwritten = client.post(
            f"/runbooks/generate/{suggestion_id}",
            json={"triggeredBy": "manual", "forceOverwrite": True},
        )
        assert overwritten.status_code == 200, overwritten.text
        new_run_id = overwritten.json().get("runbook", {}).get("generator_meta", {}).get("run_id")
        if new_run_id:
            created_run_ids.append(new_run_id)

        snapshot2 = firestore_client.collection(suggestions).document(suggestion_id).get()
        doc2 = snapshot2.to_dict() or {}
        stored2 = (doc2.get("suggestion_content") or {}).get("runbook_snippet") or {}
        assert stored2.get("edit_source") == "generated"
        assert stored2.get("title") != "Human edited title"

    finally:
        firestore_client.collection(suggestions).document(suggestion_id).delete()
        firestore_client.collection(patterns).document(trace_id).delete()
        for run_id in created_run_ids:
            firestore_client.collection(errors).document(f"{run_id}:{suggestion_id}").delete()


def test_get_endpoint_returns_runbook_artifact(
    firestore_client,
    test_prefix,
    client,
):
    """Test retrieval endpoint returns complete runbook with approval metadata."""
    suggestions = suggestions_collection(test_prefix)
    patterns = failure_patterns_collection(test_prefix)

    trace_id = f"trace_{uuid4().hex[:8]}"
    suggestion_id = f"sugg_{uuid4().hex[:8]}"

    try:
        firestore_client.collection(patterns).document(trace_id).set(
            _create_failure_pattern_doc(trace_id=trace_id, input_pattern="User asks for recommendations")
        )
        firestore_client.collection(suggestions).document(suggestion_id).set(
            _create_suggestion_doc(suggestion_id=suggestion_id, trace_id=trace_id)
        )

        # Generate runbook first
        gen = client.post(
            f"/runbooks/generate/{suggestion_id}",
            json={"triggeredBy": "manual", "forceOverwrite": True},
        )
        assert gen.status_code == 200, gen.text

        # Retrieve runbook
        resp = client.get(f"/runbooks/{suggestion_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body.get("suggestion_id") == suggestion_id
        assert body.get("suggestion_status") == "pending"

        runbook = body.get("runbook") or {}
        assert runbook.get("runbook_id") == f"runbook_{suggestion_id}"
        assert runbook.get("title")
        assert runbook.get("rationale")
        assert runbook.get("markdown_content")
        assert isinstance(runbook.get("symptoms"), list)
        assert isinstance(runbook.get("diagnosis_commands"), list)

    finally:
        firestore_client.collection(suggestions).document(suggestion_id).delete()
        firestore_client.collection(patterns).document(trace_id).delete()


def test_get_endpoint_returns_404_for_missing_runbook(
    firestore_client,
    test_prefix,
    client,
):
    """Test retrieval returns 404 when runbook doesn't exist."""
    suggestions = suggestions_collection(test_prefix)

    suggestion_id = f"sugg_{uuid4().hex[:8]}"

    try:
        # Create suggestion without runbook
        firestore_client.collection(suggestions).document(suggestion_id).set(
            _create_suggestion_doc(suggestion_id=suggestion_id, trace_id="dummy_trace")
        )

        resp = client.get(f"/runbooks/{suggestion_id}")
        assert resp.status_code == 404

    finally:
        firestore_client.collection(suggestions).document(suggestion_id).delete()


def test_health_endpoint(client):
    """Test health endpoint returns config info."""
    resp = client.get("/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body.get("status") == "ok"
    assert "version" in body
    assert "backlog" in body
    assert "pendingRunbookSuggestions" in body.get("backlog", {})
    assert "config" in body
    assert "model" in body.get("config", {})
    assert "batchSize" in body.get("config", {})
