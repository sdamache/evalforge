"""Export format generators for approved suggestions.

Generates CI-ready exports in DeepEval JSON, Pytest, and YAML formats.
Per research.md, DeepEval uses the 9-parameter LLMTestCase schema.
"""

from __future__ import annotations

import ast
import json
from typing import Any, Optional

import yaml

from src.common.logging import get_logger

logger = get_logger(__name__)


class ExportError(Exception):
    """Raised when export generation fails."""

    pass


class ContentMissingError(ExportError):
    """Raised when suggestion_content is missing required fields."""

    pass


# =============================================================================
# DeepEval JSON Exporter (T018)
# =============================================================================


def export_deepeval(suggestion: dict[str, Any]) -> str:
    """Generate DeepEval-compatible JSON from an approved suggestion.

    DeepEval LLMTestCase schema (from research.md):
    - input: User input/query to the LLM (required)
    - actual_output: The LLM's actual response (required)
    - expected_output: Ideal/ground truth output (optional)
    - context: Static knowledge base segments (optional)
    - retrieval_context: Dynamic RAG retrieval results (optional)

    Args:
        suggestion: Suggestion document from Firestore.

    Returns:
        JSON string containing DeepEval test case array.

    Raises:
        ContentMissingError: If suggestion_content lacks required fields.
    """
    content = suggestion.get("suggestion_content", {})
    eval_test = content.get("eval_test", {})

    if not eval_test:
        raise ContentMissingError(
            "suggestion_content.eval_test is missing or empty"
        )

    # Extract input from eval_test structure
    input_data = eval_test.get("input", {})
    input_text = input_data.get("prompt", "")

    if not input_text:
        raise ContentMissingError(
            "suggestion_content.eval_test.input.prompt is missing"
        )

    # Build DeepEval test case
    test_case = {
        "input": input_text,
        "actual_output": "",  # To be filled during test execution
    }

    # Add expected_output from assertions if available
    assertions = eval_test.get("assertions", {})
    required = assertions.get("required", [])
    if required:
        # Use first required assertion as expected output hint
        test_case["expected_output"] = required[0]

    # Add context from pattern if available
    pattern = suggestion.get("pattern", {})
    if pattern:
        context_items = []
        if pattern.get("trigger_condition"):
            context_items.append(f"Trigger: {pattern['trigger_condition']}")
        if pattern.get("failure_type"):
            context_items.append(f"Failure type: {pattern['failure_type']}")
        if context_items:
            test_case["context"] = context_items

    # Add retrieval_context from source_traces if available
    source_traces = suggestion.get("source_traces", [])
    if source_traces:
        test_case["retrieval_context"] = [
            f"Source trace: {trace}" for trace in source_traces[:5]
        ]

    # Wrap in array as per DeepEval dataset format
    result = json.dumps([test_case], indent=2)

    # Validate JSON is parseable
    try:
        json.loads(result)
    except json.JSONDecodeError as e:
        raise ExportError(f"Generated invalid JSON: {e}")

    logger.debug(
        "Generated DeepEval export",
        extra={"suggestion_id": suggestion.get("suggestion_id")},
    )

    return result


# =============================================================================
# Pytest Exporter (T019)
# =============================================================================


def export_pytest(suggestion: dict[str, Any]) -> str:
    """Generate syntactically valid Python pytest code from an approved suggestion.

    Args:
        suggestion: Suggestion document from Firestore.

    Returns:
        Python test code string.

    Raises:
        ContentMissingError: If suggestion_content lacks required fields.
    """
    content = suggestion.get("suggestion_content", {})
    eval_test = content.get("eval_test", {})

    if not eval_test:
        raise ContentMissingError(
            "suggestion_content.eval_test is missing or empty"
        )

    suggestion_id = suggestion.get("suggestion_id", "unknown")
    title = eval_test.get("title", "Untitled test")
    input_data = eval_test.get("input", {})
    prompt = input_data.get("prompt", "")
    assertions = eval_test.get("assertions", {})
    required = assertions.get("required", [])
    forbidden = assertions.get("forbidden", [])

    # Build test function name from suggestion_id
    # Sanitize for valid Python identifier
    safe_id = suggestion_id.replace("-", "_").replace(".", "_")
    func_name = f"test_{safe_id}"

    # Build assertion code
    assertion_lines = []
    for req in required:
        # Escape quotes in assertion text
        escaped_req = req.replace('"', '\\"')
        assertion_lines.append(
            f'    # Required: {escaped_req}\n'
            f'    assert "{escaped_req}" in response or validate_requirement(response, "{escaped_req}")'
        )

    for forb in forbidden:
        escaped_forb = forb.replace('"', '\\"')
        assertion_lines.append(
            f'    # Forbidden: {escaped_forb}\n'
            f'    assert "{escaped_forb}" not in response'
        )

    if not assertion_lines:
        assertion_lines.append("    assert response is not None  # Basic validation")

    assertions_code = "\n".join(assertion_lines)
    escaped_prompt = prompt.replace('"""', '\\"\\"\\"')
    escaped_title = title.replace('"', '\\"')

    # Generate Python code
    code = f'''"""Auto-generated pytest test for: {escaped_title}

Generated from EvalForge suggestion: {suggestion_id}
"""

import pytest


def validate_requirement(response: str, requirement: str) -> bool:
    """Validate that response meets the requirement.

    Implement custom validation logic here.
    """
    # TODO: Implement semantic validation
    return requirement.lower() in response.lower()


def {func_name}():
    """{escaped_title}

    Suggestion ID: {suggestion_id}
    """
    # Input prompt
    prompt = """{escaped_prompt}"""

    # TODO: Replace with actual LLM call
    response = call_llm(prompt)

{assertions_code}


def call_llm(prompt: str) -> str:
    """Placeholder for LLM invocation.

    Replace with your actual LLM client call.
    """
    raise NotImplementedError("Implement call_llm with your LLM client")
'''

    # Validate Python syntax
    try:
        ast.parse(code)
    except SyntaxError as e:
        raise ExportError(f"Generated invalid Python syntax: {e}")

    logger.debug(
        "Generated Pytest export",
        extra={"suggestion_id": suggestion_id, "func_name": func_name},
    )

    return code


# =============================================================================
# YAML Exporter (T020)
# =============================================================================


def export_yaml(suggestion: dict[str, Any]) -> str:
    """Generate valid YAML configuration from an approved suggestion.

    Args:
        suggestion: Suggestion document from Firestore.

    Returns:
        YAML configuration string.

    Raises:
        ContentMissingError: If suggestion_content lacks required fields.
    """
    content = suggestion.get("suggestion_content", {})
    eval_test = content.get("eval_test", {})

    if not eval_test:
        raise ContentMissingError(
            "suggestion_content.eval_test is missing or empty"
        )

    suggestion_id = suggestion.get("suggestion_id", "unknown")
    suggestion_type = suggestion.get("type", "eval")
    pattern = suggestion.get("pattern", {})

    # Build YAML structure
    yaml_data = {
        "evalforge_test": {
            "metadata": {
                "suggestion_id": suggestion_id,
                "type": suggestion_type,
                "generated_by": "evalforge-approval-workflow",
            },
            "test_case": {
                "title": eval_test.get("title", "Untitled"),
                "input": eval_test.get("input", {}),
                "assertions": eval_test.get("assertions", {}),
            },
        }
    }

    # Add pattern info if available
    if pattern:
        yaml_data["evalforge_test"]["pattern"] = {
            "failure_type": pattern.get("failure_type"),
            "severity": pattern.get("severity"),
            "trigger_condition": pattern.get("trigger_condition"),
        }

    # Add source traces
    source_traces = suggestion.get("source_traces", [])
    if source_traces:
        yaml_data["evalforge_test"]["metadata"]["source_traces"] = source_traces

    # Generate YAML
    result = yaml.dump(
        yaml_data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )

    # Validate YAML is loadable
    try:
        yaml.safe_load(result)
    except yaml.YAMLError as e:
        raise ExportError(f"Generated invalid YAML: {e}")

    logger.debug(
        "Generated YAML export",
        extra={"suggestion_id": suggestion_id},
    )

    return result


# =============================================================================
# Format Dispatcher
# =============================================================================


EXPORTERS = {
    "deepeval": export_deepeval,
    "pytest": export_pytest,
    "yaml": export_yaml,
}


def export_suggestion(
    suggestion: dict[str, Any],
    format: str = "deepeval",
) -> tuple[str, str]:
    """Export a suggestion in the requested format.

    Args:
        suggestion: Suggestion document from Firestore.
        format: Export format (deepeval, pytest, yaml).

    Returns:
        Tuple of (content, content_type).

    Raises:
        ValueError: If format is not supported.
        ContentMissingError: If suggestion lacks required content.
        ExportError: If export generation fails.
    """
    if format not in EXPORTERS:
        raise ValueError(f"Unsupported export format: {format}")

    exporter = EXPORTERS[format]
    content = exporter(suggestion)

    # Map format to content type
    content_types = {
        "deepeval": "application/json",
        "pytest": "text/x-python",
        "yaml": "application/x-yaml",
    }

    return content, content_types[format]
