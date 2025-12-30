# Data Model: Runbook Draft Generator

**Feature**: 006-runbook-generation
**Date**: 2025-12-30

## Overview

The runbook generator follows the same embedded document pattern as the eval test generator. RunbookDraft is stored within the existing Suggestion entity at `suggestion_content.runbook_snippet`, avoiding separate collection management.

## Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Suggestion                                   │
│  (existing entity from Issue #3)                                    │
├─────────────────────────────────────────────────────────────────────┤
│  suggestion_id: str (PK)                                            │
│  type: "eval" | "guardrail" | "runbook"                            │
│  status: "pending" | "approved" | "rejected"                        │
│  created_at: datetime                                               │
│  updated_at: datetime                                               │
│  source_traces: List[str]                                           │
│  pattern: FailurePattern                                            │
│  approval_metadata: ApprovalMetadata | null                         │
│  suggestion_content: {                                              │
│    eval_test: EvalTestDraft | null      ← Issue #4                 │
│    guardrail_rule: GuardrailRule | null ← Issue #5                 │
│    runbook_snippet: RunbookDraft | null ← THIS FEATURE             │
│  }                                                                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ embeds
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        RunbookDraft                                  │
├─────────────────────────────────────────────────────────────────────┤
│  runbook_id: str                     # Format: "runbook_{suggestion_id}"
│  title: str                          # e.g., "Stale Data - Operational Runbook"
│  rationale: str                      # Why this runbook was generated (plain-language reasoning)
│  markdown_content: str               # Full rendered Markdown
│  symptoms: List[str]                 # Observable indicators
│  diagnosis_commands: List[str]       # Specific commands/queries
│  mitigation_steps: List[str]         # Immediate actions
│  escalation_criteria: str            # When/who/threshold
│  source: RunbookDraftSource          # Lineage tracking
│  status: "draft" | "needs_human_input"
│  edit_source: "generated" | "human"
│  generated_at: datetime
│  updated_at: datetime
│  generator_meta: RunbookDraftGeneratorMeta
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌─────────────────────────────┐   ┌─────────────────────────────────────┐
│    RunbookDraftSource       │   │    RunbookDraftGeneratorMeta        │
├─────────────────────────────┤   ├─────────────────────────────────────┤
│  suggestion_id: str         │   │  model: str                         │
│  canonical_trace_id: str    │   │  temperature: float                 │
│  canonical_pattern_id: str  │   │  prompt_hash: str                   │
│  trace_ids: List[str]       │   │  response_sha256: str               │
│  pattern_ids: List[str]     │   │  run_id: str                        │
└─────────────────────────────┘   └─────────────────────────────────────┘
```

## Collections

### Existing Collections (No Changes)

| Collection | Document Key | Purpose |
|------------|-------------|---------|
| `{prefix}suggestions` | `suggestion_id` | Stores Suggestion with embedded runbook_snippet |
| `{prefix}failure_patterns` | `pattern_id` | Source patterns for generation (read-only) |

### New Collections

| Collection | Document Key | Purpose |
|------------|-------------|---------|
| `{prefix}runbook_runs` | `run_id` | Batch execution summaries |
| `{prefix}runbook_errors` | `{run_id}:{suggestion_id}` | Per-suggestion failure records |

## Entity Definitions

### RunbookDraft

The core generated artifact embedded on Suggestion documents.

```python
class RunbookDraftStatus(str, Enum):
    DRAFT = "draft"
    NEEDS_HUMAN_INPUT = "needs_human_input"

class EditSource(str, Enum):
    GENERATED = "generated"
    HUMAN = "human"

class RunbookDraft(BaseModel):
    runbook_id: str                          # Format: runbook_{suggestion_id}
    title: str                               # e.g., "Hallucination - Operational Runbook"
    rationale: str                           # Why this runbook was generated (plain-language reasoning citing source trace)
    markdown_content: str                    # Full Markdown (GitHub/Confluence ready)

    # Structured fields for programmatic access
    symptoms: List[str]                      # ["Quality score drops below 0.5", "User reports inaccuracy"]
    diagnosis_commands: List[str]            # ["datadog trace search...", "curl -X GET..."]
    mitigation_steps: List[str]              # ["Apply guardrail X", "Restart service Y"]
    escalation_criteria: str                 # "Customer impact >100 users OR downtime >30 min"

    # Lineage
    source: RunbookDraftSource

    # Lifecycle
    status: RunbookDraftStatus
    edit_source: EditSource
    generated_at: datetime
    updated_at: datetime
    generator_meta: RunbookDraftGeneratorMeta
```

### RunbookDraftSource

Tracks lineage back to source incidents and patterns.

```python
class RunbookDraftSource(BaseModel):
    suggestion_id: str                       # Parent suggestion
    canonical_trace_id: str                  # Primary source trace
    canonical_pattern_id: str                # Primary source pattern
    trace_ids: List[str]                     # All contributing traces
    pattern_ids: List[str]                   # All contributing patterns
```

### RunbookDraftGeneratorMeta

Audit trail for generation reproducibility.

```python
class RunbookDraftGeneratorMeta(BaseModel):
    model: str                               # e.g., "gemini-2.5-flash"
    temperature: float                       # e.g., 0.3
    prompt_hash: str                         # SHA256 of prompt
    response_sha256: str                     # SHA256 of raw response
    run_id: str                              # Batch run identifier
```

### RunbookRunSummary

Batch execution record (mirrors EvalTestRunSummary).

```python
class RunbookRunSummary(BaseModel):
    run_id: str                              # Format: run_{timestamp}_{random}
    started_at: datetime
    finished_at: datetime
    triggered_by: TriggeredBy                # "scheduled" | "manual"
    batch_size: int
    picked_up_count: int
    generated_count: int
    skipped_count: int
    error_count: int
    processing_duration_ms: int
    suggestion_outcomes: List[RunbookOutcome]
```

### RunbookError

Per-suggestion failure record for diagnostics.

```python
class RunbookErrorType(str, Enum):
    INVALID_JSON = "invalid_json"
    SCHEMA_VALIDATION = "schema_validation"
    VERTEX_ERROR = "vertex_error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"

class RunbookError(BaseModel):
    run_id: str
    suggestion_id: str
    error_type: RunbookErrorType
    error_message: str
    recorded_at: datetime
    model_response_sha256: Optional[str]
    model_response_excerpt: Optional[str]    # First 500 chars for debugging
```

## Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `runbook_id` | Must match `runbook_{suggestion_id}` pattern | Schema validation error |
| `markdown_content` | Must contain all 6 required sections | Status set to `needs_human_input` |
| `diagnosis_commands` | Must have at least 2 items | Status set to `needs_human_input` |
| `symptoms` | Must have at least 1 item | Status set to `needs_human_input` |
| `edit_source` | Cannot overwrite `"human"` without `forceOverwrite` | 409 Conflict |

## State Transitions

### RunbookDraft Status

```
                    ┌──────────────────────────────────┐
                    │                                  │
                    ▼                                  │
┌─────────────┐   Generate   ┌─────────────────────────────┐
│   (none)    │ ──────────▶  │     draft                   │
└─────────────┘              └─────────────────────────────┘
                                         │
                                         │ Insufficient context
                                         ▼
                             ┌─────────────────────────────┐
                             │   needs_human_input         │
                             └─────────────────────────────┘
                                         │
                                         │ Human edits & saves
                                         ▼
                             ┌─────────────────────────────┐
                             │   draft (edit_source=human) │
                             └─────────────────────────────┘
```

### EditSource Transitions

```
generated ──[human edits]──▶ human
human ──[forceOverwrite=true]──▶ generated
```

## Indexes

### Required Composite Indexes

Already exist from Issue #3 (reused):
- `(type, status, created_at)` - for querying pending runbook suggestions

New indexes:
- `runbook_runs`: `(started_at DESC)` - for health check last run lookup
- `runbook_errors`: `(run_id, suggestion_id)` - for error lookup

## Firestore Document Examples

### Suggestion with RunbookDraft

```json
{
  "suggestion_id": "sugg_abc123",
  "type": "runbook",
  "status": "pending",
  "created_at": "2025-12-30T10:00:00Z",
  "updated_at": "2025-12-30T12:00:00Z",
  "source_traces": ["dd_trace_123", "dd_trace_456"],
  "pattern": {
    "failure_type": "stale_data",
    "trigger_condition": "Product recommendation without inventory check",
    "severity": "medium"
  },
  "suggestion_content": {
    "runbook_snippet": {
      "runbook_id": "runbook_sugg_abc123",
      "title": "Stale Data - Operational Runbook",
      "rationale": "Generated from production incident dd_trace_123 where LLM agent recommended discontinued products due to stale inventory cache. This runbook captures the diagnosis and remediation steps for similar future incidents.",
      "markdown_content": "# Stale Data - Operational Runbook\n\n**Source Incident**: `dd_trace_123`\n...",
      "symptoms": [
        "Product unavailable errors in customer feedback",
        "Inventory mismatch alerts in monitoring"
      ],
      "diagnosis_commands": [
        "datadog trace search \"service:llm-agent @failure_type:stale_data\"",
        "curl -s inventory-api/sync-status | jq '.last_sync_at'"
      ],
      "mitigation_steps": [
        "Force inventory cache refresh: curl -X POST inventory-api/refresh",
        "Apply guardrail: product_availability_check"
      ],
      "escalation_criteria": "Customer impact >100 users OR sync delay >1 hour",
      "source": {
        "suggestion_id": "sugg_abc123",
        "canonical_trace_id": "dd_trace_123",
        "canonical_pattern_id": "pattern_dd_trace_123",
        "trace_ids": ["dd_trace_123", "dd_trace_456"],
        "pattern_ids": ["pattern_dd_trace_123"]
      },
      "status": "draft",
      "edit_source": "generated",
      "generated_at": "2025-12-30T12:00:00Z",
      "updated_at": "2025-12-30T12:00:00Z",
      "generator_meta": {
        "model": "gemini-2.5-flash",
        "temperature": 0.3,
        "prompt_hash": "sha256:abc123...",
        "response_sha256": "sha256:def456...",
        "run_id": "run_20251230_120000_ab12cd34"
      }
    }
  }
}
```
