# Data Model: Failure Pattern Extraction

## Collection: `evalforge_raw_traces`

### Entity: FailureCapture (input)

Represents a normalized record of a production failure trace captured from Datadog (written by ingestion).

- **Document ID**: `trace_id` (string)
- **trace_id** (string, required): Datadog trace identifier.
- **fetched_at** (datetime, required): Ingestion timestamp.
- **failure_type** (string, required): Ingestion-time failure label (may be coarse).
- **severity** (string, required): Normalized label (`low|medium|high|critical`).
- **trace_payload** (object, required): Sanitized trace payload (no raw PII).
- **processed** (bool, required, default=false): Whether extraction has produced a stored failure pattern for this trace.

**Constraints**

- `processed=true` MUST be preserved once set, unless explicitly reset by an operator.
- Documents MUST remain PII-safe (sanitized by ingestion).

## Collection: `evalforge_failure_patterns`

### Entity: FailurePattern (output)

Represents a structured failure pattern extracted from a single FailureCapture. Fields align with spec FR-003 and FR-010.

- **Document ID**: `source_trace_id` (string) for idempotent upserts (one pattern per trace).
- **pattern_id** (string, required): Stable identifier for the pattern; recommended format `pattern_<source_trace_id>`.
- **source_trace_id** (string, required): References `FailureCapture.trace_id`. *(FR-003: trace reference)*
- **title** (string, required): Concise pattern title describing the failure. *(FR-003: pattern title)*
- **failure_type** (string enum, required): One of `hallucination|toxicity|wrong_tool|runaway_loop|pii_leak|stale_data|infrastructure_error|client_error`. *(FR-003: standardized category)*
- **trigger_condition** (string, required): Short label describing what triggered the failure. *(FR-003: primary contributing factor)*
- **summary** (string, required): 1-2 sentence description of what happened. *(FR-003: concise summary)*
- **root_cause_hypothesis** (string, required): Best explanation for why the failure occurred. *(FR-003: root-cause hypothesis)*
- **evidence** (object, required): Supporting evidence from the trace. *(FR-003: supporting evidence)*
  - **signals** (array[string], required): At least one trace-derived signal (e.g., error codes, latency spikes, token counts).
  - **excerpt** (string, optional): Short redacted text excerpt (prompts/outputs/errors); never full transcripts.
- **recommended_actions** (array[string], required): At least one prevention/mitigation action. *(FR-003: recommended actions)*
- **reproduction_context** (object, required):
  - **input_pattern** (string, required): Typical input phrasing/shape that reproduces the issue.
  - **required_state** (string, optional): Preconditions needed to reproduce (e.g., empty cart, no history).
  - **tools_involved** (array[string], required): Tool names involved in the failure, if any.
- **severity** (string enum, required): One of `low|medium|high|critical`.
- **confidence** (number, required): Float in range `[0.0, 1.0]`. *(FR-003, FR-009)*
- **confidence_rationale** (string, required): Short explanation of key signals that influenced the confidence score. *(FR-010)*
- **extracted_at** (datetime, required): Extraction timestamp (UTC). *(FR-003: extraction timestamp)*

**Constraints**

- All documents in `evalforge_failure_patterns` MUST be schema-valid; invalid model outputs MUST NOT be written to this collection.
- `evidence.excerpt` MUST be redacted/truncated and MUST NOT contain raw sensitive user data.
- Re-processing the same `source_trace_id` MUST overwrite/update the same document (idempotent).

## Collection: `evalforge_extraction_runs` (recommended)

### Entity: ExtractionRunSummary (audit)

Captures one batch execution of the extraction service.

- **Document ID**: `run_id` (string, generated per execution).
- **run_id** (string, required)
- **started_at** (datetime, required)
- **finished_at** (datetime, required)
- **triggered_by** (string enum, required): `scheduled|manual`.
- **batch_size** (integer, required)
- **picked_up_count** (integer, required): Traces fetched for attempted processing.
- **stored_count** (integer, required): Patterns successfully stored.
- **validation_failed_count** (integer, required)
- **error_count** (integer, required): Includes timeouts and API failures.
- **trace_outcomes** (array[object], optional): Per-trace summaries:
  - **source_trace_id** (string)
  - **status** (string enum): `stored|skipped|validation_failed|error|timed_out`
  - **pattern_id** (string, optional)
  - **error_reason** (string, optional)

## Collection: `evalforge_extraction_errors` (recommended)

### Entity: ExtractionError (diagnostic)

Stores per-trace failures (e.g., invalid JSON, retries exhausted) without polluting the schema-valid patterns collection.

- **Document ID**: `${run_id}:${source_trace_id}` (string)
- **run_id** (string, required)
- **source_trace_id** (string, required)
- **error_type** (string enum, required): `invalid_json|schema_validation|vertex_error|timeout|oversize|unknown`
- **error_message** (string, required)
- **raw_model_response** (string, optional): Truncated/redacted.
- **recorded_at** (datetime, required)
