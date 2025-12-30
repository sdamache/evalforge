"""Prompt templates for SRE runbook draft generation.

Generates operational runbooks following SRE best practices with 6 sections:
- Summary
- Symptoms
- Diagnosis Steps
- Immediate Mitigation
- Root Cause Fix
- Escalation
"""

from __future__ import annotations

from typing import Any, Dict, List


# Failure-type-specific diagnostic command suggestions
FAILURE_TYPE_DIAGNOSTICS: Dict[str, List[str]] = {
    "hallucination": [
        'datadog trace search "service:llm-agent @failure_type:hallucination"',
        "curl -s llm-observability/quality-scores | jq '.recent_failures'",
        'grep -r "confidence_score" logs/ | awk \'$NF < 0.5\'',
    ],
    "stale_data": [
        'datadog trace search "service:llm-agent @failure_type:stale_data"',
        "curl -s cache-service/sync-status | jq '.last_sync_at'",
        "redis-cli TTL product_catalog:*",
    ],
    "prompt_injection": [
        'datadog trace search "service:llm-agent @failure_type:prompt_injection"',
        "curl -s guardrails-api/violations?type=injection | jq '.count'",
        'grep -r "injection_detected" security-logs/',
    ],
    "toxicity": [
        'datadog trace search "service:llm-agent @failure_type:toxicity"',
        "curl -s content-moderation/violations | jq '.recent'",
        "aws cloudwatch get-metric-statistics --metric-name ToxicityScore",
    ],
    "guardrail_failure": [
        'datadog trace search "service:guardrails @status:error"',
        "curl -s guardrails-api/health | jq '.failed_rules'",
        "kubectl logs -l app=guardrails --since=1h | grep ERROR",
    ],
    "infrastructure_error": [
        'datadog trace search "service:llm-agent @http.status_code:5*"',
        "kubectl describe pod -l app=llm-agent",
        "aws cloudwatch get-metric-statistics --metric-name ErrorRate",
    ],
    "quality_degradation": [
        'datadog trace search "service:llm-agent @quality_score:<0.5"',
        "curl -s observability/quality-trends | jq '.weekly_average'",
        "prometheus query 'avg(llm_quality_score) by (model)'",
    ],
}

DEFAULT_DIAGNOSTICS = [
    'datadog trace search "service:llm-agent @status:error"',
    "kubectl logs -l app=llm-agent --since=1h | grep -i error",
    "curl -s observability/health | jq '.'",
]


def build_runbook_generation_prompt(
    *,
    suggestion: Dict[str, Any],
    canonical_pattern: Dict[str, Any],
    trace_ids: List[str],
    pattern_ids: List[str],
) -> str:
    """Build the generation prompt for a runbook draft.

    Generates SRE-standard runbook with 6 sections and specific diagnostic
    commands based on failure type.

    Inputs must already be sanitized (no raw PII) before calling this builder.

    Args:
        suggestion: Sanitized suggestion document
        canonical_pattern: Primary failure pattern with reproduction context
        trace_ids: All contributing trace IDs for lineage (FR-007)
        pattern_ids: All contributing pattern IDs for lineage (FR-007)

    Returns:
        Prompt string for Gemini runbook generation
    """
    suggestion_id = suggestion.get("suggestion_id", "")
    pattern_summary = suggestion.get("pattern", {}) or {}

    failure_type = pattern_summary.get("failure_type", canonical_pattern.get("failure_type", "unknown"))
    trigger_condition = pattern_summary.get("trigger_condition", canonical_pattern.get("trigger_condition", ""))
    summary = pattern_summary.get("summary", canonical_pattern.get("summary", ""))
    severity = pattern_summary.get("severity", canonical_pattern.get("severity", "medium"))
    title = pattern_summary.get("title", canonical_pattern.get("title", f"{failure_type} Failure"))

    root_cause = canonical_pattern.get("root_cause_hypothesis", "")
    evidence = canonical_pattern.get("evidence", {}) or {}
    evidence_signals = evidence.get("signals", [])
    reproduction_context = canonical_pattern.get("reproduction_context", {}) or {}

    input_pattern = reproduction_context.get("input_pattern", "")
    required_state = reproduction_context.get("required_state", "")
    tools_involved = reproduction_context.get("tools_involved", [])

    # Get failure-type-specific diagnostic commands
    diagnostic_suggestions = FAILURE_TYPE_DIAGNOSTICS.get(failure_type, DEFAULT_DIAGNOSTICS)

    # Build canonical trace reference
    canonical_trace_id = trace_ids[0] if trace_ids else "unknown"

    return f"""
You are generating an SRE operational runbook for Evalforge.

IMPORTANT CONSTRAINTS:
- Output MUST be a single JSON object (no markdown wrapping, no prose outside JSON).
- The `markdown_content` field MUST contain valid Markdown with ALL 6 sections below.
- Do NOT include raw PII (emails, phone numbers, user IDs, access tokens).
- Include at least 2 SPECIFIC diagnostic commands in `diagnosis_commands` (not just "check logs").
- The runbook should be immediately actionable by an on-call engineer.
- If the available context is insufficient, set `status` to `needs_human_input`.

RUNBOOK TEMPLATE STRUCTURE (must appear in markdown_content):
```markdown
# {{Failure Type}} - Operational Runbook

**Source Incident**: `{{trace_id}}`
**Severity**: {{severity}}
**Generated**: {{timestamp}}

---

## Summary
Brief description of the failure mode (1-2 sentences).

## Symptoms
Observable indicators that this failure is occurring:
- Symptom 1 (with metric/log pattern to check)
- Symptom 2 (with specific error message)

## Diagnosis Steps
1. **Check X** using command: `specific_command_here`
2. **Verify Y** in dashboard: [Dashboard Link](url)
3. **Review Z logs**: Look for pattern `{{specific_pattern}}`

## Immediate Mitigation
Actions to reduce customer impact right now:
1. **Step 1**: Specific action with command/API call
2. **Step 2**: Validation step to confirm mitigation worked

## Root Cause Fix
Long-term fix to prevent recurrence:
1. **Code change**: Modify `{{file}}` to add `{{check}}`
2. **Deploy guardrail**: Apply guardrail rule `{{rule_name}}`

## Escalation
- **When to escalate**: If diagnosis steps don't confirm root cause within 15 minutes
- **Who to contact**: #team-llm-ops in Slack
- **Escalation threshold**: Customer impact >100 users OR downtime >30 minutes

---

*Auto-generated by EvalForge from production failure patterns.*
```

CONTEXT:
- suggestion_id: {suggestion_id}
- canonical_trace_id: {canonical_trace_id}
- failure_type: {failure_type}
- severity: {severity}
- title: {title}
- trigger_condition: {trigger_condition}
- failure_summary: {summary}
- root_cause_hypothesis: {root_cause}
- evidence_signals: {evidence_signals}
- reproduction_context.input_pattern: {input_pattern}
- reproduction_context.required_state: {required_state}
- reproduction_context.tools_involved: {tools_involved}
- lineage.trace_ids: {trace_ids}
- lineage.pattern_ids: {pattern_ids}

SUGGESTED DIAGNOSTIC COMMANDS for {failure_type}:
{chr(10).join(f'- {cmd}' for cmd in diagnostic_suggestions)}

TASK:
Generate a JSON object with these fields:
- title (string): Runbook title, e.g., "{{failure_type}} - Operational Runbook"
- rationale (string): Plain-language explanation of why this runbook was generated, citing the source trace ID ({canonical_trace_id}) and what incident it addresses. This helps reviewers understand the context.
- markdown_content (string): Full Markdown content following the template structure above
- symptoms (array[string]): Observable indicators (minimum 1)
- diagnosis_commands (array[string]): Specific commands/queries for diagnosis (minimum 2)
- mitigation_steps (array[string]): Immediate actions to reduce impact
- escalation_criteria (string): When/who/threshold for escalation
- status: one of ["draft", "needs_human_input"]
""".strip()
