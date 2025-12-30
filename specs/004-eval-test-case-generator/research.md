# Research: Eval Test Case Generator

**Branch**: `004-eval-test-case-generator` | **Date**: 2025-12-29

## Research Tasks Completed

### 1) Eval test draft format and pass/fail strategy

**Decision**: Store generated eval tests as a **framework-agnostic JSON object** embedded on the Suggestion (`suggestion_content.eval_test`).

**Rationale**:
- Keeps review and retrieval simple (one document read for suggestions).
- Avoids locking the project into a specific harness (pytest/promptfoo) during the hackathon.
- Enables later export into any test runner by writing adapters.

**Pass/Fail Strategy Decision**: **Rubric-first**, with an optional golden output string when the expected output is deterministic.

**Rationale**:
- Rubrics tolerate normal LLM variance while still preventing regressions.
- Golden outputs are brittle but helpful for deterministic Q&A cases (e.g., factual questions).

**Alternatives Considered**:
- Emit `pytest` templates: “drop-in” but couples to Python and a specific runner.
- Emit Promptfoo YAML: convenient, but opinionated and adds a new schema to maintain.

### 2) Gemini structured JSON output for generation

**Decision**: Use the **google-genai SDK** with `response_mime_type="application/json"` and a strict `response_schema` for the EvalTestDraft.

**Rationale**:
- Avoids brittle “parse freeform text” logic.
- Aligns with the extraction service’s approach and reduces failure modes (invalid JSON, missing fields).

**Best Practice**:
- Low temperature (0.0–0.2) to improve determinism.
- Token caps to stay within latency and cost budgets.
- Persist a `prompt_hash` and `response_sha256` for auditability (without storing raw PII).

### 3) Canonical source selection for multi-trace suggestions

**Decision**: For suggestions with multiple source traces/patterns, choose the **highest-confidence FailurePattern** as the canonical reproduction source. Tie-breaker: **most recent** source trace entry.

**Rationale**:
- Uses the system’s own confidence signal to select the best-quality reproduction context.
- Keeps behavior deterministic and explainable.

**Implementation Note**:
- Confidence lives on `FailurePattern` documents in `{prefix}failure_patterns`, so the generator must fetch all referenced patterns to compare `confidence`.

### 4) Safe regeneration policy (avoid silent loss of human edits)

**Decision**: Do not overwrite an existing draft if it appears “human-edited” unless the caller explicitly sets `forceOverwrite=true`.

**Rationale**:
- Matches the spec edge case: regeneration must not silently discard edits.
- Keeps reviewer trust by making changes explicit.

**Pragmatic marker**:
- Add metadata to the eval draft: `edit_source = "generated" | "human"`.
- Any `edit_source="human"` blocks overwrite unless forced.

### 5) Firestore shape and size constraints

**Decision**: Keep the embedded eval test JSON compact and avoid storing long prompts/outputs.

**Rationale**:
- Firestore documents have a hard 1MB limit.
- The constitution requires PII stripping and minimal storage of sensitive text.

**Best Practices**:
- Use `src.common.pii.redact_and_truncate` on any stored text fields.
- Store short excerpts and generalized “input patterns” rather than raw transcripts.

### 6) Batch processing and throttling strategy

**Decision**: Scheduled/manual batch runs with bounded `EVAL_TEST_BATCH_SIZE`, processed sequentially.

**Rationale**:
- Keeps quota usage predictable.
- Prevents stampedes during failure bursts.

**Retry**:
- At least 3 attempts with exponential backoff for transient Gemini failures (429/5xx) per constitution.

## Resolved Clarifications

- Output format: framework-agnostic JSON.
- Trigger: scheduled/batch runs (manual + scheduled).
- Canonical source: highest-confidence pattern (tie: most recent).
- Criteria style: rubric-first, optional golden output.
- Storage location: embedded at `suggestion_content.eval_test`.

## Next Steps

Proceed to Phase 1 design artifacts:
- Define EvalTestDraft schema in `data-model.md`
- Define generator API contract in `contracts/eval-generator-openapi.yaml`
- Write operator quickstart in `quickstart.md`
