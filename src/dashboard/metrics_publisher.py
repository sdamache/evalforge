"""Metrics Publisher Cloud Function.

Entry point for the Cloud Function that aggregates suggestion counts
from Firestore and publishes metrics to Datadog every 60 seconds.

Deploy with:
    gcloud functions deploy evalforge-metrics-publisher \
        --runtime python311 \
        --trigger-http \
        --entry-point publish_metrics \
        --source src/dashboard/ \
        --set-secrets DATADOG_API_KEY=DATADOG_API_KEY:latest

Trigger with Cloud Scheduler:
    gcloud scheduler jobs create http evalforge-metrics-job \
        --schedule="* * * * *" \
        --uri="<function-url>" \
        --http-method=POST
"""

import logging
import time
from typing import Any

import functions_framework
from flask import Request, jsonify

from dashboard.config import load_dashboard_config, DashboardConfigError
from dashboard.datadog_client import DatadogMetricsClient, DatadogClientError
from dashboard.aggregator import aggregate_suggestion_counts, AggregationError

# Configure logging for Cloud Functions
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@functions_framework.http
def publish_metrics(request: Request) -> tuple[dict[str, Any], int]:
    """Cloud Function entry point for metrics publishing.

    Aggregates suggestion counts from Firestore and submits metrics
    to Datadog's Metrics API.

    Args:
        request: HTTP request from Cloud Scheduler or manual trigger.

    Returns:
        Tuple of (response_dict, status_code).
        - 200: Metrics published successfully
        - 500: Error during aggregation or submission
    """
    start_time = time.time()

    logger.info("Metrics publisher triggered")

    try:
        # Load configuration
        config = load_dashboard_config()
        logger.info(
            "Configuration loaded",
            extra={
                "datadog_site": config.datadog_site,
                "firestore_project": config.firestore_project_id,
                "firestore_collection": config.firestore_collection,
            },
        )

        # Aggregate counts from Firestore
        counts = aggregate_suggestion_counts(config)
        logger.info(
            "Aggregation complete",
            extra={
                "pending": counts.pending,
                "approved": counts.approved,
                "rejected": counts.rejected,
                "total": counts.total,
            },
        )

        # Submit to Datadog
        client = DatadogMetricsClient(config)
        client.submit_suggestion_metrics(counts)

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Metrics published successfully",
            extra={"elapsed_ms": elapsed_ms},
        )

        return jsonify({
            "status": "success",
            "message": "Metrics published to Datadog",
            "counts": {
                "pending": counts.pending,
                "approved": counts.approved,
                "rejected": counts.rejected,
                "total": counts.total,
            },
            "elapsed_ms": round(elapsed_ms, 2),
        }), 200

    except DashboardConfigError as e:
        logger.error(f"Configuration error: {e}")
        return jsonify({
            "status": "error",
            "error": "Configuration error",
            "message": str(e),
        }), 500

    except AggregationError as e:
        logger.error(f"Aggregation error: {e}")
        return jsonify({
            "status": "error",
            "error": "Aggregation error",
            "message": str(e),
        }), 500

    except DatadogClientError as e:
        logger.error(f"Datadog submission error: {e}")
        return jsonify({
            "status": "error",
            "error": "Datadog error",
            "message": str(e),
        }), 500

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return jsonify({
            "status": "error",
            "error": "Unexpected error",
            "message": str(e),
        }), 500


def aggregate_and_publish() -> dict[str, Any]:
    """Standalone function for local testing.

    Can be called directly without HTTP context for testing:
        python -c "from dashboard.metrics_publisher import aggregate_and_publish; print(aggregate_and_publish())"
    """
    config = load_dashboard_config()
    counts = aggregate_suggestion_counts(config)
    client = DatadogMetricsClient(config)
    client.submit_suggestion_metrics(counts)

    return {
        "pending": counts.pending,
        "approved": counts.approved,
        "rejected": counts.rejected,
        "total": counts.total,
    }
