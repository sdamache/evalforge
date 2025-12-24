#!/usr/bin/env python3
"""Evaluation script for failure pattern extraction accuracy (AC1).

Reads labeled sample spans from tests/data/extraction/sample_failure_spans.json,
runs extraction, and scores results based on:
- Correct failure_type match
- Correct trigger_condition (matches any expected keyword)

NOTE: Each entry in the sample file represents a single LLM span (not a complete
multi-span trace). See the file's _comment field for terminology clarification.

Target: >=8/10 (80%) accuracy per AC1.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from src.common.config import load_extraction_settings
from src.extraction.firestore_repository import create_firestore_repository
from src.extraction.gemini_client import create_gemini_client, GeminiClientError
from src.extraction.models import FailureType, TriggeredBy
from src.extraction.prompt_templates import build_extraction_prompt
from src.extraction.trace_utils import prepare_trace_for_extraction


SAMPLE_SPANS_PATH = PROJECT_ROOT / "tests" / "data" / "extraction" / "sample_failure_spans.json"


def load_sample_spans() -> List[Dict[str, Any]]:
    """Load labeled sample spans from JSON file.

    Each entry represents a single LLM span with expected failure classification.
    """
    with open(SAMPLE_SPANS_PATH) as f:
        data = json.load(f)
    return data["spans"]


def score_failure_type(expected: str, actual: str) -> Tuple[bool, str]:
    """Score failure_type match.

    Returns:
        Tuple of (is_correct, explanation)
    """
    if expected.lower() == actual.lower():
        return True, f"Correct: {actual}"
    return False, f"Expected '{expected}', got '{actual}'"


def score_trigger_condition(expected_keywords: List[str], actual: str) -> Tuple[bool, str]:
    """Score trigger_condition by checking if any expected keyword is present.

    Returns:
        Tuple of (is_correct, explanation)
    """
    actual_lower = actual.lower()
    matched_keywords = [kw for kw in expected_keywords if kw.lower() in actual_lower]

    if matched_keywords:
        return True, f"Matched keywords: {matched_keywords}"
    return False, f"No keywords matched. Expected one of: {expected_keywords}"


def evaluate_single_span(
    span: Dict[str, Any],
    gemini_client,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Evaluate extraction on a single span.

    Returns:
        Dict with span's trace_id, expected, actual, scores, and explanations.
    """
    trace_id = span["trace_id"]  # Document ID in our pipeline
    expected = span["expected"]

    result = {
        "trace_id": trace_id,
        "expected_failure_type": expected["failure_type"],
        "expected_trigger_keywords": expected["trigger_condition_keywords"],
        "actual_failure_type": None,
        "actual_trigger_condition": None,
        "failure_type_correct": False,
        "trigger_condition_correct": False,
        "failure_type_explanation": "",
        "trigger_condition_explanation": "",
        "error": None,
    }

    try:
        # Prepare span for extraction (uses trace_payload field)
        prepared_payload, _ = prepare_trace_for_extraction(span)

        # Build prompt and call Gemini
        prompt = build_extraction_prompt(prepared_payload)
        response = gemini_client.extract_pattern(prompt)

        # Extract results
        parsed = response.parsed_json
        result["actual_failure_type"] = parsed.get("failure_type", "")
        result["actual_trigger_condition"] = parsed.get("trigger_condition", "")

        # Score failure_type
        ft_correct, ft_explanation = score_failure_type(
            expected["failure_type"],
            result["actual_failure_type"],
        )
        result["failure_type_correct"] = ft_correct
        result["failure_type_explanation"] = ft_explanation

        # Score trigger_condition
        tc_correct, tc_explanation = score_trigger_condition(
            expected["trigger_condition_keywords"],
            result["actual_trigger_condition"],
        )
        result["trigger_condition_correct"] = tc_correct
        result["trigger_condition_explanation"] = tc_explanation

    except GeminiClientError as e:
        result["error"] = f"Gemini error: {e}"
    except Exception as e:
        result["error"] = f"Unexpected error: {e}"

    if verbose:
        print(f"\n--- {trace_id} ---")
        print(f"Expected failure_type: {expected['failure_type']}")
        print(f"Actual failure_type: {result['actual_failure_type']}")
        print(f"  -> {result['failure_type_explanation']}")
        print(f"Expected trigger keywords: {expected['trigger_condition_keywords']}")
        print(f"Actual trigger_condition: {result['actual_trigger_condition']}")
        print(f"  -> {result['trigger_condition_explanation']}")
        if result["error"]:
            print(f"ERROR: {result['error']}")

    return result


def run_evaluation(verbose: bool = False, max_spans: int = None) -> Dict[str, Any]:
    """Run evaluation on all sample spans.

    Args:
        verbose: Print detailed results for each span.
        max_spans: Limit number of spans to evaluate.

    Returns:
        Dict with overall scores and per-span results.
    """
    print("Loading sample spans...")
    spans = load_sample_spans()

    if max_spans:
        spans = spans[:max_spans]

    print(f"Loaded {len(spans)} spans")

    print("Initializing Gemini client...")
    settings = load_extraction_settings()
    gemini_client = create_gemini_client(settings.gemini)

    print(f"Using model: {settings.gemini.model}")
    print(f"Temperature: {settings.gemini.temperature}")
    print()

    results = []
    for i, span in enumerate(spans, 1):
        print(f"Evaluating span {i}/{len(spans)}: {span['trace_id']}...")
        result = evaluate_single_span(span, gemini_client, verbose)
        results.append(result)

    # Calculate overall scores
    total = len(results)
    errors = sum(1 for r in results if r["error"])
    successful = total - errors

    failure_type_correct = sum(1 for r in results if r["failure_type_correct"])
    trigger_correct = sum(1 for r in results if r["trigger_condition_correct"])
    both_correct = sum(
        1 for r in results
        if r["failure_type_correct"] and r["trigger_condition_correct"]
    )

    summary = {
        "total_traces": total,
        "successful_extractions": successful,
        "errors": errors,
        "failure_type_accuracy": failure_type_correct / successful if successful > 0 else 0,
        "trigger_condition_accuracy": trigger_correct / successful if successful > 0 else 0,
        "both_correct_accuracy": both_correct / successful if successful > 0 else 0,
        "failure_type_correct_count": failure_type_correct,
        "trigger_condition_correct_count": trigger_correct,
        "both_correct_count": both_correct,
        "target_accuracy": 0.8,  # AC1: >=80%
        "passes_ac1": both_correct / successful >= 0.8 if successful > 0 else False,
    }

    return {
        "summary": summary,
        "results": results,
    }


def print_summary(evaluation: Dict[str, Any]) -> None:
    """Print evaluation summary."""
    summary = evaluation["summary"]

    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Total traces: {summary['total_traces']}")
    print(f"Successful extractions: {summary['successful_extractions']}")
    print(f"Errors: {summary['errors']}")
    print()
    print(f"Failure type accuracy: {summary['failure_type_accuracy']:.1%} ({summary['failure_type_correct_count']}/{summary['successful_extractions']})")
    print(f"Trigger condition accuracy: {summary['trigger_condition_accuracy']:.1%} ({summary['trigger_condition_correct_count']}/{summary['successful_extractions']})")
    print(f"Both correct accuracy: {summary['both_correct_accuracy']:.1%} ({summary['both_correct_count']}/{summary['successful_extractions']})")
    print()
    print(f"Target (AC1): {summary['target_accuracy']:.0%}")
    print(f"PASSES AC1: {'YES' if summary['passes_ac1'] else 'NO'}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Evaluate failure pattern extraction accuracy")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print detailed results")
    parser.add_argument("-n", "--max-spans", type=int, help="Limit number of spans to evaluate")
    parser.add_argument("-o", "--output", type=str, help="Output JSON file for results")
    args = parser.parse_args()

    try:
        evaluation = run_evaluation(verbose=args.verbose, max_spans=args.max_spans)
        print_summary(evaluation)

        if args.output:
            with open(args.output, "w") as f:
                json.dump(evaluation, f, indent=2, default=str)
            print(f"\nDetailed results written to: {args.output}")

        # Exit with appropriate code
        sys.exit(0 if evaluation["summary"]["passes_ac1"] else 1)

    except Exception as e:
        print(f"Evaluation failed: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
