"""Dashboard module for Datadog integration.

Provides metrics publishing to Datadog for EvalForge suggestion monitoring.
The metrics publisher runs as a Cloud Function triggered every 60 seconds,
pushing aggregated suggestion counts to Datadog's Metrics API.

Exports:
    - DashboardConfig: Configuration for Datadog dashboard integration
    - DatadogMetricsClient: Client for submitting metrics to Datadog API
    - MetricPayload, MetricSeries, MetricPoint: Metric data structures
    - aggregate_suggestion_counts: Firestore aggregation for suggestion metrics
    - build_metrics_payload: Build Datadog-compatible metrics payload
    - publish_metrics: Cloud Function entry point
"""

from dashboard.config import DashboardConfig, load_dashboard_config

__all__ = [
    "DashboardConfig",
    "load_dashboard_config",
]
