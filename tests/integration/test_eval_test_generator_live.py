"""
Live integration tests for eval test draft generation (Gemini + Firestore).

These tests are skipped unless RUN_LIVE_TESTS=1.
"""

from __future__ import annotations

import os
from datetime import datetime, UTC
import re
from uuid import uuid4

import pytest

from fastapi.testclient import TestClient

from src.common.config import load_firestore_config
from src.common.firestore import (
    eval_test_errors_collection,
    eval_test_runs_collection,
    failure_patterns_collection,
    get_firestore_client,
    suggestions_collection,
)
from src.generators.eval_tests.main import app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="Live eval test generator integration tests require RUN_LIVE_TESTS=1",
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


@pytest.fixture
def test_prefix(monkeypatch) -> str:
    base = os.getenv("LIVE_TEST_COLLECTION_PREFIX", "test")
    prefix = f"{base.rstrip('_')}_evaltests_{uuid4().hex[:8]}_"
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
        "title": "Test failure pattern",
        "failure_type": "hallucination",
        "trigger_condition": "User asked a factual question",
        "summary": "Model responded with an incorrect factual claim.",
        "root_cause_hypothesis": "The model failed to consult a retrieval tool before answering.",
        "evidence": {"signals": ["incorrect_answer"], "excerpt": "The capital of France is Berlin."},
        "recommended_actions": ["Use retrieval before answering factual questions."],
        "reproduction_context": {
            "input_pattern": input_pattern or "",
            "required_state": None,
            "tools_involved": ["retrieval_tool"],
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
        "type": "eval",
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
            "failure_type": "hallucination",
            "trigger_condition": "User asked a factual question",
            "title": "Hallucinated factual response",
            "summary": "Model answered a factual question incorrectly.",
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


def test_run_once_generates_draft_and_template_fallback(
    firestore_client,
    test_prefix,
    client,
):
    suggestions = suggestions_collection(test_prefix)
    patterns = failure_patterns_collection(test_prefix)
    runs = eval_test_runs_collection(test_prefix)
    errors = eval_test_errors_collection(test_prefix)

    trace_ok = f"trace_{uuid4().hex[:8]}"
    suggestion_ok = f"sugg_{uuid4().hex[:8]}"

    trace_missing = f"trace_{uuid4().hex[:8]}"
    suggestion_missing = f"sugg_{uuid4().hex[:8]}"

    created_run_id = None
    try:
        firestore_client.collection(patterns).document(trace_ok).set(
            _create_failure_pattern_doc(trace_id=trace_ok, input_pattern="What is the capital of France?")
        )
        firestore_client.collection(patterns).document(trace_missing).set(
            _create_failure_pattern_doc(trace_id=trace_missing, input_pattern=None)
        )

        firestore_client.collection(suggestions).document(suggestion_ok).set(
            _create_suggestion_doc(suggestion_id=suggestion_ok, trace_id=trace_ok)
        )
        firestore_client.collection(suggestions).document(suggestion_missing).set(
            _create_suggestion_doc(suggestion_id=suggestion_missing, trace_id=trace_missing)
        )

        response = client.post(
            "/eval-tests/run-once",
            json={"batchSize": 2, "suggestionIds": [suggestion_ok, suggestion_missing], "triggeredBy": "manual"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        created_run_id = body.get("runId")

        ok_snapshot = firestore_client.collection(suggestions).document(suggestion_ok).get()
        ok_doc = ok_snapshot.to_dict() or {}
        assert ok_doc["status"] == "pending"
        eval_test_ok = (ok_doc.get("suggestion_content") or {}).get("eval_test")
        assert isinstance(eval_test_ok, dict)
        assert eval_test_ok.get("eval_test_id") == f"eval_{suggestion_ok}"
        assert eval_test_ok.get("title")
        assert eval_test_ok.get("rationale")
        assert eval_test_ok.get("source", {}).get("suggestion_id") == suggestion_ok
        assert eval_test_ok.get("assertions", {}).get("required")
        forbidden = (eval_test_ok.get("assertions", {}) or {}).get("forbidden")
        assert isinstance(forbidden, list)

        missing_snapshot = firestore_client.collection(suggestions).document(suggestion_missing).get()
        missing_doc = missing_snapshot.to_dict() or {}
        assert missing_doc["status"] == "pending"
        eval_test_missing = (missing_doc.get("suggestion_content") or {}).get("eval_test")
        assert isinstance(eval_test_missing, dict)
        assert eval_test_missing.get("status") == "needs_human_input"
        assert "TODO" in (eval_test_missing.get("input", {}) or {}).get("prompt", "")

    finally:
        firestore_client.collection(suggestions).document(suggestion_ok).delete()
        firestore_client.collection(suggestions).document(suggestion_missing).delete()
        firestore_client.collection(patterns).document(trace_ok).delete()
        firestore_client.collection(patterns).document(trace_missing).delete()
        if created_run_id:
            firestore_client.collection(runs).document(created_run_id).delete()
            firestore_client.collection(errors).document(f"{created_run_id}:{suggestion_ok}").delete()
            firestore_client.collection(errors).document(f"{created_run_id}:{suggestion_missing}").delete()


def test_generate_endpoint_blocks_human_edits_without_force_overwrite(
    firestore_client,
    test_prefix,
    client,
):
    suggestions = suggestions_collection(test_prefix)
    patterns = failure_patterns_collection(test_prefix)
    errors = eval_test_errors_collection(test_prefix)

    trace_id = f"trace_{uuid4().hex[:8]}"
    suggestion_id = f"sugg_{uuid4().hex[:8]}"

    created_run_id = None
    try:
        firestore_client.collection(patterns).document(trace_id).set(
            _create_failure_pattern_doc(trace_id=trace_id, input_pattern="What is the capital of France?")
        )
        firestore_client.collection(suggestions).document(suggestion_id).set(
            _create_suggestion_doc(suggestion_id=suggestion_id, trace_id=trace_id)
        )

        resp = client.post(
            f"/eval-tests/generate/{suggestion_id}",
            json={"triggeredBy": "manual", "forceOverwrite": False},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        eval_test = body.get("evalTest") or {}
        created_run_id = ((eval_test.get("generator_meta") or {}).get("run_id")) or None

        snapshot = firestore_client.collection(suggestions).document(suggestion_id).get()
        doc = snapshot.to_dict() or {}
        stored = (doc.get("suggestion_content") or {}).get("eval_test") or {}

        assert stored.get("rationale"), "expected non-empty rationale"
        assert stored.get("source", {}).get("trace_ids") == [trace_id]
        assert stored.get("source", {}).get("pattern_ids") == [f"pattern_{trace_id}"]

        firestore_client.collection(suggestions).document(suggestion_id).update(
            {
                "suggestion_content.eval_test.edit_source": "human",
                "suggestion_content.eval_test.title": "Human edited title",
            }
        )

        blocked = client.post(
            f"/eval-tests/generate/{suggestion_id}",
            json={"triggeredBy": "manual", "forceOverwrite": False},
        )
        assert blocked.status_code == 409, blocked.text

        overwritten = client.post(
            f"/eval-tests/generate/{suggestion_id}",
            json={"triggeredBy": "manual", "forceOverwrite": True},
        )
        assert overwritten.status_code == 200, overwritten.text

        snapshot2 = firestore_client.collection(suggestions).document(suggestion_id).get()
        doc2 = snapshot2.to_dict() or {}
        stored2 = (doc2.get("suggestion_content") or {}).get("eval_test") or {}
        assert stored2.get("edit_source") == "generated"
        assert stored2.get("title") != "Human edited title"

    finally:
        firestore_client.collection(suggestions).document(suggestion_id).delete()
        firestore_client.collection(patterns).document(trace_id).delete()
        if created_run_id:
            firestore_client.collection(errors).document(f"{created_run_id}:{suggestion_id}").delete()


def test_get_endpoint_returns_artifact_and_redacts_basic_pii(
    firestore_client,
    test_prefix,
    client,
):
    suggestions = suggestions_collection(test_prefix)
    patterns = failure_patterns_collection(test_prefix)

    trace_id = f"trace_{uuid4().hex[:8]}"
    suggestion_id = f"sugg_{uuid4().hex[:8]}"

    try:
        firestore_client.collection(patterns).document(trace_id).set(
            _create_failure_pattern_doc(
                trace_id=trace_id,
                input_pattern="Email alice@example.com and call 555-555-5555 for support.",
            )
        )
        firestore_client.collection(suggestions).document(suggestion_id).set(
            _create_suggestion_doc(suggestion_id=suggestion_id, trace_id=trace_id)
        )

        gen = client.post(
            f"/eval-tests/generate/{suggestion_id}",
            json={"triggeredBy": "manual", "forceOverwrite": True},
        )
        assert gen.status_code == 200, gen.text

        resp = client.get(f"/eval-tests/{suggestion_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body.get("suggestion_id") == suggestion_id
        assert body.get("suggestion_status") == "pending"
        eval_test = body.get("eval_test") or {}

        # Regex patterns for PII detection - using raw strings with single backslashes
        # for proper regex interpretation (e.g., \. matches literal period, \b is word boundary)
        email_re = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
        phone_re = re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")

        strings_to_check = [
            eval_test.get("title"),
            eval_test.get("rationale"),
            (eval_test.get("input") or {}).get("prompt"),
            (eval_test.get("input") or {}).get("required_state"),
            *((eval_test.get("assertions") or {}).get("required") or []),
            *((eval_test.get("assertions") or {}).get("forbidden") or []),
            (eval_test.get("assertions") or {}).get("golden_output"),
            (eval_test.get("assertions") or {}).get("notes"),
        ]

        for value in strings_to_check:
            if not value:
                continue
            assert not email_re.search(value), f"email leaked in stored text: {value}"
            assert not phone_re.search(value), f"phone leaked in stored text: {value}"
    finally:
        firestore_client.collection(suggestions).document(suggestion_id).delete()
        firestore_client.collection(patterns).document(trace_id).delete()
