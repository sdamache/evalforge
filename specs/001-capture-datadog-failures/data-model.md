# Data Model: Automatic Capture of Datadog Failures

## Entity: FailureCapture

Represents a normalized record of a production LLM failure captured from Datadog.

- **trace_id** (string, required): Unique identifier of the Datadog trace.
- **fetched_at** (datetime, required): Timestamp when the trace was retrieved by the ingestion job.
- **status_code** (integer, optional): HTTP status associated with the failing call, if available.
- **quality_score** (float, optional): Datadog LLM quality score for the trace.
- **failure_type** (string, required): Categorical label such as `hallucination`, `toxicity`, `prompt_injection`, `latency`, or `infrastructure_error`.
- **trace_payload** (object, required): Sanitized subset of the original trace payload with raw PII fields removed.
- **user_hash** (string, optional): SHA-256 hash of the original user identifier plus salt, used for grouping incidents without exposing PII.
- **processed** (bool, required, default=false): Indicates whether this failure has been consumed by downstream eval/guardrail/runbook generators.
- **service_name** (string, required): Name of the LLM agent or service (e.g., `llm-agent`), derived from Datadog tags.
- **severity** (string, required): Normalized severity label (e.g., `low`, `medium`, `high`, `critical`) based on quality_score and eval flags.
- **recurrence_count** (integer, required, default=1): Number of times failures with the same signature have been observed.

**Sanitization Rules**

- Strip before storing: `user.email`, `user.name`, `user.phone`, `user.address`, `user.ip`, `client.ip`, `session_id`, `request.headers.authorization`, `request.headers.cookie`, and any tag prefixed with `pii:` or `user.` (except `user.id`).
- Hash with salt: `user.id` → `user_hash = sha256(user.id + salt)`.
- Redact free-text `prompt`/`input`/`response` fields unless explicitly whitelisted for debugging; retain model metadata, token counts, timings, and evaluation flags.

### Relationships

- A `FailureCapture` references a single Datadog trace (`trace_id`), but the same underlying issue may result in many captures that share a failure signature.
- Downstream systems (evals, guardrails, runbooks) will reference `FailureCapture` records by `trace_id` or a separate improvement identifier.

### Constraints

- `trace_id` MUST be unique within the Firestore collection; attempts to insert a duplicate MUST update `recurrence_count` instead of creating a new document.
- `trace_payload` MUST NOT contain raw PII fields (email, name, phone, address, direct user IDs); any identifiers are stored as `user_hash`.
- `fetched_at` MUST reflect ingestion time, not original trace creation time, to support freshness monitoring.

## Entity: SourceTraceReference

Captures the minimal information required to rehydrate or inspect the original trace in Datadog.

- **trace_id** (string, required): Matches `FailureCapture.trace_id`.
- **datadog_url** (string, required): Deep link to the trace in the Datadog UI.
- **datadog_site** (string, required): Site identifier (e.g., `datadoghq.com`).

## Entity: ExportPackage

Represents a bundle sent to downstream systems when a failure is exported for improvement work.

- **failure_trace_id** (string, required): References the associated `FailureCapture.trace_id`.
- **exported_at** (datetime, required): Timestamp when export occurred.
- **destination** (string, required): Logical destination such as `eval_backlog`, `guardrail_generator`, or `runbook_drafts`.
- **status** (string, required): Export status (`pending`, `succeeded`, `failed`).
- **status_detail** (string, optional): Short human-readable explanation for failures or special handling.
