# Data Model: Eval Test Case Generator

**Branch**: `004-eval-test-case-generator` | **Date**: 2025-12-29

## Entity Overview

This feature adds a structured **EvalTestDraft** embedded on the existing **Suggestion** document created by Issue #3.

```
┌─────────────────────┐         ┌──────────────────────┐
│   FailurePattern    │ 1    n  │      Suggestion      │
│   (Issue #2)        │─────────│   (Issue #3)         │
│                     │         │                      │
│ - confidence        │         │ - source_traces[]    │
│ - reproduction_ctx  │         │ - suggestion_content │
└─────────────────────┘         │      └─ eval_test ◄───┐
                                └──────────────────────┘
                                         │
                                         ▼
                                ┌──────────────────────┐
                                │   EvalTestDraft      │
                                │  (this feature)      │
                                └──────────────────────┘
```

## Entities

### Suggestion (existing)

**Collection**: `{FIRESTORE_COLLECTION_PREFIX}suggestions`  
**Document ID**: `suggestion_id` (e.g., `sugg_abc123`)

This feature populates:

- `suggestion_content.eval_test` → **EvalTestDraft** (framework-agnostic JSON)

This feature also reads (but MUST NOT modify) existing governance fields for downstream gating:

- `status` → approval status (`pending` / `approved` / `rejected`)
- `approval_metadata.timestamp` → approval timestamp (when present)

### EvalTestDraft (new, embedded)

**Embedded in**: `Suggestion.suggestion_content.eval_test`

| Field | Type | Required | Description |
|------|------|----------|-------------|
| `eval_test_id` | string | Yes | Stable identifier (recommended: `eval_{suggestion_id}`) |
| `title` | string | Yes | Human-readable test name |
| `rationale` | string | Yes | Plain-language mapping from production failure → test purpose |
| `source` | object | Yes | Lineage + canonical source selection |
| `input` | object | Yes | Reproducible input pattern and minimal setup |
| `assertions` | object | Yes | Rubric-first pass/fail criteria (+ optional golden output) |
| `status` | string | Yes | One of: `draft`, `needs_human_input` |
| `edit_source` | string | Yes | One of: `generated`, `human` (blocks overwrite unless forced) |
| `generated_at` | timestamp | Yes | When draft was produced |
| `updated_at` | timestamp | Yes | When draft was last updated |
| `generator_meta` | object | Yes | Model + prompt hashes for auditability |

#### EvalTestDraft.source

| Field | Type | Required | Description |
|------|------|----------|-------------|
| `suggestion_id` | string | Yes | Owning suggestion |
| `canonical_trace_id` | string | Yes | Chosen trace for reproduction context |
| `canonical_pattern_id` | string | Yes | Chosen pattern for reproduction context |
| `trace_ids` | array[string] | Yes | All contributing trace IDs (lineage) |
| `pattern_ids` | array[string] | Yes | All contributing pattern IDs (lineage) |

#### EvalTestDraft.input

| Field | Type | Required | Description |
|------|------|----------|-------------|
| `prompt` | string | Yes | Sanitized, reproducible prompt/input (may be generalized) |
| `required_state` | string | No | Preconditions needed to reproduce (optional) |
| `tools_involved` | array[string] | Yes | Tools involved (can be empty) |

#### EvalTestDraft.assertions

| Field | Type | Required | Description |
|------|------|----------|-------------|
| `required` | array[string] | Yes | Rubric: behaviors/content that must be present |
| `forbidden` | array[string] | Yes | Rubric: behaviors/content that must not occur |
| `golden_output` | string | No | Optional golden output when deterministic (short) |
| `notes` | string | No | Extra reviewer guidance (optional) |

#### EvalTestDraft.generator_meta

| Field | Type | Required | Description |
|------|------|----------|-------------|
| `model` | string | Yes | Gemini model name |
| `temperature` | number | Yes | Generation temperature |
| `prompt_hash` | string | Yes | Hash of generation prompt |
| `response_sha256` | string | Yes | Hash of raw model response |
| `run_id` | string | Yes | Generation run identifier |

### EvalTestRunSummary (new)

**Collection**: `{FIRESTORE_COLLECTION_PREFIX}eval_test_runs`  
**Document ID**: `run_id`

| Field | Type | Required | Description |
|------|------|----------|-------------|
| `run_id` | string | Yes | Unique run identifier |
| `started_at` | timestamp | Yes | Run start |
| `finished_at` | timestamp | Yes | Run completion |
| `triggered_by` | string | Yes | `scheduled` or `manual` |
| `batch_size` | integer | Yes | Configured max suggestions to process |
| `picked_up_count` | integer | Yes | Suggestions selected for processing |
| `generated_count` | integer | Yes | Drafts successfully written |
| `skipped_count` | integer | Yes | Skipped (e.g., non-eval type, overwrite protected) |
| `error_count` | integer | Yes | Failures recorded |
| `suggestion_outcomes` | array[object] | No | Optional per-suggestion outcomes for demo/audit |

### EvalTestError (new)

**Collection**: `{FIRESTORE_COLLECTION_PREFIX}eval_test_errors`  
**Document ID**: `{run_id}:{suggestion_id}`

| Field | Type | Required | Description |
|------|------|----------|-------------|
| `run_id` | string | Yes | Run identifier |
| `suggestion_id` | string | Yes | Suggestion that failed |
| `error_type` | string | Yes | `invalid_json`, `schema_validation`, `vertex_error`, `timeout`, `unknown` |
| `error_message` | string | Yes | Human-readable error |
| `recorded_at` | timestamp | Yes | When the error was recorded |
| `model_response_sha256` | string | No | Hash of raw response for correlation |
| `model_response_excerpt` | string | No | Short redacted excerpt for debugging |

## Enums

### TriggeredBy

`scheduled` \| `manual`

### EvalDraftStatus

`draft` \| `needs_human_input`

### EditSource

`generated` \| `human`

## Sample Embedded Draft

```json
{
  "eval_test_id": "eval_sugg_abc123",
  "title": "Prevent stale product recommendations",
  "rationale": "A production incident showed the agent recommending discontinued SKUs; this test ensures the agent checks inventory freshness before recommending products.",
  "source": {
    "suggestion_id": "sugg_abc123",
    "canonical_trace_id": "dd_trace_67890",
    "canonical_pattern_id": "pattern_dd_trace_67890",
    "trace_ids": ["dd_trace_12345", "dd_trace_67890"],
    "pattern_ids": ["pattern_dd_trace_12345", "pattern_dd_trace_67890"]
  },
  "input": {
    "prompt": "Recommend a product for a customer looking for a laptop under $1000.",
    "required_state": "Inventory contains out-of-stock and discontinued items.",
    "tools_involved": ["inventory_lookup"]
  },
  "assertions": {
    "required": ["Must call inventory_lookup before recommending a SKU", "Must recommend only in-stock SKUs"],
    "forbidden": ["Must not recommend discontinued SKUs"],
    "golden_output": null
  },
  "status": "draft",
  "edit_source": "generated",
  "generated_at": "2025-12-29T12:00:00Z",
  "updated_at": "2025-12-29T12:00:00Z",
  "generator_meta": {
    "model": "gemini-2.5-flash",
    "temperature": 0.2,
    "prompt_hash": "sha256:...",
    "response_sha256": "sha256:...",
    "run_id": "run_20251229_120000_ab12cd34"
  }
}
```
