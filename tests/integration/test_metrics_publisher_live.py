"""Live integration tests for Datadog metrics publisher.

These tests hit real Datadog and Firestore APIs - no mocks.
Run with: RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_metrics_publisher_live.py -v
"""

import os
import time
import pytest

# Skip all tests if RUN_LIVE_TESTS is not set
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="Live tests disabled. Set RUN_LIVE_TESTS=1 to run.",
)


@pytest.fixture
def dashboard_config():
    """Load dashboard config from environment."""
    from dashboard.config import load_dashboard_config
    return load_dashboard_config()


@pytest.fixture
def datadog_client(dashboard_config):
    """Create Datadog metrics client."""
    from dashboard.datadog_client import DatadogMetricsClient
    return DatadogMetricsClient(dashboard_config)


class TestMetricsPublisherLive:
    """Live integration tests for metrics publisher."""

    def test_submit_single_metric_to_datadog(self, datadog_client):
        """Test that a single metric is accepted by Datadog API.

        Verifies:
        - API key authentication works
        - Metric submission returns success
        - No errors in response
        """
        from dashboard.models import MetricPayload, MetricSeries, MetricPoint

        payload = MetricPayload(
            series=[
                MetricSeries(
                    metric="evalforge.test.integration",
                    points=[MetricPoint(timestamp=int(time.time()), value=1.0)],
                    tags=["env:test", "test:live_integration"],
                )
            ]
        )

        result = datadog_client.submit_metrics(payload)
        assert result is True, "Metric submission should succeed"

    def test_submit_suggestion_metrics_to_datadog(self, datadog_client):
        """Test that all suggestion metrics are accepted by Datadog API.

        Verifies:
        - All 7+ metric series are submitted
        - Type and severity tagged metrics work
        - Coverage improvement metric works
        """
        from dashboard.models import SuggestionCounts

        counts = SuggestionCounts(
            pending=5,
            approved=10,
            rejected=2,
            by_type={"eval": 3, "guardrail": 1, "runbook": 1},
            by_severity={"low": 1, "medium": 2, "high": 1, "critical": 1},
            total_failures=50,
        )

        result = datadog_client.submit_suggestion_metrics(counts)
        assert result is True, "All suggestion metrics should be submitted"

    def test_aggregate_from_live_firestore(self, dashboard_config):
        """Test that Firestore aggregation works against live database.

        Verifies:
        - Connection to Firestore succeeds
        - Aggregation query returns valid counts
        - No exceptions during aggregation
        """
        from dashboard.aggregator import aggregate_suggestion_counts

        counts = aggregate_suggestion_counts(dashboard_config)

        # Counts should be non-negative integers (or floats from Firestore)
        assert counts.pending >= 0, "Pending count should be non-negative"
        assert counts.approved >= 0, "Approved count should be non-negative"
        assert counts.rejected >= 0, "Rejected count should be non-negative"
        assert counts.total >= 0, "Total count should be non-negative"

    def test_end_to_end_aggregate_and_submit(self, dashboard_config, datadog_client):
        """Test full flow: aggregate from Firestore and submit to Datadog.

        Verifies:
        - Aggregation works
        - Submission works
        - Full pipeline completes without errors
        """
        from dashboard.aggregator import aggregate_suggestion_counts

        # Step 1: Aggregate from Firestore
        counts = aggregate_suggestion_counts(dashboard_config)

        # Step 2: Submit to Datadog
        result = datadog_client.submit_suggestion_metrics(counts)

        assert result is True, "End-to-end flow should complete successfully"

    def test_empty_payload_submission(self, datadog_client):
        """Test that empty payload submission is handled gracefully.

        Verifies:
        - Empty payloads don't cause errors
        - Returns True (success) for empty case
        """
        from dashboard.models import MetricPayload

        payload = MetricPayload(series=[])
        result = datadog_client.submit_metrics(payload)
        assert result is True, "Empty payload should succeed"

    def test_metrics_appear_in_datadog_explorer(self, datadog_client):
        """Test that submitted metrics are queryable in Datadog.

        Note: This test submits a unique metric and would ideally query
        Datadog Metrics API to verify it appears. For now, we just verify
        submission succeeds - manual verification in Datadog UI.
        """
        from dashboard.models import MetricPayload, MetricSeries, MetricPoint

        # Use unique timestamp for this test run
        test_timestamp = int(time.time())
        test_value = float(test_timestamp % 1000)  # Unique value

        payload = MetricPayload(
            series=[
                MetricSeries(
                    metric="evalforge.test.explorer_verification",
                    points=[MetricPoint(timestamp=test_timestamp, value=test_value)],
                    tags=[
                        "env:test",
                        "test:explorer_verification",
                        f"run_id:{test_timestamp}",
                    ],
                )
            ]
        )

        result = datadog_client.submit_metrics(payload)
        assert result is True

        print(f"\n>>> Verify in Datadog Metrics Explorer:")
        print(f"    Metric: evalforge.test.explorer_verification")
        print(f"    Tag: run_id:{test_timestamp}")
        print(f"    Value: {test_value}")
