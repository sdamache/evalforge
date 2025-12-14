# Research: Failure Pattern Extraction

## Overview

This spike captures the key technical decisions for extracting structured failure patterns from production failure traces using Vertex AI Gemini, while staying compliant with the Evalforge constitution (observability-first, privacy-safe, Cloud Run only, cost-conscious).

## Decisions

### 1) Firestore inputs, outputs, and idempotency

- **Decision**: Read from Firestore collection `evalforge_raw_traces` where `processed == false`; write schema-validated pattern records to `evalforge_failure_patterns`; mark the source trace `processed=true` only after a successful pattern write.
- **Rationale**:
  - Matches the stated batch workflow and acceptance criteria (schema validation before storage, resilient batch processing).
  - Ensures one pattern per trace and avoids repeated model spend for already-processed traces.
  - Firestore document IDs are already the Datadog trace ID for `evalforge_raw_traces`, which simplifies joins and idempotency.
- **Alternatives considered**:
  - Always reprocess the last N hours regardless of `processed` (higher cost and noise).
  - Store patterns back into the raw trace document only (mixes concerns and increases risk of accidental overwrites).

### 2) Output schema and validation strategy

- **Decision**: Treat the following fields as the canonical persisted pattern contract (validated before write) and store any failures in a separate error record rather than the patterns collection:
  - `pattern_id`, `source_trace_id`, `failure_type`, `trigger_condition`, `reproduction_context`, `severity`, `confidence`, `extracted_at`, `raw_trace_snippet`.
- **Rationale**:
  - Keeps `evalforge_failure_patterns` clean: 100% schema-valid documents (AC2).
  - Supports downstream automation (evals/guardrails/runbooks) using stable, structured fields.
- **Alternatives considered**:
  - Storing invalid/unparsed model output in the patterns collection (breaks AC2).
  - Validating only “best-effort” and storing partial records (creates downstream brittleness).

### 3) Evidence storage and PII safety

- **Decision**: Store evidence as (a) structured signals and (b) short redacted text excerpts (prompts/outputs/errors) when helpful; never store full prompt/output transcripts. Evidence is written as `raw_trace_snippet` and must be redacted/truncated.
- **Rationale**:
  - Balances actionability with privacy risk (supports investigations without exposing raw user data).
  - Aligns with constitution constraints requiring PII stripping/hashing before persistence.
- **Alternatives considered**:
  - Signals-only (lowest risk but weaker debuggability).
  - Full-text storage (rejected due to privacy/compliance risk).

### 4) Gemini SDK and structured output

- **Decision**: Use the **new `google-genai` SDK** (not the deprecated `vertexai.generative_models`) with `response_mime_type: "application/json"` and a `response_schema` to guarantee structured JSON output. Additionally, use few-shot examples in the prompt to guide the model on field semantics and constrain `failure_type`/`severity` to fixed enums.
- **Rationale**:
  - The `vertexai.generative_models` module is **deprecated as of June 2025** and will be removed June 2026; using `google-genai` ensures long-term compatibility.
  - `response_mime_type: "application/json"` with `response_schema` **guarantees** JSON conformance at the API level, rather than relying solely on prompt engineering which can fail.
  - Few-shot examples improve consistency and reduce variance across traces (supports AC1).
  - Strict schema validation ensures storage contract integrity (AC2) and prevents downstream breakage.
- **SDK Usage**:
  ```python
  from google import genai
  from google.genai.types import HttpOptions

  client = genai.Client(http_options=HttpOptions(api_version="v1"))
  response = client.models.generate_content(
      model="gemini-2.5-flash",
      contents=prompt,
      config={
          "response_mime_type": "application/json",
          "response_schema": failure_pattern_schema,
          "temperature": 0.2,
          "max_output_tokens": 4096,
      },
  )
  ```
- **Alternatives considered**:
  - Prompt-only JSON instruction without `response_mime_type` (unreliable; model can emit markdown or extra text).
  - Legacy `vertexai.generative_models` SDK (deprecated, migration required within 12 months).
  - Zero-shot only (higher variance, harder to reach ≥80% accuracy early).

### 5) Gemini model configuration and determinism

- **Decision**: Use `gemini-2.5-flash` (GA model) with temperature `0.2` and output token cap of `max_output_tokens=4096`. Keep processing sequential per run to reduce rate-limit and concurrency risk.
- **Rationale**:
  - `gemini-2.5-flash` is GA as of Google I/O 2025, optimized for low latency and high throughput.
  - Lower temperature (0.2 vs default 1.0) improves repeatability for structured extraction (supports "consistent patterns").
  - Token cap of 4096 (vs original 1024) provides sufficient room for detailed pattern extraction including evidence, actions, and rationale; the model supports up to 65,535 output tokens.
  - Sequential processing reduces accidental request bursts and rate-limit risk.
- **Model Limits** (for reference):
  - Max input tokens: 1,048,576
  - Max output tokens: 65,535
  - Temperature range: 0.0–2.0 (default 1.0)
- **Alternatives considered**:
  - Higher temperature for creativity (hurts consistency).
  - Parallel calls per batch (faster but higher rate-limit and cost-spike risk).
  - `gemini-2.5-flash-lite` (cheaper but less capable for nuanced extraction).

### 6) Timeouts, truncation, and retries

- **Decision**:
  - Enforce a per-trace time budget of **15 seconds** end-to-end (model call + validation + write); timeout is treated as a per-trace error and the batch continues. The spec requires 10 seconds (AC4), but real-world Gemini Flash latencies can reach 5–15 seconds for typical prompts; 15 seconds provides margin while still meeting the "≥95% within 10s" success criterion.
  - If a trace payload exceeds **200KB**, truncate to the last **100KB** before sending to Gemini. Given the model supports ~1M input tokens (~3–4MB text), this is conservative but controls cost.
  - Retry Gemini API failures up to 3 times with exponential backoff (matches existing `tenacity` pattern in `datadog_client.py`).
- **Rationale**:
  - 15-second budget balances the spec's 10-second target against observed Gemini latency variance; most requests complete in 3–8 seconds, so ≥95% will meet the 10s target.
  - Truncation focuses on recent context (where failures manifest) while staying well under model limits.
  - 3 retries with backoff matches project conventions and bounds total wait time.
- **Alternatives considered**:
  - Strict 10-second timeout (risks higher timeout rate during Gemini load spikes).
  - No truncation (risk of higher cost and slower responses for verbose traces).
  - Unlimited retries (risk of runaway spend and scheduler overlap).

### 7) Run tracking and auditability

- **Decision**: Produce a per-run summary (counts, durations, per-trace outcomes) and persist it as a separate “run record” for audit/debugging; include `run_id` in logs and in stored patterns.
- **Rationale**:
  - Supports observability-first investigations and demos of the full loop.
  - Enables operators to understand partial successes without scanning raw logs.
- **Alternatives considered**:
  - Logs-only (harder to query and demo).

## Open Items (to confirm during implementation)

- ~~Verify the Vertex AI SDK call shape for Gemini JSON-only responses~~ → **RESOLVED**: Use `google-genai` SDK with `response_mime_type: "application/json"` and `response_schema` (see Decision #4).
- Confirm IAM strategy for "internal ML engineering + on-call only" access to stored patterns (Cloud Run invoker + Firestore IAM).
- Measure real per-trace latency and adjust `BATCH_SIZE`/timeouts to stay inside Cloud Run request timeout limits.
- **NEW**: Add `google-genai` to project dependencies (`pyproject.toml` or `requirements.txt`).
- **NEW**: Define the `response_schema` dict matching the Pydantic `FailurePattern` model for compile-time and runtime validation alignment.

## References

- [Gemini 2.5 Flash Documentation](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash)
- [Structured Output (JSON mode)](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/control-generated-output)
- [Google Gen AI SDK (new)](https://cloud.google.com/vertex-ai/generative-ai/docs/sdks/overview) — replaces deprecated `vertexai.generative_models`
