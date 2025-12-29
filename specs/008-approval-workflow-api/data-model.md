# Data Model: Approval Workflow API

**Branch**: `008-approval-workflow-api` | **Date**: 2025-12-29

## Entity Overview

This feature adds **approval workflow operations** on the existing **Suggestion** documents created by Issue #3 (deduplication). No new Firestore collections are created.

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Suggestion                                 │
│                   (Issue #3, extended by this feature)              │
│                                                                      │
│  - suggestion_id (PK)                                               │
│  - type: "eval" | "guardrail" | "runbook"                           │
│  - status: "pending" | "approved" | "rejected" ◄── This feature     │
│  - created_at                                                        │
│  - updated_at                                                        │
│  - source_traces[]                                                   │
│  - pattern {}                                                        │
│  - suggestion_content {}                                             │
│  - similarity_group                                                  │
│  - embedding[]                                                       │
│  - approval_metadata {} ◄── This feature                            │
│  - version_history[] ◄── This feature                               │
└─────────────────────────────────────────────────────────────────────┘
```

## Entities

### Suggestion (existing, extended)

**Collection**: `{FIRESTORE_COLLECTION_PREFIX}suggestions`
**Document ID**: `suggestion_id` (e.g., `sugg_abc123`)

This feature reads and updates:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `suggestion_id` | string | Yes | Unique identifier (existing) |
| `type` | string | Yes | One of: `eval`, `guardrail`, `runbook` (existing) |
| `status` | string | Yes | One of: `pending`, `approved`, `rejected` (existing, updated by this feature) |
| `created_at` | timestamp | Yes | When suggestion was created (existing) |
| `updated_at` | timestamp | Yes | When suggestion was last modified (updated by this feature) |
| `source_traces` | array[string] | Yes | Trace IDs that contributed to this suggestion (existing) |
| `pattern` | object | Yes | Extracted failure pattern (existing) |
| `suggestion_content` | object | Yes | Generated content by type (existing) |
| `similarity_group` | string | No | Deduplication group ID (existing) |
| `embedding` | array[number] | No | Vector embedding for similarity (existing) |
| `approval_metadata` | object | No | **NEW**: Approval/rejection details (added by this feature) |
| `version_history` | array[object] | Yes | **NEW**: Audit trail of status changes (added by this feature) |

### ApprovalMetadata (new, embedded)

**Embedded in**: `Suggestion.approval_metadata`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `actor` | string | Yes | Who performed the action (email or API key identifier) |
| `action` | string | Yes | One of: `approved`, `rejected` |
| `notes` | string | No | Optional notes provided during approval |
| `reason` | string | Conditional | Required for rejection, explains why rejected |
| `timestamp` | timestamp | Yes | When the action was performed |

### VersionHistoryEntry (new, embedded)

**Embedded in**: `Suggestion.version_history[]`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | string | Yes | Status after this transition |
| `timestamp` | timestamp | Yes | When the transition occurred |
| `actor` | string | Yes | Who triggered the transition |
| `notes` | string | No | Optional context for the transition |

## API Request/Response Models

### ApproveRequest

```json
{
  "notes": "Validated with team, deploying to staging first"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `notes` | string | No | Optional notes for the approval |

### RejectRequest

```json
{
  "reason": "False positive - not actually a failure pattern"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `reason` | string | Yes | Required explanation for rejection |

### ApprovalResponse

```json
{
  "status": "success",
  "suggestion_id": "sugg_xyz789",
  "new_status": "approved",
  "timestamp": "2025-12-29T15:00:00Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `success` or `error` |
| `suggestion_id` | string | The affected suggestion ID |
| `new_status` | string | The new status after the action |
| `timestamp` | string | ISO timestamp of the action |

### SuggestionListResponse

```json
{
  "suggestions": [...],
  "limit": 50,
  "next_cursor": "sugg_xyz789",
  "has_more": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `suggestions` | array | List of suggestion summaries |
| `limit` | integer | Page size used |
| `next_cursor` | string | Cursor for next page (last doc ID), null if no more |
| `has_more` | boolean | Whether more results exist |

**Note**: Uses cursor-based pagination (`start_after`) instead of offset to avoid Firestore billing for skipped documents.

### SuggestionDetail

```json
{
  "suggestion_id": "sugg_xyz789",
  "type": "eval",
  "status": "pending",
  "created_at": "2025-12-29T12:00:00Z",
  "updated_at": "2025-12-29T12:00:00Z",
  "pattern": {
    "failure_type": "stale_data",
    "trigger_condition": "Product recommendation without inventory check",
    "severity": "medium"
  },
  "suggestion_content": {
    "eval_test": {...},
    "guardrail_rule": {...},
    "runbook_snippet": {...}
  },
  "source_traces": ["dd_trace_123", "dd_trace_456"],
  "approval_metadata": null,
  "version_history": [
    {"status": "pending", "timestamp": "2025-12-29T12:00:00Z", "actor": "system"}
  ]
}
```

### ExportResponse

Returns file content with appropriate Content-Type header.

| Format | Content-Type | Body |
|--------|--------------|------|
| `deepeval` | `application/json` | JSON object |
| `pytest` | `text/x-python` | Python test code |
| `yaml` | `application/x-yaml` | YAML configuration |

## Enums

### SuggestionStatus

`pending` | `approved` | `rejected`

**State Transitions**:
- `pending` → `approved` (via POST /approve)
- `pending` → `rejected` (via POST /reject)
- `approved` → (terminal, no transitions)
- `rejected` → (terminal, no transitions)

### SuggestionType

`eval` | `guardrail` | `runbook`

### ExportFormat

`deepeval` | `pytest` | `yaml`

## Sample Documents

### Pending Suggestion

```json
{
  "suggestion_id": "sugg_xyz789",
  "type": "eval",
  "status": "pending",
  "created_at": "2025-12-29T12:00:00Z",
  "updated_at": "2025-12-29T12:00:00Z",
  "source_traces": ["dd_trace_123", "dd_trace_456"],
  "pattern": {
    "failure_type": "stale_data",
    "trigger_condition": "Product recommendation without inventory check",
    "severity": "medium",
    "confidence": 0.85
  },
  "suggestion_content": {
    "eval_test": {
      "title": "Prevent stale product recommendations",
      "input": {"prompt": "Show me winter coats"},
      "assertions": {
        "required": ["Product must be in active catalog"],
        "forbidden": ["Discontinued SKUs"]
      }
    }
  },
  "version_history": [
    {"status": "pending", "timestamp": "2025-12-29T12:00:00Z", "actor": "deduplication-service"}
  ]
}
```

### Approved Suggestion

```json
{
  "suggestion_id": "sugg_xyz789",
  "type": "eval",
  "status": "approved",
  "created_at": "2025-12-29T12:00:00Z",
  "updated_at": "2025-12-29T15:00:00Z",
  "source_traces": ["dd_trace_123", "dd_trace_456"],
  "pattern": {...},
  "suggestion_content": {...},
  "approval_metadata": {
    "actor": "platform-lead@example.com",
    "action": "approved",
    "notes": "Validated with team",
    "timestamp": "2025-12-29T15:00:00Z"
  },
  "version_history": [
    {"status": "pending", "timestamp": "2025-12-29T12:00:00Z", "actor": "deduplication-service"},
    {"status": "approved", "timestamp": "2025-12-29T15:00:00Z", "actor": "platform-lead@example.com", "notes": "Validated with team"}
  ]
}
```

### Rejected Suggestion

```json
{
  "suggestion_id": "sugg_abc456",
  "type": "guardrail",
  "status": "rejected",
  "created_at": "2025-12-29T10:00:00Z",
  "updated_at": "2025-12-29T14:00:00Z",
  "source_traces": ["dd_trace_789"],
  "pattern": {...},
  "suggestion_content": {...},
  "approval_metadata": {
    "actor": "ml-engineer@example.com",
    "action": "rejected",
    "reason": "False positive - edge case already handled by existing guardrail",
    "timestamp": "2025-12-29T14:00:00Z"
  },
  "version_history": [
    {"status": "pending", "timestamp": "2025-12-29T10:00:00Z", "actor": "deduplication-service"},
    {"status": "rejected", "timestamp": "2025-12-29T14:00:00Z", "actor": "ml-engineer@example.com", "notes": "False positive"}
  ]
}
```

## Indexes Required

The following Firestore composite indexes are needed (may already exist from Issue #3):

| Collection | Fields | Order |
|------------|--------|-------|
| suggestions | `status`, `created_at` | ASC, DESC |
| suggestions | `status`, `type`, `created_at` | ASC, ASC, DESC |
| suggestions | `type`, `created_at` | ASC, DESC |

## Validation Rules

1. **Approval**: `status` must be `pending`; transition to `approved`
2. **Rejection**: `status` must be `pending`; `reason` field required; transition to `rejected`
3. **Export**: `status` must be `approved`; `suggestion_content` must contain appropriate content for the suggestion type
4. **Idempotency**: Re-approving an already approved suggestion returns 409 Conflict
5. **Atomicity**: Status transition and version_history append must be in same Firestore transaction
