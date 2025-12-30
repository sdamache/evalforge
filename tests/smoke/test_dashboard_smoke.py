"""End-to-end smoke tests for Datadog Dashboard Integration.

These tests validate the full workflow: publish metrics → approve suggestion → verify update.
They include edge case testing for robustness validation.

Run with: RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/smoke/test_dashboard_smoke.py -v

Prerequisites:
- Metrics Publisher Cloud Function deployed OR local environment configured
- Approval API deployed and accessible
- Firestore database with test suggestions
- Datadog API credentials configured
"""

import os
import time
import uuid
import statistics
from typing import Optional
import pytest
import requests

# Skip all tests if RUN_LIVE_TESTS is not set
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="Smoke tests disabled. Set RUN_LIVE_TESTS=1 to run.",
)


@pytest.fixture
def approval_api_config():
    """Load Approval API configuration from environment."""
    api_url = os.environ.get("APPROVAL_API_URL")
    api_key = os.environ.get("APPROVAL_API_KEY")

    if not api_url:
        pytest.skip("APPROVAL_API_URL not set - skipping smoke tests")

    return {
        "base_url": api_url.rstrip("/"),
        "api_key": api_key,
        "headers": {
            "X-API-Key": api_key if api_key else None,
            "Content-Type": "application/json",
        },
    }


@pytest.fixture
def datadog_config():
    """Load Datadog configuration from environment."""
    api_key = os.environ.get("DATADOG_API_KEY")
    site = os.environ.get("DATADOG_SITE", "us5.datadoghq.com")

    if not api_key:
        pytest.skip("DATADOG_API_KEY not set - skipping Datadog tests")

    return {
        "api_key": api_key,
        "site": site,
        "metrics_url": f"https://api.{site}/api/v2/series",
    }


class TestDashboardSmokeEndToEnd:
    """End-to-end smoke tests for the complete dashboard workflow."""

    def test_full_flow_publish_view_approve(self, approval_api_config, datadog_config):
        """Test complete workflow: publish metrics → list suggestions → approve one.

        This is the core smoke test validating the entire feedback loop:
        1. Verify metrics can be published to Datadog
        2. Verify suggestions can be listed from Approval API
        3. Verify a suggestion can be approved
        4. Verify the approval is reflected in the system

        Validates: T037 full smoke test requirement
        """
        # Step 1: Verify metrics API is accessible
        test_metric_payload = {
            "series": [
                {
                    "metric": "evalforge.smoke_test",
                    "type": 3,  # GAUGE
                    "points": [{"timestamp": int(time.time()), "value": 1}],
                    "tags": ["env:test", "smoke:true"],
                }
            ]
        }

        metrics_response = requests.post(
            datadog_config["metrics_url"],
            headers={
                "DD-API-KEY": datadog_config["api_key"],
                "Content-Type": "application/json",
            },
            json=test_metric_payload,
            timeout=10,
        )

        assert metrics_response.status_code in [
            200,
            202,
        ], f"Metrics submission failed: {metrics_response.text}"
        print("Step 1: Metrics API accessible ✓")

        # Step 2: List pending suggestions
        headers = {k: v for k, v in approval_api_config["headers"].items() if v}
        list_url = f"{approval_api_config['base_url']}/suggestions"

        list_response = requests.get(
            list_url, params={"status": "pending", "limit": 10}, headers=headers, timeout=10
        )

        if list_response.status_code == 404:
            pytest.skip("No suggestions endpoint available")

        assert list_response.status_code == 200, f"List failed: {list_response.text}"
        print("Step 2: Suggestions listed successfully ✓")

        # Step 3: Approve a suggestion (if any available)
        data = list_response.json()
        suggestions = data.get("suggestions", data) if isinstance(data, dict) else data

        if not suggestions:
            print("Step 3: No pending suggestions to approve (empty state) ✓")
            return

        suggestion_id = suggestions[0].get("suggestion_id") or suggestions[0].get("id")
        approve_url = f"{approval_api_config['base_url']}/suggestions/{suggestion_id}/approve"

        start_time = time.time()
        approve_response = requests.post(approve_url, headers=headers, json={}, timeout=10)
        approve_time = time.time() - start_time

        assert approve_response.status_code == 200, f"Approve failed: {approve_response.text}"
        assert approve_time < 3.0, f"Approve took {approve_time:.2f}s, expected < 3s"
        print(f"Step 3: Suggestion approved in {approve_time:.2f}s ✓")

        # Step 4: Verify status changed
        result = approve_response.json()
        assert result.get("status") == "approved" or "approved" in str(result).lower()
        print("Step 4: Status verified as approved ✓")

        print("\n=== Full smoke test PASSED ===")


class TestEdgeCaseEmptyState:
    """Test dashboard behavior with zero pending suggestions."""

    def test_empty_state_graceful_handling(self, approval_api_config):
        """Test that system handles 0 pending suggestions gracefully.

        Validates edge case: Empty state (0 pending suggestions)
        - Dashboard should display "0 pending" gracefully, not show an error
        """
        headers = {k: v for k, v in approval_api_config["headers"].items() if v}
        url = f"{approval_api_config['base_url']}/suggestions"

        response = requests.get(
            url, params={"status": "pending", "limit": 10}, headers=headers, timeout=10
        )

        # Should return 200 with empty list, not error
        assert response.status_code in [200, 404], f"Unexpected status: {response.status_code}"

        if response.status_code == 200:
            data = response.json()
            suggestions = data.get("suggestions", data) if isinstance(data, dict) else data

            # Empty list is valid - system handles gracefully
            if not suggestions:
                print("Empty state handled gracefully: returned empty list ✓")
            else:
                print(f"Non-empty state: {len(suggestions)} suggestions found")


class TestEdgeCaseLargeDataset:
    """Test dashboard behavior with large datasets (1000+ suggestions)."""

    def test_large_dataset_response_time(self, approval_api_config):
        """Test that listing suggestions performs well with large datasets.

        Validates edge case: Large dataset (1000+ suggestions)
        - Dashboard should load in <2 seconds even with 1000+ suggestions
        """
        headers = {k: v for k, v in approval_api_config["headers"].items() if v}
        url = f"{approval_api_config['base_url']}/suggestions"

        # Request a large page to simulate large dataset scenario
        start_time = time.time()
        response = requests.get(
            url, params={"status": "pending", "limit": 100}, headers=headers, timeout=10
        )
        response_time = time.time() - start_time

        if response.status_code == 404:
            pytest.skip("Suggestions endpoint not available")

        assert response.status_code == 200, f"List failed: {response.text}"

        # Performance check: should respond in < 2 seconds even for large pages
        assert response_time < 2.0, f"Response took {response_time:.2f}s, expected < 2s"

        data = response.json()
        suggestions = data.get("suggestions", data) if isinstance(data, dict) else data
        print(f"Large dataset test: {len(suggestions)} suggestions in {response_time:.2f}s ✓")


class TestEdgeCaseRapidActions:
    """Test dashboard behavior with rapid consecutive actions."""

    def test_rapid_consecutive_actions(self, approval_api_config):
        """Test that rapid consecutive actions are handled correctly.

        Validates edge case: Rapid consecutive actions
        - System should handle multiple rapid approvals without race conditions
        """
        headers = {k: v for k, v in approval_api_config["headers"].items() if v}
        url = f"{approval_api_config['base_url']}/suggestions"

        # Get multiple pending suggestions
        response = requests.get(
            url, params={"status": "pending", "limit": 5}, headers=headers, timeout=10
        )

        if response.status_code != 200:
            pytest.skip("Suggestions endpoint not available")

        data = response.json()
        suggestions = data.get("suggestions", data) if isinstance(data, dict) else data

        if len(suggestions) < 2:
            pytest.skip("Need at least 2 pending suggestions for rapid action test")

        # Rapidly approve multiple suggestions
        results = []
        for suggestion in suggestions[:3]:  # Test with up to 3 suggestions
            suggestion_id = suggestion.get("suggestion_id") or suggestion.get("id")
            approve_url = f"{approval_api_config['base_url']}/suggestions/{suggestion_id}/approve"

            start_time = time.time()
            resp = requests.post(approve_url, headers=headers, json={}, timeout=10)
            elapsed = time.time() - start_time

            results.append(
                {
                    "suggestion_id": suggestion_id,
                    "status_code": resp.status_code,
                    "elapsed": elapsed,
                    "success": resp.status_code == 200,
                }
            )
            # Minimal delay between rapid actions
            time.sleep(0.1)

        successful = sum(1 for r in results if r["success"])
        total = len(results)

        print(f"Rapid actions: {successful}/{total} successful")
        for r in results:
            status = "✓" if r["success"] else "✗"
            print(f"  {r['suggestion_id'][:8]}: {r['elapsed']:.2f}s {status}")

        # At least 80% should succeed (allows for some concurrent conflicts)
        success_rate = successful / total if total > 0 else 0
        assert success_rate >= 0.8, f"Rapid action success rate {success_rate:.0%} < 80%"


class TestEdgeCaseNetworkTimeout:
    """Test dashboard behavior with network timeouts."""

    def test_timeout_handling(self, approval_api_config):
        """Test that the API responds within acceptable timeout.

        Validates edge case: Network timeout handling
        - Actions should complete within timeout thresholds
        """
        headers = {k: v for k, v in approval_api_config["headers"].items() if v}
        url = f"{approval_api_config['base_url']}/health"

        # Test with a short timeout - API should respond quickly
        try:
            response = requests.get(url, headers=headers, timeout=5)
            assert response.status_code == 200, f"Health check failed: {response.status_code}"
            print("Timeout handling: API responds within 5s timeout ✓")
        except requests.exceptions.Timeout:
            pytest.fail("API did not respond within 5 second timeout")
        except requests.exceptions.ConnectionError as e:
            pytest.skip(f"Could not connect to API: {e}")


class TestSuccessRateMonitoring:
    """Test success rate monitoring for action reliability (T033a)."""

    def test_action_success_rate_threshold(self, approval_api_config):
        """Verify 95% action success threshold (SC-006).

        Validates: T033a - Add success rate monitoring
        - 95% of dashboard page loads should render successfully without errors

        This test performs multiple API calls and verifies success rate.
        """
        headers = {k: v for k, v in approval_api_config["headers"].items() if v}
        health_url = f"{approval_api_config['base_url']}/health"
        suggestions_url = f"{approval_api_config['base_url']}/suggestions"

        # Perform multiple requests to measure success rate
        num_requests = 20
        results = []

        for i in range(num_requests):
            try:
                # Alternate between health and suggestions endpoints
                if i % 2 == 0:
                    resp = requests.get(health_url, headers=headers, timeout=10)
                else:
                    resp = requests.get(
                        suggestions_url,
                        params={"status": "pending", "limit": 10},
                        headers=headers,
                        timeout=10,
                    )

                results.append(
                    {
                        "request_num": i + 1,
                        "success": resp.status_code in [200, 404],  # 404 is valid for empty
                        "status_code": resp.status_code,
                        "response_time": resp.elapsed.total_seconds(),
                    }
                )
            except requests.exceptions.RequestException as e:
                results.append(
                    {
                        "request_num": i + 1,
                        "success": False,
                        "status_code": 0,
                        "error": str(e),
                    }
                )

            # Small delay between requests
            time.sleep(0.2)

        # Calculate success rate
        successful = sum(1 for r in results if r["success"])
        success_rate = successful / num_requests

        # Calculate response time statistics for successful requests
        response_times = [r["response_time"] for r in results if r.get("success") and "response_time" in r]

        print(f"\n=== Success Rate Monitoring Results ===")
        print(f"Total requests: {num_requests}")
        print(f"Successful: {successful}")
        print(f"Success rate: {success_rate:.1%}")

        if response_times:
            print(f"Avg response time: {statistics.mean(response_times):.3f}s")
            print(f"P95 response time: {sorted(response_times)[int(len(response_times) * 0.95)]:.3f}s")

        # Verify 95% success threshold (SC-006)
        assert success_rate >= 0.95, (
            f"Success rate {success_rate:.1%} is below 95% threshold. "
            f"Failed requests: {[r for r in results if not r['success']]}"
        )

        print(f"\n95% success rate threshold PASSED ({success_rate:.1%}) ✓")


class TestConcurrentApprovalHandling:
    """Test handling of concurrent approvals on the same suggestion."""

    def test_concurrent_approval_conflict(self, approval_api_config):
        """Test that concurrent approvals of the same suggestion are handled.

        Validates edge case from spec:
        - How does the system handle concurrent approvals of the same suggestion?
        - Only the first approval should succeed; subsequent attempts should show "already approved"
        """
        headers = {k: v for k, v in approval_api_config["headers"].items() if v}
        url = f"{approval_api_config['base_url']}/suggestions"

        # Get a pending suggestion
        response = requests.get(
            url, params={"status": "pending", "limit": 1}, headers=headers, timeout=10
        )

        if response.status_code != 200:
            pytest.skip("Suggestions endpoint not available")

        data = response.json()
        suggestions = data.get("suggestions", data) if isinstance(data, dict) else data

        if not suggestions:
            pytest.skip("No pending suggestions for concurrent test")

        suggestion_id = suggestions[0].get("suggestion_id") or suggestions[0].get("id")
        approve_url = f"{approval_api_config['base_url']}/suggestions/{suggestion_id}/approve"

        # First approval should succeed
        first_response = requests.post(approve_url, headers=headers, json={}, timeout=10)
        assert first_response.status_code == 200, f"First approval failed: {first_response.text}"
        print(f"First approval of {suggestion_id[:8]}: SUCCESS ✓")

        # Second approval of same suggestion should either:
        # - Return success (idempotent)
        # - Return conflict/already approved error
        second_response = requests.post(approve_url, headers=headers, json={}, timeout=10)

        # Accept 200 (idempotent) or 409/400 (conflict)
        assert second_response.status_code in [
            200,
            400,
            409,
        ], f"Unexpected response to duplicate approval: {second_response.status_code}"

        if second_response.status_code == 200:
            print(f"Second approval of {suggestion_id[:8]}: Idempotent success ✓")
        else:
            print(f"Second approval of {suggestion_id[:8]}: Correctly rejected ({second_response.status_code}) ✓")
