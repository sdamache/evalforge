"""Firestore aggregation for suggestion metrics.

Queries the evalforge_suggestions collection to count suggestions
by status, type, and severity for dashboard metrics.
"""

import logging
from typing import Optional

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from dashboard.config import DashboardConfig
from dashboard.models import SuggestionCounts, SuggestionType, SuggestionStatus, Severity

logger = logging.getLogger(__name__)


class AggregationError(Exception):
    """Raised when Firestore aggregation fails."""


def aggregate_suggestion_counts(
    config: DashboardConfig,
    db: Optional[firestore.Client] = None,
) -> SuggestionCounts:
    """Aggregate suggestion counts from Firestore.

    Queries the suggestions collection and counts documents by:
    - Status (pending, approved, rejected)
    - Type (eval, guardrail, runbook) - for pending only
    - Severity (low, medium, high, critical) - for pending only

    Args:
        config: Dashboard configuration with Firestore settings.
        db: Optional Firestore client (for testing). If None, creates new client.

    Returns:
        SuggestionCounts with aggregated counts.

    Raises:
        AggregationError: If Firestore query fails.
    """
    if db is None:
        db = firestore.Client(
            project=config.firestore_project_id,
            database=config.firestore_database_id,
        )

    collection_ref = db.collection(config.firestore_collection)

    logger.info(
        "Starting suggestion count aggregation",
        extra={
            "collection": config.firestore_collection,
            "project": config.firestore_project_id,
        },
    )

    try:
        counts = SuggestionCounts()

        # Count by status using Firestore aggregation queries
        for status in SuggestionStatus:
            query = collection_ref.where(filter=FieldFilter("status", "==", status.value))
            # Use count aggregation for efficiency
            count_result = query.count().get()
            count_value = count_result[0][0].value if count_result else 0

            if status == SuggestionStatus.PENDING:
                counts.pending = count_value
            elif status == SuggestionStatus.APPROVED:
                counts.approved = count_value
            elif status == SuggestionStatus.REJECTED:
                counts.rejected = count_value

        # For pending suggestions, get type and severity breakdown
        # Need to iterate through documents for this breakdown
        pending_query = collection_ref.where(filter=FieldFilter("status", "==", SuggestionStatus.PENDING.value))
        pending_docs = pending_query.stream()

        type_counts = {t.value: 0 for t in SuggestionType}
        severity_counts = {s.value: 0 for s in Severity}

        for doc in pending_docs:
            data = doc.to_dict()
            suggestion_type = data.get("type", SuggestionType.EVAL.value)
            severity = data.get("severity", Severity.MEDIUM.value)

            if suggestion_type in type_counts:
                type_counts[suggestion_type] += 1
            if severity in severity_counts:
                severity_counts[severity] += 1

        counts.by_type = type_counts
        counts.by_severity = severity_counts

        # Get total failures count from failure_patterns collection for coverage calculation
        # This is the denominator for coverage improvement percentage
        try:
            failures_collection = db.collection("evalforge_failure_patterns")
            failures_count_result = failures_collection.count().get()
            counts.total_failures = failures_count_result[0][0].value if failures_count_result else 0
        except Exception as e:
            logger.warning(
                "Could not count total failures, using 0",
                extra={"error": str(e)},
            )
            counts.total_failures = 0

        logger.info(
            "Aggregation complete",
            extra={
                "pending": counts.pending,
                "approved": counts.approved,
                "rejected": counts.rejected,
                "total": counts.total,
                "by_type": counts.by_type,
                "by_severity": counts.by_severity,
                "total_failures": counts.total_failures,
            },
        )

        return counts

    except Exception as e:
        logger.error(
            "Firestore aggregation failed",
            extra={"error": str(e), "error_type": type(e).__name__},
        )
        raise AggregationError(f"Failed to aggregate suggestions: {e}") from e
