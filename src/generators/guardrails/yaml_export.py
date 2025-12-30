"""YAML export utility for Datadog AI Guard compatibility.

Converts GuardrailDraft models to Datadog-compatible YAML structure.
Excludes internal metadata (generator_meta, source) for deployment use.

Usage:
    from src.generators.guardrails.yaml_export import guardrail_to_yaml, guardrail_to_yaml_dict

    yaml_str = guardrail_to_yaml(draft)
    yaml_dict = guardrail_to_yaml_dict(draft)
"""

from typing import Any, Dict

import yaml

from .models import GuardrailDraft


def guardrail_to_yaml_dict(draft: GuardrailDraft) -> Dict[str, Any]:
    """Convert GuardrailDraft to Datadog AI Guard compatible dict.

    Includes only deployment-relevant fields:
    - rule_name
    - guardrail_type
    - configuration
    - description
    - justification (as comment/note)
    - estimated_prevention_rate
    - status

    Excludes internal metadata:
    - generator_meta
    - source
    - edit_source
    - generated_at/updated_at
    - guardrail_id

    Args:
        draft: The GuardrailDraft to convert

    Returns:
        Dict suitable for YAML serialization in Datadog format
    """
    return {
        "rule_name": draft.rule_name,
        "type": draft.guardrail_type.value,
        "description": draft.description,
        "configuration": draft.configuration,
        "justification": draft.justification,
        "failure_type": draft.failure_type,
        "estimated_prevention_rate": draft.estimated_prevention_rate,
        "status": draft.status.value,
    }


def guardrail_to_yaml(draft: GuardrailDraft) -> str:
    """Convert GuardrailDraft to YAML string.

    Args:
        draft: The GuardrailDraft to convert

    Returns:
        YAML formatted string suitable for Datadog AI Guard
    """
    yaml_dict = guardrail_to_yaml_dict(draft)
    return yaml.dump(
        yaml_dict,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
