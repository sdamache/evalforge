"""Few-shot prompt template builder for failure pattern extraction.

This module builds prompts for Gemini to extract structured failure patterns
from production LLM traces. Uses few-shot examples to guide the model on
field semantics and constrain outputs to the expected schema.
"""

import hashlib
import json
from typing import Any, Dict

from src.extraction.models import FailureType, Severity


# ============================================================================
# System Prompt
# ============================================================================

SYSTEM_PROMPT = """You are an expert LLM failure analyst. Your task is to analyze production failure traces from LLM applications and extract structured failure patterns.

For each trace, you must identify:
1. **Title**: A concise, descriptive title for the failure pattern (max 100 chars)
2. **Failure Type**: Categorize into one of the standardized types
3. **Trigger Condition**: What specific input/state triggered this failure
4. **Summary**: 1-2 sentence description of what happened
5. **Root Cause Hypothesis**: Your best explanation for WHY this failed
6. **Evidence**: Specific signals from the trace that support your analysis
7. **Recommended Actions**: Concrete steps to prevent/mitigate this failure
8. **Reproduction Context**: How to reproduce this issue
9. **Severity**: Impact level (low/medium/high/critical)
10. **Confidence**: How confident you are in your analysis (0.0-1.0)
11. **Confidence Rationale**: Brief explanation of what influenced your confidence

## Failure Type Definitions

- **hallucination**: Model generated factually incorrect or fabricated information
- **toxicity**: Model produced harmful, offensive, or inappropriate content
- **wrong_tool**: Model called the wrong tool or used incorrect tool parameters
- **runaway_loop**: Model got stuck in a repetitive loop or infinite recursion
- **pii_leak**: Model exposed personally identifiable information inappropriately
- **stale_data**: Model used outdated information leading to incorrect responses
- **infrastructure_error**: Backend/infrastructure failure (timeouts, rate limits, etc.)
- **client_error**: Invalid request from client (bad input format, missing required fields)

## Evidence Guidelines

- **signals**: List specific, concrete signals from the trace (error codes, latency values, token counts, etc.)
- **excerpt**: Optional short redacted snippet (NEVER include full prompts/responses or PII)

## Confidence Guidelines

- **0.9-1.0**: Very high - Clear evidence, obvious pattern, unambiguous failure type
- **0.7-0.9**: High - Strong evidence, pattern is clear but some ambiguity
- **0.5-0.7**: Medium - Moderate evidence, reasonable hypothesis but alternatives exist
- **0.3-0.5**: Low - Limited evidence, best guess based on available data
- **0.0-0.3**: Very low - Insufficient evidence, highly speculative

Analyze the trace carefully and provide your structured assessment."""


# ============================================================================
# Few-Shot Examples
# ============================================================================

FEW_SHOT_EXAMPLES = [
    # Example 1: Hallucination
    {
        "input": {
            "trace_id": "abc123",
            "failure_type": "llm_error",
            "severity": "high",
            "trace_payload": {
                "model": "gpt-4",
                "prompt": "What is the capital of Australia?",
                "response": "The capital of Australia is Sydney, which is also the largest city.",
                "error": None,
                "latency_ms": 450,
                "tokens_used": 52,
            },
        },
        "output": {
            "title": "Incorrect capital city hallucination",
            "failure_type": "hallucination",
            "trigger_condition": "Factual geography question",
            "summary": "Model incorrectly stated Sydney as Australia's capital when it is actually Canberra.",
            "root_cause_hypothesis": "Model conflated 'largest city' with 'capital city', a common misconception in training data.",
            "evidence": {
                "signals": ["response contains 'Sydney' instead of 'Canberra'", "no error raised", "normal latency 450ms"],
                "excerpt": "capital of Australia is Sydney",
            },
            "recommended_actions": [
                "Add fact-checking layer for geographical questions",
                "Include explicit capital city validation in response pipeline",
            ],
            "reproduction_context": {
                "input_pattern": "What is the capital of [country]?",
                "required_state": None,
                "tools_involved": [],
            },
            "severity": "high",
            "confidence": 0.95,
            "confidence_rationale": "Clear factual error with unambiguous correct answer; high confidence this is hallucination.",
        },
    },
    # Example 2: Wrong Tool
    {
        "input": {
            "trace_id": "def456",
            "failure_type": "tool_error",
            "severity": "medium",
            "trace_payload": {
                "model": "gpt-4",
                "prompt": "Search for the latest news about AI",
                "tool_calls": [{"tool": "calculator", "input": "latest news AI"}],
                "error": "Calculator cannot process text input",
                "latency_ms": 120,
            },
        },
        "output": {
            "title": "Calculator tool called for news search task",
            "failure_type": "wrong_tool",
            "trigger_condition": "News search request routed to calculator",
            "summary": "Model incorrectly selected calculator tool for a web search task, causing an error.",
            "root_cause_hypothesis": "Tool selection logic failed to match search intent to web_search tool, possibly due to ambiguous tool descriptions.",
            "evidence": {
                "signals": ["tool_calls contains calculator", "error: Calculator cannot process text", "search intent in prompt"],
                "excerpt": "tool: calculator, input: latest news AI",
            },
            "recommended_actions": [
                "Improve tool descriptions to clarify use cases",
                "Add intent classification before tool selection",
                "Implement tool call validation layer",
            ],
            "reproduction_context": {
                "input_pattern": "Search for [topic]",
                "required_state": "Calculator and web_search tools both available",
                "tools_involved": ["calculator", "web_search"],
            },
            "severity": "medium",
            "confidence": 0.85,
            "confidence_rationale": "Clear wrong tool selection with explicit error; tool call evidence directly shows the issue.",
        },
    },
    # Example 3: Infrastructure Error
    {
        "input": {
            "trace_id": "ghi789",
            "failure_type": "infrastructure_error",
            "severity": "critical",
            "trace_payload": {
                "model": "gpt-4",
                "prompt": "Generate a report...",
                "error": "Rate limit exceeded: 429 Too Many Requests",
                "latency_ms": 5,
                "retry_count": 3,
            },
        },
        "output": {
            "title": "API rate limit exceeded after retries",
            "failure_type": "infrastructure_error",
            "trigger_condition": "High request volume exceeded API rate limits",
            "summary": "Request failed with 429 error after 3 retry attempts due to API rate limiting.",
            "root_cause_hypothesis": "Burst traffic exceeded provisioned rate limits; retry backoff may be insufficient.",
            "evidence": {
                "signals": ["error code 429", "retry_count: 3", "latency 5ms indicates immediate rejection"],
                "excerpt": "Rate limit exceeded: 429",
            },
            "recommended_actions": [
                "Implement exponential backoff with jitter",
                "Add request queuing for rate limit smoothing",
                "Consider increasing API tier or adding fallback provider",
            ],
            "reproduction_context": {
                "input_pattern": "Any request during high traffic period",
                "required_state": "API quota near or at limit",
                "tools_involved": [],
            },
            "severity": "critical",
            "confidence": 0.98,
            "confidence_rationale": "Explicit 429 error code with retry exhaustion; infrastructure error is definitive.",
        },
    },
]


# ============================================================================
# Prompt Builder
# ============================================================================


def build_extraction_prompt(trace_payload: Dict[str, Any]) -> str:
    """Build the full extraction prompt with system context and few-shot examples.

    Args:
        trace_payload: The sanitized trace payload to analyze.

    Returns:
        Complete prompt string ready for Gemini.
    """
    # Format few-shot examples
    examples_text = []
    for i, example in enumerate(FEW_SHOT_EXAMPLES, 1):
        examples_text.append(f"### Example {i}")
        examples_text.append("**Input Trace:**")
        examples_text.append(f"```json\n{json.dumps(example['input'], indent=2)}\n```")
        examples_text.append("**Expected Output:**")
        examples_text.append(f"```json\n{json.dumps(example['output'], indent=2)}\n```")
        examples_text.append("")

    # Build the full prompt
    prompt_parts = [
        SYSTEM_PROMPT,
        "",
        "## Few-Shot Examples",
        "",
        "\n".join(examples_text),
        "## Your Task",
        "",
        "Analyze the following production failure trace and extract a structured failure pattern.",
        "",
        "**Input Trace:**",
        f"```json\n{json.dumps(trace_payload, indent=2)}\n```",
        "",
        "Provide your analysis as a JSON object following the schema shown in the examples.",
    ]

    return "\n".join(prompt_parts)


def compute_prompt_hash(prompt: str) -> str:
    """Compute a SHA-256 hash of the prompt for logging/auditing.

    Args:
        prompt: The full prompt string.

    Returns:
        Hex-encoded SHA-256 hash (first 16 chars for brevity).
    """
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def get_failure_type_descriptions() -> Dict[str, str]:
    """Return descriptions for each failure type.

    Useful for documentation and prompt engineering.
    """
    return {
        FailureType.HALLUCINATION.value: "Model generated factually incorrect or fabricated information",
        FailureType.TOXICITY.value: "Model produced harmful, offensive, or inappropriate content",
        FailureType.WRONG_TOOL.value: "Model called the wrong tool or used incorrect tool parameters",
        FailureType.RUNAWAY_LOOP.value: "Model got stuck in a repetitive loop or infinite recursion",
        FailureType.PII_LEAK.value: "Model exposed personally identifiable information inappropriately",
        FailureType.STALE_DATA.value: "Model used outdated information leading to incorrect responses",
        FailureType.INFRASTRUCTURE_ERROR.value: "Backend/infrastructure failure (timeouts, rate limits, etc.)",
        FailureType.CLIENT_ERROR.value: "Invalid request from client (bad input format, missing fields)",
    }


def get_severity_descriptions() -> Dict[str, str]:
    """Return descriptions for each severity level."""
    return {
        Severity.LOW.value: "Minor issue with minimal user impact",
        Severity.MEDIUM.value: "Noticeable degradation but workaround exists",
        Severity.HIGH.value: "Significant impact on user experience",
        Severity.CRITICAL.value: "Complete failure or security/safety concern",
    }
