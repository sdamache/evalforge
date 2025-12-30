# Data Model: Datadog Dashboard Integration

**Feature Branch**: `007-datadog-dashboard`
**Created**: 2025-12-29

## Overview

This feature primarily reads from existing Firestore collections and writes to Datadog's Metrics API. No new persistent entities are created; instead, we define metrics and transformations.

## Source Entity: Suggestion (Read-Only)

**Collection**: `evalforge_suggestions`
**Managed By**: Issue #3 (Suggestion Storage) and Issue #8 (Approval Workflow API)

```python
@dataclass
class Suggestion:
    """Existing entity - read-only for this feature."""
    suggestion_id: str           # Primary key (e.g., "sugg_xyz789")
    type: SuggestionType         # eval | guardrail | runbook
    status: SuggestionStatus     # pending | approved | rejected
    severity: Severity           # low | medium | high | critical
    created_at: datetime         # When suggestion was generated
    updated_at: datetime         # Last status change
    source_traces: list[str]     # Originating trace IDs
    pattern: dict                # Failure pattern details
    suggestion_content: dict     # Generated eval/guardrail/runbook content
```

### Enums

```python
class SuggestionType(str, Enum):
    EVAL = "eval"
    GUARDRAIL = "guardrail"
    RUNBOOK = "runbook"

class SuggestionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
```

## Datadog Metrics (Output)

### Metric Definitions

| Metric Name | Type | Tags | Description |
|-------------|------|------|-------------|
| `evalforge.suggestions.pending` | gauge | - | Count of pending suggestions |
| `evalforge.suggestions.approved` | gauge | - | Count of approved suggestions |
| `evalforge.suggestions.rejected` | gauge | - | Count of rejected suggestions |
| `evalforge.suggestions.total` | gauge | - | Total count of all suggestions |
| `evalforge.suggestions.by_type` | gauge | `type:{eval\|guardrail\|runbook}` | Count grouped by suggestion type |
| `evalforge.suggestions.by_severity` | gauge | `severity:{low\|medium\|high\|critical}` | Count grouped by severity |
| `evalforge.coverage.improvement` | gauge | - | Percentage: approved evals / total failures |

### Metric Payload Structure

```python
@dataclass
class MetricPayload:
    """Payload for Datadog Metrics API v2."""
    series: list[MetricSeries]

@dataclass
class MetricSeries:
    """Single metric series."""
    metric: str              # e.g., "evalforge.suggestions.pending"
    type: int                # 3 = gauge
    points: list[MetricPoint]
    tags: list[str]          # e.g., ["type:eval", "env:production"]

@dataclass
class MetricPoint:
    """Single data point."""
    timestamp: int           # Unix timestamp (seconds)
    value: float             # Metric value
```

### Example Payload

```json
{
  "series": [
    {
      "metric": "evalforge.suggestions.pending",
      "type": 3,
      "points": [
        {"timestamp": 1735489200, "value": 12}
      ],
      "tags": ["env:production", "service:evalforge"]
    },
    {
      "metric": "evalforge.suggestions.by_type",
      "type": 3,
      "points": [
        {"timestamp": 1735489200, "value": 5}
      ],
      "tags": ["type:eval", "env:production"]
    },
    {
      "metric": "evalforge.suggestions.by_type",
      "type": 3,
      "points": [
        {"timestamp": 1735489200, "value": 4}
      ],
      "tags": ["type:guardrail", "env:production"]
    },
    {
      "metric": "evalforge.suggestions.by_type",
      "type": 3,
      "points": [
        {"timestamp": 1735489200, "value": 3}
      ],
      "tags": ["type:runbook", "env:production"]
    }
  ]
}
```

## Aggregation Queries

### Firestore Queries for Metrics Publisher

```python
def get_suggestion_counts(db: firestore.Client) -> dict:
    """Aggregate suggestion counts for metrics."""
    collection = db.collection("evalforge_suggestions")

    counts = {
        "pending": 0,
        "approved": 0,
        "rejected": 0,
        "by_type": {"eval": 0, "guardrail": 0, "runbook": 0},
        "by_severity": {"low": 0, "medium": 0, "high": 0, "critical": 0},
    }

    # Count by status
    for status in ["pending", "approved", "rejected"]:
        query = collection.where("status", "==", status)
        counts[status] = len(list(query.stream()))

    # Count by type (pending only for actionable queue)
    pending_query = collection.where("status", "==", "pending")
    for doc in pending_query.stream():
        data = doc.to_dict()
        suggestion_type = data.get("type", "eval")
        severity = data.get("severity", "medium")
        counts["by_type"][suggestion_type] += 1
        counts["by_severity"][severity] += 1

    return counts
```

## App Builder Data Requirements

### Table Component Data Source

The App Builder table component needs to fetch suggestion details directly from the Approval API (Issue #8):

```
GET /suggestions?status=pending&limit=100&sort=severity,created_at
```

**Response Fields Used**:

| Field | Column Header | Format |
|-------|---------------|--------|
| `suggestion_id` | ID | String (truncated to 8 chars) |
| `type` | Type | Status pill (eval=blue, guardrail=orange, runbook=green) |
| `severity` | Severity | Status pill (critical=red, high=orange, medium=yellow, low=gray) |
| `created_at` | Age | Relative time (e.g., "2h ago") |
| - | Actions | Approve/Reject buttons |

### Button Actions

| Button | HTTP Method | Endpoint | Body |
|--------|-------------|----------|------|
| Approve | POST | `/suggestions/{id}/approve` | `{}` |
| Reject | POST | `/suggestions/{id}/reject` | `{"reason": "optional"}` |

## State Transitions

```
                  ┌─────────────┐
                  │             │
    ┌─────────────▶   pending   ◀─────────────┐
    │             │             │             │
    │             └──────┬──────┘             │
    │                    │                    │
    │         ┌──────────┴──────────┐         │
    │         │                     │         │
    │         ▼                     ▼         │
    │   ┌───────────┐         ┌───────────┐   │
    │   │           │         │           │   │
    └───│ approved  │         │ rejected  │───┘
        │           │         │           │
        └───────────┘         └───────────┘
              │                     │
              │                     │
              ▼                     ▼
        [FINAL STATE]         [FINAL STATE]
```

**Note**: State transitions are managed by Issue #8 Approval Workflow API. This feature only reads current state.

## Indexes

### Required Firestore Indexes

```yaml
# Already created by Issue #3 and #8
indexes:
  - collection: evalforge_suggestions
    fields:
      - field: status
        order: ASCENDING
      - field: severity
        order: DESCENDING
      - field: created_at
        order: ASCENDING
```

## Data Volume Assumptions

| Metric | Expected Value | Impact |
|--------|----------------|--------|
| Total suggestions | <1000 | Single query sufficient |
| New suggestions/day | 10-50 | 60s polling is adequate |
| Approval rate | ~80% | Most suggestions approved |
| Peak concurrent users | 1-5 | No scaling concerns |
