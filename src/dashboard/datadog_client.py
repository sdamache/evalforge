"""Datadog API client for metrics submission.

Wraps the datadog-api-client library to submit EvalForge metrics
to Datadog's Metrics API v2.
"""

import time
import logging
from typing import Optional

from datadog_api_client import ApiClient, Configuration
from datadog_api_client.v2.api.metrics_api import MetricsApi
from datadog_api_client.v2.model.metric_intake_type import MetricIntakeType
from datadog_api_client.v2.model.metric_payload import MetricPayload as DDMetricPayload
from datadog_api_client.v2.model.metric_point import MetricPoint as DDMetricPoint
from datadog_api_client.v2.model.metric_series import MetricSeries as DDMetricSeries

from dashboard.config import DashboardConfig
from dashboard.models import MetricPayload, SuggestionCounts

# Structured logging setup
logger = logging.getLogger(__name__)


class DatadogClientError(Exception):
    """Raised when Datadog API operations fail."""


class DatadogMetricsClient:
    """Client for submitting metrics to Datadog API v2.

    Attributes:
        config: Dashboard configuration with Datadog credentials.
    """

    def __init__(self, config: DashboardConfig):
        """Initialize the Datadog client.

        Args:
            config: Dashboard configuration with API credentials.
        """
        self.config = config
        self._configuration = Configuration()
        self._configuration.api_key["apiKeyAuth"] = config.datadog_api_key
        self._configuration.server_variables["site"] = config.datadog_site

        logger.info(
            "DatadogMetricsClient initialized",
            extra={
                "datadog_site": config.datadog_site,
                "environment": config.environment,
                "service": config.service_name,
            },
        )

    def _get_base_tags(self) -> list[str]:
        """Get base tags applied to all metrics."""
        return [
            f"env:{self.config.environment}",
            f"service:{self.config.service_name}",
        ]

    def submit_metrics(self, payload: MetricPayload) -> bool:
        """Submit metrics to Datadog API.

        Args:
            payload: MetricPayload with series to submit.

        Returns:
            True if submission succeeded, False otherwise.

        Raises:
            DatadogClientError: If API call fails.
        """
        if not payload.series:
            logger.warning("No metrics to submit - empty payload")
            return True

        # Convert our models to Datadog SDK models
        dd_series = []
        for series in payload.series:
            dd_points = [
                DDMetricPoint(timestamp=p.timestamp, value=p.value)
                for p in series.points
            ]
            dd_series.append(
                DDMetricSeries(
                    metric=series.metric,
                    type=MetricIntakeType.GAUGE,
                    points=dd_points,
                    tags=series.tags,
                )
            )

        dd_payload = DDMetricPayload(series=dd_series)

        logger.info(
            "Submitting metrics to Datadog",
            extra={
                "metric_count": len(dd_series),
                "metrics": [s.metric for s in payload.series],
            },
        )

        try:
            with ApiClient(self._configuration) as api_client:
                api = MetricsApi(api_client)
                response = api.submit_metrics(body=dd_payload)

                if response.errors:
                    logger.error(
                        "Datadog API returned errors",
                        extra={"errors": response.errors},
                    )
                    raise DatadogClientError(f"Datadog API errors: {response.errors}")

                logger.info(
                    "Metrics submitted successfully",
                    extra={"metric_count": len(dd_series)},
                )
                return True

        except Exception as e:
            logger.error(
                "Failed to submit metrics to Datadog",
                extra={"error": str(e), "error_type": type(e).__name__},
            )
            raise DatadogClientError(f"Failed to submit metrics: {e}") from e

    def submit_suggestion_metrics(self, counts: SuggestionCounts) -> bool:
        """Submit suggestion count metrics to Datadog.

        Builds and submits all EvalForge suggestion metrics based on
        aggregated counts from Firestore.

        Args:
            counts: Aggregated suggestion counts.

        Returns:
            True if submission succeeded.
        """
        timestamp = int(time.time())
        base_tags = self._get_base_tags()
        series = []

        # Status count metrics
        for status, value in [
            ("pending", counts.pending),
            ("approved", counts.approved),
            ("rejected", counts.rejected),
        ]:
            from dashboard.models import MetricSeries, MetricPoint

            series.append(
                MetricSeries(
                    metric=f"evalforge.suggestions.{status}",
                    points=[MetricPoint(timestamp=timestamp, value=float(value))],
                    tags=base_tags,
                )
            )

        # Total metric
        series.append(
            MetricSeries(
                metric="evalforge.suggestions.total",
                points=[MetricPoint(timestamp=timestamp, value=float(counts.total))],
                tags=base_tags,
            )
        )

        # By type metrics (for pending suggestions)
        for suggestion_type, count in counts.by_type.items():
            series.append(
                MetricSeries(
                    metric="evalforge.suggestions.by_type",
                    points=[MetricPoint(timestamp=timestamp, value=float(count))],
                    tags=base_tags + [f"type:{suggestion_type}"],
                )
            )

        # By severity metrics (for pending suggestions)
        for severity, count in counts.by_severity.items():
            series.append(
                MetricSeries(
                    metric="evalforge.suggestions.by_severity",
                    points=[MetricPoint(timestamp=timestamp, value=float(count))],
                    tags=base_tags + [f"severity:{severity}"],
                )
            )

        # Coverage improvement metric
        series.append(
            MetricSeries(
                metric="evalforge.coverage.improvement",
                points=[
                    MetricPoint(timestamp=timestamp, value=counts.coverage_improvement)
                ],
                tags=base_tags,
            )
        )

        logger.info(
            "Built suggestion metrics payload",
            extra={
                "pending": counts.pending,
                "approved": counts.approved,
                "rejected": counts.rejected,
                "total_series": len(series),
            },
        )

        payload = MetricPayload(series=series)
        return self.submit_metrics(payload)
