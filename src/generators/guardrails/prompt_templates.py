"""Prompt templates for guardrail draft generation.

Builds prompts that include:
- Failure type and guardrail type hint (pre-determined from mapping)
- Example configurations for each guardrail type
- PII redaction constraints
- JSON output enforcement
"""

from typing import Any, Dict, List

from .guardrail_types import GuardrailType

# Example configurations by guardrail type - used in prompts to guide generation
EXAMPLE_CONFIGURATIONS: Dict[GuardrailType, Dict[str, Any]] = {
    GuardrailType.VALIDATION_RULE: {
        "check_type": "pre_response",
        "condition": "Verify claims against knowledge base before responding",
        "validation_source": "knowledge_base",
    },
    GuardrailType.RATE_LIMIT: {
        "max_calls": 10,
        "window_seconds": 60,
        "scope": "session",
        "action": "block_and_alert",
    },
    GuardrailType.CONTENT_FILTER: {
        "filter_type": "output",
        "threshold": 0.7,
        "categories": ["toxic", "harmful", "profane"],
        "action": "block",
    },
    GuardrailType.REDACTION_RULE: {
        "patterns": ["email", "phone", "ssn", "credit_card"],
        "custom_regex": None,
        "scope": "output",
        "action": "redact",
    },
    GuardrailType.SCOPE_LIMIT: {
        "allowed_tools": ["search", "calculator"],
        "blocked_tools": ["file_write", "code_execution"],
        "context_rules": "Block dangerous tools when handling untrusted input",
        "action": "block",
    },
    GuardrailType.FRESHNESS_CHECK: {
        "max_age_hours": 24,
        "data_sources": ["customer_data", "inventory"],
        "action": "warn",
    },
    GuardrailType.INPUT_SANITIZATION: {
        "patterns": ["ignore previous", "disregard instructions", "system prompt"],
        "custom_patterns": None,
        "action": "block",
    },
}


def build_guardrail_generation_prompt(
    *,
    suggestion: Dict[str, Any],
    canonical_pattern: Dict[str, Any],
    guardrail_type: GuardrailType,
    trace_ids: List[str],
    pattern_ids: List[str],
) -> str:
    """Build the generation prompt for a guardrail draft.

    Inputs must already be sanitized (no raw PII) before calling this builder.

    Args:
        suggestion: The suggestion document (sanitized)
        canonical_pattern: The canonical pattern document (sanitized)
        guardrail_type: Pre-determined guardrail type from failure type mapping
        trace_ids: All contributing trace IDs
        pattern_ids: All contributing pattern IDs

    Returns:
        The fully constructed prompt string
    """
    suggestion_id = suggestion.get("suggestion_id", "")
    pattern_summary = suggestion.get("pattern", {}) or {}

    failure_type = pattern_summary.get(
        "failure_type", canonical_pattern.get("failure_type", "unknown")
    )
    trigger_condition = pattern_summary.get(
        "trigger_condition", canonical_pattern.get("trigger_condition", "")
    )
    severity = pattern_summary.get("severity", canonical_pattern.get("severity", ""))
    summary = pattern_summary.get("summary", canonical_pattern.get("summary", ""))

    root_cause = canonical_pattern.get("root_cause_hypothesis", "")
    evidence = canonical_pattern.get("evidence", {}) or {}
    evidence_signals = evidence.get("signals", [])
    reproduction_context = canonical_pattern.get("reproduction_context", {}) or {}

    input_pattern = reproduction_context.get("input_pattern", "")
    required_state = reproduction_context.get("required_state", "")

    example_config = EXAMPLE_CONFIGURATIONS.get(guardrail_type, {})

    return f"""
You are generating a structured JSON guardrail rule draft for Evalforge.

IMPORTANT CONSTRAINTS:
- Output MUST be a single JSON object (no markdown, no prose).
- Do NOT include raw PII (emails, phone numbers, user IDs, access tokens). Use placeholders like [EMAIL_REDACTED].
- Generate SPECIFIC configuration values (concrete thresholds, limits, patterns) - NOT placeholders.
- Include a plain-language justification explaining WHY this guardrail prevents the failure recurrence.
- If the available context is insufficient to generate actionable configuration, set `status` to `needs_human_input`
  and include descriptive placeholders in the configuration.

FAILURE CONTEXT:
- suggestion_id: {suggestion_id}
- failure_type: {failure_type}
- trigger_condition: {trigger_condition}
- severity: {severity}
- failure_summary: {summary}
- root_cause_hypothesis: {root_cause}
- evidence_signals: {evidence_signals}
- reproduction_context.input_pattern: {input_pattern}
- reproduction_context.required_state: {required_state}
- lineage.trace_ids: {trace_ids}
- lineage.pattern_ids: {pattern_ids}

GUARDRAIL TYPE: {guardrail_type.value}
(This guardrail type was pre-determined based on the failure type mapping)

EXAMPLE CONFIGURATION for {guardrail_type.value}:
{example_config}

TASK:
Generate a JSON object with these fields:
- rule_name (string): Descriptive snake_case name, max 100 chars (e.g., "block_runaway_api_calls")
- description (string): What this guardrail prevents, max 500 chars
- justification (string): Plain-language explanation of WHY this prevents the failure recurrence, max 800 chars
- configuration (object): Type-specific configuration with CONCRETE values (see example above)
- estimated_prevention_rate (number): 0.0-1.0, your confidence this guardrail would prevent similar failures
- status: one of ["draft", "needs_human_input"]

Focus on:
1. Making the configuration immediately actionable (specific thresholds, not "appropriate value")
2. Explaining the prevention mechanism in justification (connect the guardrail to the failure pattern)
3. Being conservative with estimated_prevention_rate (0.7-0.9 for well-understood patterns)
""".strip()


def build_needs_human_input_prompt_context(
    failure_type: str,
    guardrail_type: GuardrailType,
    reason: str,
) -> str:
    """Build context string for template fallback drafts.

    Used when Gemini is unavailable or context is insufficient.
    """
    return f"""
Guardrail draft requires human input.

Failure Type: {failure_type}
Guardrail Type: {guardrail_type.value}
Reason: {reason}

Please review the source patterns and complete the configuration manually.
""".strip()
