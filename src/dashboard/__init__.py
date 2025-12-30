"""Dashboard module for Datadog integration.

Provides metrics publishing to Datadog for EvalForge suggestion monitoring.
The metrics publisher runs as a Cloud Function triggered every 60 seconds,
pushing aggregated suggestion counts to Datadog's Metrics API.

Exports:
    - DashboardConfig: Configuration for Datadog dashboard integration
    - DatadogMetricsClient: Client for submitting metrics to Datadog API
    - MetricPayload, MetricSeries, MetricPoint: Metric data structures
    - SuggestionCounts: Aggregated counts from Firestore
    - aggregate_suggestion_counts: Firestore aggregation for suggestion metrics
"""

from dashboard.config import DashboardConfig, load_dashboard_config
from dashboard.models import (
    MetricPayload,
    MetricSeries,
    MetricPoint,
    SuggestionCounts,
    SuggestionType,
    SuggestionStatus,
    Severity,
)
from dashboard.datadog_client import DatadogMetricsClient, DatadogClientError
from dashboard.aggregator import aggregate_suggestion_counts, AggregationError

__all__ = [
    # Config
    "DashboardConfig",
    "load_dashboard_config",
    # Models
    "MetricPayload",
    "MetricSeries",
    "MetricPoint",
    "SuggestionCounts",
    "SuggestionType",
    "SuggestionStatus",
    "Severity",
    # Client
    "DatadogMetricsClient",
    "DatadogClientError",
    # Aggregator
    "aggregate_suggestion_counts",
    "AggregationError",
]
