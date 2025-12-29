# Data Model: Suggestion Storage and Deduplication

**Branch**: `003-suggestion-deduplication` | **Date**: 2025-12-28

## Entity Overview

```
┌─────────────────────┐         ┌──────────────────────┐
│   FailurePattern    │ 1    n  │     Suggestion       │
│   (from Issue #2)   │─────────│                      │
│                     │         │  - source_traces[]   │
│  - pattern_id       │         │  - embedding[]       │
│  - failure_type     │         │  - status            │
│  - trigger_condition│         │  - version_history[] │
└─────────────────────┘         └──────────────────────┘
                                         │
                                         │ 1
                                         │
                                         ▼ n
                                ┌──────────────────────┐
                                │  StatusHistoryEntry  │
                                │                      │
                                │  - previous_status   │
                                │  - new_status        │
                                │  - actor             │
                                │  - timestamp         │
                                └──────────────────────┘
```

## Entities

### Suggestion

**Collection**: `evalforge_suggestions`
**Document ID**: `suggestion_id` (auto-generated UUID)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `suggestion_id` | string | Yes | Unique identifier (format: `sugg_{uuid}`) |
| `type` | enum | Yes | One of: `eval`, `guardrail`, `runbook` |
| `status` | enum | Yes | One of: `pending`, `approved`, `rejected` |
| `severity` | enum | Yes | One of: `low`, `medium`, `high`, `critical` |
| `source_traces` | array[SourceTraceEntry] | Yes | Contributing trace IDs with timestamps |
| `pattern` | PatternSummary | Yes | Consolidated pattern info |
| `embedding` | array[float] | Yes | 768-dimensional embedding vector |
| `similarity_group` | string | Yes | Group ID for merged patterns |
| `suggestion_content` | SuggestionContent | No | Generated artifacts (populated by future issues) |
| `approval_metadata` | ApprovalMetadata | No | Set when approved/rejected |
| `version_history` | array[StatusHistoryEntry] | Yes | Audit trail of status changes |
| `created_at` | timestamp | Yes | First creation timestamp (UTC) |
| `updated_at` | timestamp | Yes | Last modification timestamp (UTC) |

**State Transitions**:
```
    ┌─────────────────────────────┐
    │                             │
    ▼                             │
┌────────┐   approve   ┌──────────┴───┐
│pending │────────────►│   approved   │
└────────┘             └──────────────┘
    │
    │ reject
    ▼
┌──────────┐
│ rejected │
└──────────┘
```

**Validation Rules**:
- `suggestion_id` must be unique across collection
- `source_traces` must have at least one entry
- `embedding` must have exactly 768 elements
- `status` can only transition: `pending` → `approved` OR `pending` → `rejected`
- `version_history` must have at least one entry (initial creation)

### SourceTraceEntry

**Embedded in**: `Suggestion.source_traces`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `trace_id` | string | Yes | Reference to original Datadog trace |
| `pattern_id` | string | Yes | Reference to extracted FailurePattern |
| `added_at` | timestamp | Yes | When this trace was merged in |
| `similarity_score` | float | No | Similarity score when merged (null for first trace) |

### PatternSummary

**Embedded in**: `Suggestion.pattern`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `failure_type` | enum | Yes | From FailureType enum |
| `trigger_condition` | string | Yes | Primary trigger description |
| `title` | string | Yes | Concise pattern title |
| `summary` | string | Yes | 1-2 sentence description |

### SuggestionContent

**Embedded in**: `Suggestion.suggestion_content`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `eval_test` | object | No | Generated eval test case (Issue #4) |
| `guardrail_rule` | object | No | Generated guardrail config (Issue #5) |
| `runbook_snippet` | object | No | Generated runbook content (Issue #6) |

*Note: This field is populated by downstream generator services (Issues #4-6), not by the deduplication service.*

### ApprovalMetadata

**Embedded in**: `Suggestion.approval_metadata`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `actor` | string | Yes | Who approved/rejected (email or API key ID) |
| `action` | enum | Yes | One of: `approved`, `rejected` |
| `notes` | string | No | Optional reviewer notes |
| `timestamp` | timestamp | Yes | When action was taken |

### StatusHistoryEntry

**Embedded in**: `Suggestion.version_history`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `previous_status` | enum | No | Previous status (null for creation) |
| `new_status` | enum | Yes | New status after transition |
| `actor` | string | Yes | Who made the change |
| `timestamp` | timestamp | Yes | When change occurred |
| `notes` | string | No | Optional notes/reason |

## Enums

### SuggestionType

```python
class SuggestionType(str, Enum):
    EVAL = "eval"
    GUARDRAIL = "guardrail"
    RUNBOOK = "runbook"
```

### SuggestionStatus

```python
class SuggestionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
```

### Severity (reuse from extraction)

```python
class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
```

### FailureType (reuse from extraction)

```python
class FailureType(str, Enum):
    HALLUCINATION = "hallucination"
    TOXICITY = "toxicity"
    WRONG_TOOL = "wrong_tool"
    RUNAWAY_LOOP = "runaway_loop"
    PII_LEAK = "pii_leak"
    STALE_DATA = "stale_data"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    CLIENT_ERROR = "client_error"
```

## Firestore Indexes

```json
{
  "indexes": [
    {
      "collectionGroup": "evalforge_suggestions",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "status", "order": "ASCENDING"},
        {"fieldPath": "type", "order": "ASCENDING"},
        {"fieldPath": "created_at", "order": "DESCENDING"}
      ]
    },
    {
      "collectionGroup": "evalforge_suggestions",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "status", "order": "ASCENDING"},
        {"fieldPath": "severity", "order": "DESCENDING"}
      ]
    },
    {
      "collectionGroup": "evalforge_suggestions",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "status", "order": "ASCENDING"},
        {"fieldPath": "created_at", "order": "DESCENDING"}
      ]
    }
  ]
}
```

## Sample Documents

### Suggestion (Pending)

```json
{
  "suggestion_id": "sugg_abc123",
  "type": "eval",
  "status": "pending",
  "severity": "medium",
  "source_traces": [
    {
      "trace_id": "dd_trace_12345",
      "pattern_id": "pattern_dd_trace_12345",
      "added_at": "2025-01-05T12:00:00Z",
      "similarity_score": null
    },
    {
      "trace_id": "dd_trace_67890",
      "pattern_id": "pattern_dd_trace_67890",
      "added_at": "2025-01-05T12:30:00Z",
      "similarity_score": 0.92
    }
  ],
  "pattern": {
    "failure_type": "stale_data",
    "trigger_condition": "Product recommendation without inventory check",
    "title": "Stale Product Recommendations",
    "summary": "Agent recommended discontinued product SKU-9876 because inventory check was not performed before responding."
  },
  "embedding": [0.123, 0.456, ...],
  "similarity_group": "group_xyz789",
  "suggestion_content": null,
  "approval_metadata": null,
  "version_history": [
    {
      "previous_status": null,
      "new_status": "pending",
      "actor": "system",
      "timestamp": "2025-01-05T12:00:00Z",
      "notes": "Created from pattern_dd_trace_12345"
    }
  ],
  "created_at": "2025-01-05T12:00:00Z",
  "updated_at": "2025-01-05T12:30:00Z"
}
```

### Suggestion (Approved)

```json
{
  "suggestion_id": "sugg_def456",
  "type": "guardrail",
  "status": "approved",
  "severity": "high",
  "source_traces": [
    {
      "trace_id": "dd_trace_11111",
      "pattern_id": "pattern_dd_trace_11111",
      "added_at": "2025-01-04T10:00:00Z",
      "similarity_score": null
    }
  ],
  "pattern": {
    "failure_type": "runaway_loop",
    "trigger_condition": "API returns error, agent retries without backoff",
    "title": "Runaway API Loop",
    "summary": "Agent called weather API 47 times in loop when it returned 503 error."
  },
  "embedding": [0.789, 0.012, ...],
  "similarity_group": "group_abc123",
  "suggestion_content": {
    "guardrail_rule": {
      "name": "max_api_calls_per_session",
      "type": "rate_limit",
      "config": {"max_calls": 10, "window_seconds": 60}
    }
  },
  "approval_metadata": {
    "actor": "reviewer@company.com",
    "action": "approved",
    "notes": "Validated with team - deploying to staging first",
    "timestamp": "2025-01-05T15:00:00Z"
  },
  "version_history": [
    {
      "previous_status": null,
      "new_status": "pending",
      "actor": "system",
      "timestamp": "2025-01-04T10:00:00Z",
      "notes": "Created from pattern_dd_trace_11111"
    },
    {
      "previous_status": "pending",
      "new_status": "approved",
      "actor": "reviewer@company.com",
      "timestamp": "2025-01-05T15:00:00Z",
      "notes": "Validated with team - deploying to staging first"
    }
  ],
  "created_at": "2025-01-04T10:00:00Z",
  "updated_at": "2025-01-05T15:00:00Z"
}
```
