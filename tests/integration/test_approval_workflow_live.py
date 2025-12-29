"""Live integration tests for approval workflow API.

These tests require real Firestore access and are only run when RUN_LIVE_TESTS=1.
No mocks - tests hit real infrastructure.

Usage:
    RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_approval_workflow_live.py -v
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

# Skip all tests in this module unless RUN_LIVE_TESTS=1
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="Live tests require RUN_LIVE_TESTS=1"
)


@pytest.fixture(scope="module")
def api_key():
    """Get API key from environment or use test default."""
    key = os.getenv("APPROVAL_API_KEY", "test-api-key-for-live-tests")
    # Set it in environment for the app to use
    os.environ["APPROVAL_API_KEY"] = key
    return key


@pytest.fixture(scope="module")
def client():
    """Create FastAPI test client."""
    from src.api.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def firestore_client():
    """Get Firestore client for test setup/cleanup."""
    from src.api.approval.repository import get_firestore_client
    return get_firestore_client()


@pytest.fixture
def test_suggestion_id():
    """Generate a unique test suggestion ID."""
    return f"test_sugg_{uuid.uuid4().hex[:12]}"


def create_test_suggestion(
    firestore_client,
    suggestion_id: str,
    status: str = "pending",
    suggestion_type: str = "eval",
) -> dict:
    """Create a test suggestion document in Firestore.

    Args:
        firestore_client: Firestore client.
        suggestion_id: Unique ID for the suggestion.
        status: Initial status (default: pending).
        suggestion_type: Type of suggestion (default: eval).

    Returns:
        The created suggestion data.
    """
    from src.common.config import load_approval_config

    config = load_approval_config()
    collection_name = f"{config.firestore.collection_prefix}suggestions"
    collection = firestore_client.collection(collection_name)

    now = datetime.now(timezone.utc).isoformat()

    suggestion_data = {
        "suggestion_id": suggestion_id,
        "type": suggestion_type,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "source_traces": ["test_trace_001"],
        "pattern": {
            "failure_type": "test_failure",
            "severity": "medium",
            "trigger_condition": "Test condition",
        },
        "suggestion_content": {
            "eval_test": {
                "title": "Test eval",
                "input": {"prompt": "Test prompt"},
                "assertions": {"required": ["Test assertion"]},
            }
        },
        "version_history": [
            {
                "status": status,
                "timestamp": now,
                "actor": "test-setup",
            }
        ],
    }

    collection.document(suggestion_id).set(suggestion_data)
    return suggestion_data


def cleanup_test_suggestion(firestore_client, suggestion_id: str):
    """Delete a test suggestion from Firestore.

    Args:
        firestore_client: Firestore client.
        suggestion_id: ID of suggestion to delete.
    """
    from src.common.config import load_approval_config

    config = load_approval_config()
    collection_name = f"{config.firestore.collection_prefix}suggestions"
    collection = firestore_client.collection(collection_name)

    collection.document(suggestion_id).delete()


# =============================================================================
# User Story 1: One-Click Approval Tests
# =============================================================================


class TestApprovalWorkflowUS1:
    """Live integration tests for User Story 1: One-Click Approval."""

    def test_approve_pending_suggestion(
        self,
        client,
        firestore_client,
        api_key,
        test_suggestion_id,
    ):
        """Test approving a pending suggestion.

        Creates a pending suggestion, calls POST /suggestions/{id}/approve,
        verifies status transitions to 'approved' and version_history is updated.
        """
        # Setup: Create a pending suggestion
        create_test_suggestion(firestore_client, test_suggestion_id)

        try:
            # Act: Call approve endpoint
            response = client.post(
                f"/suggestions/{test_suggestion_id}/approve",
                headers={"X-API-Key": api_key},
                json={"notes": "Live test approval"},
            )

            # Assert: Response is successful
            assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

            data = response.json()
            assert data["status"] == "success"
            assert data["suggestion_id"] == test_suggestion_id
            assert data["new_status"] == "approved"
            assert "timestamp" in data

            # Verify: Check Firestore directly
            from src.api.approval.repository import get_suggestion
            updated = get_suggestion(firestore_client, test_suggestion_id)

            assert updated is not None
            assert updated["status"] == "approved"
            assert updated["approval_metadata"]["action"] == "approved"
            assert updated["approval_metadata"]["notes"] == "Live test approval"

            # Check version_history has new entry
            history = updated.get("version_history", [])
            assert len(history) >= 2  # Initial + approval
            latest = history[-1]
            assert latest["status"] == "approved"

        finally:
            # Cleanup
            cleanup_test_suggestion(firestore_client, test_suggestion_id)

    def test_approve_requires_api_key(self, client, test_suggestion_id):
        """Test that approve endpoint requires API key."""
        response = client.post(
            f"/suggestions/{test_suggestion_id}/approve",
            json={},
        )
        assert response.status_code == 401

    def test_approve_nonexistent_suggestion(self, client, api_key):
        """Test approving a non-existent suggestion returns 404."""
        response = client.post(
            "/suggestions/nonexistent_id_12345/approve",
            headers={"X-API-Key": api_key},
            json={},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_approve_already_approved_returns_409(
        self,
        client,
        firestore_client,
        api_key,
        test_suggestion_id,
    ):
        """Test approving an already approved suggestion returns 409."""
        # Setup: Create an already approved suggestion
        create_test_suggestion(
            firestore_client,
            test_suggestion_id,
            status="approved",
        )

        try:
            response = client.post(
                f"/suggestions/{test_suggestion_id}/approve",
                headers={"X-API-Key": api_key},
                json={},
            )

            assert response.status_code == 409
            assert "not in pending state" in response.json()["detail"]

        finally:
            cleanup_test_suggestion(firestore_client, test_suggestion_id)


# =============================================================================
# User Story 2: Rejection with Reason Tests
# =============================================================================


class TestRejectionWorkflowUS2:
    """Live integration tests for User Story 2: Rejection with Reason."""

    def test_reject_pending_suggestion(
        self,
        client,
        firestore_client,
        api_key,
        test_suggestion_id,
    ):
        """Test rejecting a pending suggestion with reason.

        Creates a pending suggestion, calls POST /suggestions/{id}/reject,
        verifies status is 'rejected' and reason is recorded.
        """
        create_test_suggestion(firestore_client, test_suggestion_id)

        try:
            response = client.post(
                f"/suggestions/{test_suggestion_id}/reject",
                headers={"X-API-Key": api_key},
                json={"reason": "False positive - test rejection"},
            )

            assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

            data = response.json()
            assert data["status"] == "success"
            assert data["new_status"] == "rejected"

            # Verify in Firestore
            from src.api.approval.repository import get_suggestion
            updated = get_suggestion(firestore_client, test_suggestion_id)

            assert updated["status"] == "rejected"
            assert updated["approval_metadata"]["action"] == "rejected"
            assert updated["approval_metadata"]["reason"] == "False positive - test rejection"

        finally:
            cleanup_test_suggestion(firestore_client, test_suggestion_id)

    def test_reject_requires_reason(self, client, api_key, test_suggestion_id):
        """Test that reject endpoint requires a reason field."""
        response = client.post(
            f"/suggestions/{test_suggestion_id}/reject",
            headers={"X-API-Key": api_key},
            json={},  # Missing reason
        )
        # Pydantic validation should fail
        assert response.status_code == 422

    def test_reject_already_rejected_returns_409(
        self,
        client,
        firestore_client,
        api_key,
        test_suggestion_id,
    ):
        """Test rejecting an already rejected suggestion returns 409."""
        create_test_suggestion(
            firestore_client,
            test_suggestion_id,
            status="rejected",
        )

        try:
            response = client.post(
                f"/suggestions/{test_suggestion_id}/reject",
                headers={"X-API-Key": api_key},
                json={"reason": "Second rejection attempt"},
            )

            assert response.status_code == 409

        finally:
            cleanup_test_suggestion(firestore_client, test_suggestion_id)
