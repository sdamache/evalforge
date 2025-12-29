"""Prompt templates for eval test draft generation."""

from __future__ import annotations

from typing import Any, Dict, List


def build_eval_test_generation_prompt(
    *,
    suggestion: Dict[str, Any],
    canonical_pattern: Dict[str, Any],
    trace_ids: List[str],
    pattern_ids: List[str],
) -> str:
    """Build the generation prompt for an eval test draft.

    Inputs must already be sanitized (no raw PII) before calling this builder.
    """
    suggestion_id = suggestion.get("suggestion_id", "")
    pattern_summary = suggestion.get("pattern", {}) or {}

    failure_type = pattern_summary.get("failure_type", canonical_pattern.get("failure_type", "unknown"))
    trigger_condition = pattern_summary.get("trigger_condition", canonical_pattern.get("trigger_condition", ""))
    summary = pattern_summary.get("summary", canonical_pattern.get("summary", ""))

    root_cause = canonical_pattern.get("root_cause_hypothesis", "")
    evidence = canonical_pattern.get("evidence", {}) or {}
    evidence_signals = evidence.get("signals", [])
    reproduction_context = canonical_pattern.get("reproduction_context", {}) or {}

    input_pattern = reproduction_context.get("input_pattern", "")
    required_state = reproduction_context.get("required_state", "")
    tools_involved = reproduction_context.get("tools_involved", [])

    return f"""
You are generating a framework-agnostic JSON eval test draft for Evalforge.

IMPORTANT CONSTRAINTS:
- Output MUST be a single JSON object (no markdown, no prose).
- Do NOT include raw PII (emails, phone numbers, user IDs, access tokens). Use placeholders like [EMAIL_REDACTED].
- Prefer rubric-based assertions: provide `assertions.required[]` and `assertions.forbidden[]`.
- Only include `assertions.golden_output` if the expected output is deterministic and short.
- If the available reproduction context is insufficient to form a runnable test, set `status` to `needs_human_input`
  and include clear placeholders in `input.prompt` and `assertions.notes` describing what a human must add.

CONTEXT:
- suggestion_id: {suggestion_id}
- failure_type: {failure_type}
- trigger_condition: {trigger_condition}
- failure_summary: {summary}
- root_cause_hypothesis: {root_cause}
- evidence_signals: {evidence_signals}
- reproduction_context.input_pattern: {input_pattern}
- reproduction_context.required_state: {required_state}
- reproduction_context.tools_involved: {tools_involved}
- lineage.trace_ids: {trace_ids}
- lineage.pattern_ids: {pattern_ids}

TASK:
Generate a JSON object with these fields:
- title (string)
- rationale (string)
- input: {{ prompt (string), required_state (optional string), tools_involved (array[string]) }}
- assertions: {{ required (array[string]), forbidden (array[string]), golden_output (optional string), notes (optional string) }}
- status: one of ["draft", "needs_human_input"]
""".strip()

