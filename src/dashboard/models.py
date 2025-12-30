"""Data models for Datadog metrics publishing.

Defines dataclasses for building metrics payloads that conform to
Datadog's Metrics API v2 format.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class SuggestionType(str, Enum):
    """Types of EvalForge suggestions."""
    EVAL = "eval"
    GUARDRAIL = "guardrail"
    RUNBOOK = "runbook"


class SuggestionStatus(str, Enum):
    """Status of suggestions in the approval workflow."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Severity(str, Enum):
    """Severity levels for suggestions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class MetricPoint:
    """Single data point for a metric.

    Attributes:
        timestamp: Unix timestamp in seconds.
        value: Metric value (float).
    """
    timestamp: int
    value: float


@dataclass
class MetricSeries:
    """Single metric series for Datadog.

    Attributes:
        metric: Metric name (e.g., evalforge.suggestions.pending).
        points: List of data points (typically one for gauges).
        tags: List of tags (e.g., ["env:production", "type:eval"]).
        type: Metric type (3 = gauge for Datadog API v2).
    """
    metric: str
    points: list[MetricPoint]
    tags: list[str] = field(default_factory=list)
    type: int = 3  # Gauge type for Datadog API v2


@dataclass
class MetricPayload:
    """Payload for submitting metrics to Datadog API v2.

    Attributes:
        series: List of metric series to submit.
    """
    series: list[MetricSeries]


@dataclass
class SuggestionCounts:
    """Aggregated counts of suggestions from Firestore.

    Attributes:
        pending: Count of pending suggestions.
        approved: Count of approved suggestions.
        rejected: Count of rejected suggestions.
        by_type: Count of pending suggestions by type.
        by_severity: Count of pending suggestions by severity.
        approved_by_type: Count of approved suggestions by type (for coverage calc).
        total_failures: Total number of failures (for coverage calculation).
    """
    pending: int = 0
    approved: int = 0
    rejected: int = 0
    by_type: dict[str, int] = field(default_factory=lambda: {
        SuggestionType.EVAL.value: 0,
        SuggestionType.GUARDRAIL.value: 0,
        SuggestionType.RUNBOOK.value: 0,
    })
    by_severity: dict[str, int] = field(default_factory=lambda: {
        Severity.LOW.value: 0,
        Severity.MEDIUM.value: 0,
        Severity.HIGH.value: 0,
        Severity.CRITICAL.value: 0,
    })
    approved_by_type: dict[str, int] = field(default_factory=lambda: {
        SuggestionType.EVAL.value: 0,
        SuggestionType.GUARDRAIL.value: 0,
        SuggestionType.RUNBOOK.value: 0,
    })
    total_failures: int = 0

    @property
    def total(self) -> int:
        """Total count of all suggestions."""
        return self.pending + self.approved + self.rejected

    @property
    def coverage_improvement(self) -> float:
        """Calculate coverage improvement percentage.

        Returns:
            Percentage of failures with approved eval coverage (0-100).
            Returns 0 if no failures exist.
        """
        if self.total_failures == 0:
            return 0.0
        # Only count APPROVED evals (not pending, not guardrails or runbooks)
        approved_evals = self.approved_by_type.get(SuggestionType.EVAL.value, 0)
        return (approved_evals / self.total_failures) * 100
