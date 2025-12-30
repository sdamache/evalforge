"""Live integration tests for approval workflow actions.

These tests verify that approve/reject actions work against the live
Approval API (Issue #8) and update Firestore correctly.

Run with: RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_approval_action_live.py -v

Prerequisites:
- Approval API deployed and accessible
- APPROVAL_API_URL and APPROVAL_API_KEY environment variables set
- Firestore database with test suggestions
"""

import os
import time
import uuid
import pytest
import requests

# Skip all tests if RUN_LIVE_TESTS is not set
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="Live tests disabled. Set RUN_LIVE_TESTS=1 to run.",
)


@pytest.fixture
def approval_api_config():
    """Load Approval API configuration from environment."""
    api_url = os.environ.get("APPROVAL_API_URL")
    api_key = os.environ.get("APPROVAL_API_KEY")

    if not api_url:
        pytest.skip("APPROVAL_API_URL not set - skipping approval action tests")

    return {
        "base_url": api_url.rstrip("/"),
        "api_key": api_key,
        "headers": {
            "Authorization": f"Bearer {api_key}" if api_key else None,
            "Content-Type": "application/json",
        },
    }


@pytest.fixture
def test_suggestion_id():
    """Generate a unique test suggestion ID."""
    return f"test_sugg_{uuid.uuid4().hex[:8]}"


class TestApprovalActionLive:
    """Live integration tests for approval workflow."""

    def test_api_health_check(self, approval_api_config):
        """Test that Approval API is accessible.

        Verifies:
        - API is running and responding
        - Health endpoint returns 200
        """
        url = f"{approval_api_config['base_url']}/health"
        response = requests.get(url, timeout=10)

        assert response.status_code == 200, f"Health check failed: {response.text}"
        print(f"API Health: {response.json()}")

    def test_list_pending_suggestions(self, approval_api_config):
        """Test listing pending suggestions.

        Verifies:
        - GET /suggestions endpoint works
        - Returns list of suggestions
        """
        url = f"{approval_api_config['base_url']}/suggestions"
        params = {"status": "pending", "limit": 10}
        headers = {k: v for k, v in approval_api_config["headers"].items() if v}

        response = requests.get(url, params=params, headers=headers, timeout=10)

        # API might return 200 with empty list or 404 if no suggestions
        assert response.status_code in [200, 404], f"List failed: {response.text}"

        if response.status_code == 200:
            data = response.json()
            print(f"Found {len(data.get('suggestions', data))} pending suggestions")

    def test_approve_action_updates_status(self, approval_api_config):
        """Test that approve action updates suggestion status.

        Note: This test requires a pending suggestion to exist.
        If no pending suggestions exist, the test will be skipped.

        Verifies:
        - POST /suggestions/{id}/approve returns 200
        - Status is updated to 'approved'
        """
        # First, get a pending suggestion
        url = f"{approval_api_config['base_url']}/suggestions"
        params = {"status": "pending", "limit": 1}
        headers = {k: v for k, v in approval_api_config["headers"].items() if v}

        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code != 200:
            pytest.skip("No suggestions endpoint available")

        data = response.json()
        suggestions = data.get("suggestions", data) if isinstance(data, dict) else data

        if not suggestions:
            pytest.skip("No pending suggestions available to test approval")

        suggestion_id = suggestions[0].get("suggestion_id") or suggestions[0].get("id")
        print(f"Testing approval on suggestion: {suggestion_id}")

        # Approve the suggestion
        approve_url = f"{approval_api_config['base_url']}/suggestions/{suggestion_id}/approve"
        response = requests.post(approve_url, headers=headers, json={}, timeout=10)

        assert response.status_code == 200, f"Approve failed: {response.text}"

        result = response.json()
        print(f"Approve result: {result}")

        # Verify status is now approved
        assert result.get("status") == "approved" or "approved" in str(result).lower()

    def test_reject_action_updates_status(self, approval_api_config):
        """Test that reject action updates suggestion status.

        Note: This test requires a pending suggestion to exist.
        If no pending suggestions exist, the test will be skipped.

        Verifies:
        - POST /suggestions/{id}/reject returns 200
        - Status is updated to 'rejected'
        """
        # First, get a pending suggestion
        url = f"{approval_api_config['base_url']}/suggestions"
        params = {"status": "pending", "limit": 1}
        headers = {k: v for k, v in approval_api_config["headers"].items() if v}

        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code != 200:
            pytest.skip("No suggestions endpoint available")

        data = response.json()
        suggestions = data.get("suggestions", data) if isinstance(data, dict) else data

        if not suggestions:
            pytest.skip("No pending suggestions available to test rejection")

        suggestion_id = suggestions[0].get("suggestion_id") or suggestions[0].get("id")
        print(f"Testing rejection on suggestion: {suggestion_id}")

        # Reject the suggestion
        reject_url = f"{approval_api_config['base_url']}/suggestions/{suggestion_id}/reject"
        response = requests.post(
            reject_url,
            headers=headers,
            json={"reason": "Test rejection from live integration test"},
            timeout=10,
        )

        assert response.status_code == 200, f"Reject failed: {response.text}"

        result = response.json()
        print(f"Reject result: {result}")

        # Verify status is now rejected
        assert result.get("status") == "rejected" or "rejected" in str(result).lower()

    def test_action_response_time_under_3_seconds(self, approval_api_config):
        """Test that approval action completes within SLA.

        Verifies:
        - Action completes within 3 seconds (SC-005)
        """
        # Get a pending suggestion
        url = f"{approval_api_config['base_url']}/suggestions"
        params = {"status": "pending", "limit": 1}
        headers = {k: v for k, v in approval_api_config["headers"].items() if v}

        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code != 200:
            pytest.skip("No suggestions endpoint available")

        data = response.json()
        suggestions = data.get("suggestions", data) if isinstance(data, dict) else data

        if not suggestions:
            pytest.skip("No pending suggestions available for timing test")

        suggestion_id = suggestions[0].get("suggestion_id") or suggestions[0].get("id")

        # Time the approval action
        approve_url = f"{approval_api_config['base_url']}/suggestions/{suggestion_id}/approve"
        start_time = time.time()
        response = requests.post(approve_url, headers=headers, json={}, timeout=10)
        elapsed = time.time() - start_time

        print(f"Approval action took: {elapsed:.2f} seconds")

        assert response.status_code == 200, f"Approve failed: {response.text}"
        assert elapsed < 3.0, f"Action took {elapsed:.2f}s, expected < 3s"

    def test_invalid_suggestion_returns_404(self, approval_api_config):
        """Test that approving non-existent suggestion returns 404.

        Verifies:
        - API handles invalid IDs gracefully
        """
        headers = {k: v for k, v in approval_api_config["headers"].items() if v}
        fake_id = f"nonexistent_{uuid.uuid4().hex[:8]}"

        url = f"{approval_api_config['base_url']}/suggestions/{fake_id}/approve"
        response = requests.post(url, headers=headers, json={}, timeout=10)

        # Should return 404 Not Found
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
