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
                "new_status": status,
                "previous_status": None,
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

            # Check version_history has new entry (uses new_status per codebase schema)
            history = updated.get("version_history", [])
            assert len(history) >= 2  # Initial + approval
            latest = history[-1]
            assert latest["new_status"] == "approved"

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


# =============================================================================
# User Story 3: Export Approved Suggestions Tests
# =============================================================================


class TestExportWorkflowUS3:
    """Live integration tests for User Story 3: Export Approved Suggestions."""

    def test_export_deepeval_format(
        self,
        client,
        firestore_client,
        api_key,
        test_suggestion_id,
    ):
        """Test exporting an approved suggestion in DeepEval JSON format.

        Creates a pending suggestion, approves it, exports as deepeval,
        validates JSON is parseable and matches DeepEval schema.
        """
        import json

        # Setup: Create and approve a suggestion
        create_test_suggestion(firestore_client, test_suggestion_id)

        try:
            # First approve it
            approve_response = client.post(
                f"/suggestions/{test_suggestion_id}/approve",
                headers={"X-API-Key": api_key},
                json={"notes": "Approving for export test"},
            )
            assert approve_response.status_code == 200

            # Export as deepeval
            response = client.get(
                f"/suggestions/{test_suggestion_id}/export",
                headers={"X-API-Key": api_key},
                params={"format": "deepeval"},
            )

            assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
            assert "application/json" in response.headers["content-type"]

            # Validate JSON is parseable
            data = json.loads(response.text)
            assert isinstance(data, list)
            assert len(data) >= 1

            # Validate DeepEval schema - must have input and actual_output
            test_case = data[0]
            assert "input" in test_case
            assert "actual_output" in test_case
            assert test_case["input"] == "Test prompt"

        finally:
            cleanup_test_suggestion(firestore_client, test_suggestion_id)

    def test_export_pytest_format(
        self,
        client,
        firestore_client,
        api_key,
        test_suggestion_id,
    ):
        """Test exporting an approved suggestion in Pytest format.

        Creates and approves a suggestion, exports as pytest,
        validates Python is syntactically valid.
        """
        import ast

        # Setup: Create and approve a suggestion
        create_test_suggestion(firestore_client, test_suggestion_id)

        try:
            # First approve it
            approve_response = client.post(
                f"/suggestions/{test_suggestion_id}/approve",
                headers={"X-API-Key": api_key},
                json={},
            )
            assert approve_response.status_code == 200

            # Export as pytest
            response = client.get(
                f"/suggestions/{test_suggestion_id}/export",
                headers={"X-API-Key": api_key},
                params={"format": "pytest"},
            )

            assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
            assert "text/x-python" in response.headers["content-type"]

            # Validate Python is syntactically valid
            code = response.text
            ast.parse(code)  # Raises SyntaxError if invalid

            # Check it contains expected elements
            assert "def test_" in code
            assert "Test prompt" in code

        finally:
            cleanup_test_suggestion(firestore_client, test_suggestion_id)

    def test_export_yaml_format(
        self,
        client,
        firestore_client,
        api_key,
        test_suggestion_id,
    ):
        """Test exporting an approved suggestion in YAML format.

        Creates and approves a suggestion, exports as yaml,
        validates YAML is loadable.
        """
        import yaml

        # Setup: Create and approve a suggestion
        create_test_suggestion(firestore_client, test_suggestion_id)

        try:
            # First approve it
            approve_response = client.post(
                f"/suggestions/{test_suggestion_id}/approve",
                headers={"X-API-Key": api_key},
                json={},
            )
            assert approve_response.status_code == 200

            # Export as yaml
            response = client.get(
                f"/suggestions/{test_suggestion_id}/export",
                headers={"X-API-Key": api_key},
                params={"format": "yaml"},
            )

            assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
            assert "application/x-yaml" in response.headers["content-type"]

            # Validate YAML is loadable
            data = yaml.safe_load(response.text)
            assert "evalforge_test" in data
            assert data["evalforge_test"]["metadata"]["suggestion_id"] == test_suggestion_id

        finally:
            cleanup_test_suggestion(firestore_client, test_suggestion_id)

    def test_export_not_approved_returns_409(
        self,
        client,
        firestore_client,
        api_key,
        test_suggestion_id,
    ):
        """Test exporting a non-approved suggestion returns 409."""
        # Setup: Create a pending suggestion (not approved)
        create_test_suggestion(firestore_client, test_suggestion_id, status="pending")

        try:
            response = client.get(
                f"/suggestions/{test_suggestion_id}/export",
                headers={"X-API-Key": api_key},
                params={"format": "deepeval"},
            )

            assert response.status_code == 409
            assert "not approved" in response.json()["detail"].lower()

        finally:
            cleanup_test_suggestion(firestore_client, test_suggestion_id)

    def test_export_nonexistent_returns_404(self, client, api_key):
        """Test exporting a non-existent suggestion returns 404."""
        response = client.get(
            "/suggestions/nonexistent_id_12345/export",
            headers={"X-API-Key": api_key},
            params={"format": "deepeval"},
        )
        assert response.status_code == 404


# =============================================================================
# User Story 4: Browse Suggestion Queue Tests
# =============================================================================


class TestBrowseQueueUS4:
    """Live integration tests for User Story 4: Browse Suggestion Queue."""

    def test_list_suggestions_basic(
        self,
        client,
        firestore_client,
        api_key,
        test_suggestion_id,
    ):
        """Test basic listing of suggestions."""
        # Setup: Create a test suggestion
        create_test_suggestion(firestore_client, test_suggestion_id)

        try:
            response = client.get(
                "/suggestions",
                headers={"X-API-Key": api_key},
            )

            assert response.status_code == 200
            data = response.json()
            assert "suggestions" in data
            assert "limit" in data
            assert "has_more" in data
            assert isinstance(data["suggestions"], list)

        finally:
            cleanup_test_suggestion(firestore_client, test_suggestion_id)

    def test_list_suggestions_filter_by_status(
        self,
        client,
        firestore_client,
        api_key,
    ):
        """Test filtering suggestions by status."""
        # Create suggestions with different statuses
        pending_id = f"test_sugg_pending_{uuid.uuid4().hex[:8]}"
        approved_id = f"test_sugg_approved_{uuid.uuid4().hex[:8]}"

        create_test_suggestion(firestore_client, pending_id, status="pending")
        create_test_suggestion(firestore_client, approved_id, status="approved")

        try:
            # Filter for pending only
            response = client.get(
                "/suggestions",
                headers={"X-API-Key": api_key},
                params={"status": "pending"},
            )

            assert response.status_code == 200
            data = response.json()

            # All returned suggestions should be pending
            for s in data["suggestions"]:
                assert s["status"] == "pending"

        finally:
            cleanup_test_suggestion(firestore_client, pending_id)
            cleanup_test_suggestion(firestore_client, approved_id)

    def test_list_suggestions_pagination(
        self,
        client,
        firestore_client,
        api_key,
    ):
        """Test cursor-based pagination."""
        # Create multiple suggestions
        ids = [f"test_sugg_page_{uuid.uuid4().hex[:8]}" for _ in range(3)]
        for sid in ids:
            create_test_suggestion(firestore_client, sid)

        try:
            # First page with limit=1
            response = client.get(
                "/suggestions",
                headers={"X-API-Key": api_key},
                params={"limit": 1},
            )

            assert response.status_code == 200
            data = response.json()
            assert len(data["suggestions"]) == 1
            assert data["has_more"] is True
            assert data["next_cursor"] is not None

            # Second page using cursor
            cursor = data["next_cursor"]
            response2 = client.get(
                "/suggestions",
                headers={"X-API-Key": api_key},
                params={"limit": 1, "cursor": cursor},
            )

            assert response2.status_code == 200
            data2 = response2.json()
            assert len(data2["suggestions"]) == 1
            # Should be a different suggestion
            assert data2["suggestions"][0]["suggestion_id"] != data["suggestions"][0]["suggestion_id"]

        finally:
            for sid in ids:
                cleanup_test_suggestion(firestore_client, sid)

    def test_get_suggestion_detail(
        self,
        client,
        firestore_client,
        api_key,
        test_suggestion_id,
    ):
        """Test getting a single suggestion with full details."""
        create_test_suggestion(firestore_client, test_suggestion_id)

        try:
            response = client.get(
                f"/suggestions/{test_suggestion_id}",
                headers={"X-API-Key": api_key},
            )

            assert response.status_code == 200
            data = response.json()

            assert data["suggestion_id"] == test_suggestion_id
            assert data["type"] == "eval"
            assert data["status"] == "pending"
            assert "created_at" in data
            assert "updated_at" in data
            assert "version_history" in data
            assert isinstance(data["version_history"], list)

        finally:
            cleanup_test_suggestion(firestore_client, test_suggestion_id)

    def test_get_suggestion_not_found(self, client, api_key):
        """Test getting a non-existent suggestion returns 404."""
        response = client.get(
            "/suggestions/nonexistent_id_12345",
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 404

    def test_list_suggestions_requires_api_key(self, client):
        """Test that listing suggestions requires API key."""
        response = client.get("/suggestions")
        assert response.status_code == 401


# =============================================================================
# User Story 5: Webhook Notification Tests
# =============================================================================


class TestWebhookNotificationUS5:
    """Live integration tests for User Story 5: Webhook Notifications.

    Note: In minimal test mode, we verify:
    - Endpoint exists and requires authentication
    - Returns 503 when webhook not configured (expected for test env)
    - Approval/rejection trigger webhook calls (verified via logs)
    """

    def test_webhook_test_endpoint_requires_auth(self, client):
        """Test that /webhooks/test endpoint requires API key."""
        response = client.post("/webhooks/test")
        assert response.status_code == 401

    def test_webhook_test_endpoint_sends_to_slack(self, client, api_key):
        """Test webhook test actually sends a message to Slack.

        Requires SLACK_WEBHOOK_URL to be configured in environment.
        Verifies the Block Kit payload is correctly formatted and delivered.
        """
        response = client.post(
            "/webhooks/test",
            headers={"X-API-Key": api_key},
        )

        # With SLACK_WEBHOOK_URL configured, should return 200
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "sent"
        assert "sent successfully" in data["message"].lower()

    def test_webhook_test_endpoint_with_custom_message(self, client, api_key):
        """Test webhook test sends custom message to Slack."""
        response = client.post(
            "/webhooks/test",
            headers={"X-API-Key": api_key},
            json={"message": "🧪 EvalForge Live Test - Custom Message"},
        )

        # With SLACK_WEBHOOK_URL configured, should return 200
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "sent"

    def test_approval_triggers_slack_notification(
        self,
        client,
        firestore_client,
        api_key,
        test_suggestion_id,
    ):
        """Test that approval sends a real Slack notification.

        Requires SLACK_WEBHOOK_URL to be configured.
        Check your Slack channel for the approval notification!
        """
        create_test_suggestion(firestore_client, test_suggestion_id)

        try:
            response = client.post(
                f"/suggestions/{test_suggestion_id}/approve",
                headers={"X-API-Key": api_key},
                json={"notes": "🧪 Live test approval - check Slack!"},
            )

            # Approval should succeed and trigger webhook
            assert response.status_code == 200
            assert response.json()["new_status"] == "approved"
            # Webhook is fire-and-forget but should have been sent
            # Check Slack channel for the notification!

        finally:
            cleanup_test_suggestion(firestore_client, test_suggestion_id)

    def test_rejection_triggers_slack_notification(
        self,
        client,
        firestore_client,
        api_key,
        test_suggestion_id,
    ):
        """Test that rejection sends a real Slack notification.

        Requires SLACK_WEBHOOK_URL to be configured.
        Check your Slack channel for the rejection notification!
        """
        create_test_suggestion(firestore_client, test_suggestion_id)

        try:
            response = client.post(
                f"/suggestions/{test_suggestion_id}/reject",
                headers={"X-API-Key": api_key},
                json={"reason": "🧪 Live test rejection - check Slack!"},
            )

            # Rejection should succeed and trigger webhook
            assert response.status_code == 200
            assert response.json()["new_status"] == "rejected"
            # Webhook is fire-and-forget but should have been sent
            # Check Slack channel for the notification!

        finally:
            cleanup_test_suggestion(firestore_client, test_suggestion_id)


# =============================================================================
# Health Check Tests (Phase 8)
# =============================================================================


class TestHealthCheck:
    """Live integration tests for health check endpoint."""

    def test_health_check_returns_ok(self, client):
        """Test health endpoint returns ok status.

        No authentication required for health checks.
        """
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "pendingCount" in data
        # pendingCount should be an integer (may be 0 or more)
        assert isinstance(data["pendingCount"], int) or data["pendingCount"] is None

    def test_health_check_includes_metrics(self, client):
        """Test health endpoint includes operational metrics."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        # Should include the expected fields
        assert "status" in data
        assert "pendingCount" in data
        assert "lastApprovalAt" in data
