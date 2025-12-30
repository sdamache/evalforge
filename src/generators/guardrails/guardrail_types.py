"""Guardrail type mapping from failure types.

This module provides the deterministic mapping from failure_type to guardrail_type
used by the guardrail generator to select the appropriate guardrail category.

Mapping version is tracked for auditability in generator_meta.
"""

from enum import Enum
from typing import Dict

# Version for tracking mapping changes in generator_meta
GUARDRAIL_MAPPING_VERSION = "1.0"


class GuardrailType(str, Enum):
    """Types of guardrails that can be generated."""

    VALIDATION_RULE = "validation_rule"
    RATE_LIMIT = "rate_limit"
    CONTENT_FILTER = "content_filter"
    REDACTION_RULE = "redaction_rule"
    SCOPE_LIMIT = "scope_limit"
    FRESHNESS_CHECK = "freshness_check"
    INPUT_SANITIZATION = "input_sanitization"


# Deterministic mapping from failure_type to guardrail_type
# Default fallback is validation_rule for unmapped types
GUARDRAIL_MAPPING: Dict[str, GuardrailType] = {
    "hallucination": GuardrailType.VALIDATION_RULE,
    "toxicity": GuardrailType.CONTENT_FILTER,
    "runaway_loop": GuardrailType.RATE_LIMIT,
    "pii_leak": GuardrailType.REDACTION_RULE,
    "wrong_tool": GuardrailType.SCOPE_LIMIT,
    "stale_data": GuardrailType.FRESHNESS_CHECK,
    "prompt_injection": GuardrailType.INPUT_SANITIZATION,
}

# Default guardrail type for unmapped failure types
DEFAULT_GUARDRAIL_TYPE = GuardrailType.VALIDATION_RULE


def get_guardrail_type(failure_type: str) -> GuardrailType:
    """Get the guardrail type for a given failure type.

    Args:
        failure_type: The failure type from the suggestion

    Returns:
        The corresponding guardrail type, or DEFAULT_GUARDRAIL_TYPE if unmapped
    """
    return GUARDRAIL_MAPPING.get(failure_type, DEFAULT_GUARDRAIL_TYPE)
