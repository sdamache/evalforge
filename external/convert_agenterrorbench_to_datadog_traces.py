#!/usr/bin/env python3
"""Convert AgentErrorBench trajectories to Datadog LLM Observability traces.

This script loads the AgentErrorBench dataset and uploads trajectories as
Datadog LLM Observability traces for ingestion by EvalForge.

Usage:
    python scripts/convert_agent_trajectories.py --upload --count 5
    python scripts/convert_agent_trajectories.py --list-failures
    python scripts/convert_agent_trajectories.py --preview 0
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from datasets import load_dataset
except ImportError:
    print("Error: 'datasets' package required. Install with: pip install datasets")
    sys.exit(1)


# Mapping from AgentErrorBench failure_types to EvalForge failure_types
FAILURE_TYPE_MAPPING = {
    # Hallucination-related
    "misalignment": "hallucination",  # Agent action doesn't match plan
    "planning_error": "hallucination",  # Wrong plan formulated
    "reasoning_error": "hallucination",  # Logic failure
    "knowledge_error": "hallucination",  # Factual error
    "hallucination": "hallucination",  # Direct mapping
    "causal_misattribution": "hallucination",  # Wrong cause identified
    "outcome_misinterpretation": "hallucination",  # Misread results
    "over_simplification": "hallucination",  # Oversimplified reasoning
    "progress_misjudge": "hallucination",  # Wrong progress assessment

    # Quality degradation
    "observation_error": "quality_degradation",  # Misinterpret observation
    "constraint_ignorance": "quality_degradation",  # Ignored constraints
    "inefficient_plan": "quality_degradation",  # Suboptimal approach
    "plan_inefficient": "quality_degradation",  # Suboptimal approach

    # Client/tool errors
    "tool_use_error": "client_error",  # Wrong tool selection
    "tool_execution_error": "client_error",  # Tool failed
    "parameter_error": "client_error",  # Wrong parameters
    "invalid_action": "client_error",  # Invalid action taken
    "impossible_action": "client_error",  # Impossible action attempted
    "environment_error": "client_error",  # Environment issue

    # Runaway/loop
    "repetition": "runaway_loop",  # Repeated actions
    "step_limit": "runaway_loop",  # Hit step limit (likely looping)

    # Infrastructure/LLM errors
    "early_termination": "llm_error",  # Stopped prematurely
    "timeout": "infrastructure_error",  # Took too long
}

# Severity mapping
SEVERITY_MAPPING = {
    "runaway_loop": "critical",
    "hallucination": "high",
    "client_error": "medium",
    "quality_degradation": "medium",
    "llm_error": "medium",
    "infrastructure_error": "high",
}


def load_agenterrorbench() -> List[Dict[str, Any]]:
    """Load AgentErrorBench dataset from HuggingFace."""
    print("Loading AgentErrorBench dataset...")
    dataset = load_dataset("davide221/agenterrorbench", split="train")
    print(f"Loaded {len(dataset)} trajectories")
    return list(dataset)


def parse_trajectory(raw_trajectory: str) -> List[Dict[str, Any]]:
    """Parse the full_trajectory JSON string into steps."""
    try:
        trajectory = json.loads(raw_trajectory)
        return trajectory.get("messages", [])
    except json.JSONDecodeError:
        return []


def map_failure_type(failure_types: List[str]) -> tuple[str, str]:
    """Map AgentErrorBench failure types to EvalForge types."""
    if not failure_types:
        return "unknown", "medium"

    # Use the first failure type for classification
    primary_failure = failure_types[0].lower()

    for key, value in FAILURE_TYPE_MAPPING.items():
        if key in primary_failure:
            severity = SEVERITY_MAPPING.get(value, "medium")
            return value, severity

    return "unknown", "medium"


def trajectory_to_datadog_trace(
    trajectory_data: Dict[str, Any],
    ml_app: str = "agent-error-bench",
    env: str = "demo",
) -> Dict[str, Any]:
    """Convert a single trajectory to Datadog trace format."""
    trajectory_id = trajectory_data.get("trajectory_id", "unknown")
    task_type = trajectory_data.get("task_type", "unknown")
    llm_model = trajectory_data.get("llm_model", "unknown")
    failure_types = trajectory_data.get("failure_types", [])
    failure_reasonings = trajectory_data.get("failure_reasonings", [])
    critical_step = trajectory_data.get("critical_failure_step", -1)
    num_steps = trajectory_data.get("num_steps", 0)

    # Map failure type
    failure_type, severity = map_failure_type(failure_types)

    # Parse trajectory to get context
    messages = parse_trajectory(trajectory_data.get("full_trajectory", "{}"))

    # Build user prompt from first user message
    user_prompt = "Agent execution trajectory"
    for msg in messages[:5]:  # Look in first 5 messages
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if len(content) > 50:  # Likely the actual task
                user_prompt = content[:500]  # Truncate
                break

    # Build assistant response from failure reasoning
    assistant_response = failure_reasonings[0] if failure_reasonings else "Agent execution failed"
    assistant_response = assistant_response[:500]  # Truncate

    # Build tags for Datadog
    tags = [
        f"failure_type:{failure_type}",
        f"severity:{severity}",
        f"task_type:{task_type}",
        f"model:{llm_model}",
        f"env:{env}",
        f"ml_app:{ml_app}",
        f"source:agenterrorbench",
    ]

    # Add specific failure type tags for detection
    if failure_type == "runaway_loop":
        tags.append("runaway_loop:true")
    elif failure_type == "hallucination":
        tags.append("hallucination:true")

    # Quality score based on failure severity
    quality_score = 0.1 if severity == "critical" else 0.3 if severity == "high" else 0.45

    return {
        "trace_id": trajectory_id,
        "span_id": f"{trajectory_id}_span",
        "name": f"agent_trajectory_{task_type}",
        "service": ml_app,
        "ml_app": ml_app,
        "model_name": llm_model,
        "model_provider": "agenterrorbench",
        "status": "error",
        "input": user_prompt,
        "output": assistant_response,
        "tags": tags,
        "failure_type": failure_type,
        "severity": severity,
        "quality_score": quality_score,
        "metadata": {
            "task_type": task_type,
            "critical_failure_step": critical_step,
            "num_steps": num_steps,
            "failure_types": failure_types,
            "source": "agenterrorbench",
        },
    }


def upload_traces_to_datadog(traces: List[Dict[str, Any]], dry_run: bool = False) -> int:
    """Upload traces to Datadog LLM Observability."""
    if dry_run:
        print(f"[DRY RUN] Would upload {len(traces)} traces")
        return len(traces)

    try:
        from ddtrace.llmobs import LLMObs
    except ImportError:
        print("Error: ddtrace required for upload. Install with: pip install ddtrace")
        return 0

    # Initialize LLMObs
    api_key = os.getenv("DD_API_KEY")
    app_key = os.getenv("DD_APP_KEY")
    site = os.getenv("DD_SITE", "us5.datadoghq.com")

    if not api_key:
        print("Error: DD_API_KEY environment variable required")
        return 0

    print(f"Initializing Datadog LLM Observability (site: {site})...")
    LLMObs.enable(
        ml_app="agent-error-bench",
        site=site,
        api_key=api_key,
        app_key=app_key,
        agentless_enabled=True,
        env="demo",
        service="agent-error-bench",
    )

    uploaded = 0
    for trace in traces:
        try:
            with LLMObs.llm(
                model_name=trace["model_name"],
                name=trace["name"],
                model_provider=trace["model_provider"],
            ) as span:
                # Mark as error
                span.error = 1

                # Annotate with data
                LLMObs.annotate(
                    span=span,
                    input_data=trace["input"],
                    output_data=trace["output"],
                    tags=dict(tag.split(":", 1) for tag in trace["tags"] if ":" in tag),
                    metadata=trace["metadata"],
                )

            uploaded += 1
            print(f"  Uploaded: {trace['trace_id']} ({trace['failure_type']})")
            time.sleep(0.1)  # Rate limiting

        except Exception as e:
            print(f"  Error uploading {trace['trace_id']}: {e}")

    print(f"\nUploaded {uploaded}/{len(traces)} traces to Datadog")
    return uploaded


def list_failure_types(trajectories: List[Dict[str, Any]]) -> None:
    """List all failure types in the dataset."""
    failure_counts: Dict[str, int] = {}
    for t in trajectories:
        for ft in t.get("failure_types", []):
            failure_counts[ft] = failure_counts.get(ft, 0) + 1

    print("\nFailure Type Distribution:")
    print("-" * 40)
    for ft, count in sorted(failure_counts.items(), key=lambda x: -x[1]):
        mapped, severity = map_failure_type([ft])
        print(f"  {ft}: {count} -> {mapped} ({severity})")


def preview_trajectory(trajectories: List[Dict[str, Any]], index: int) -> None:
    """Preview a single trajectory conversion."""
    if index >= len(trajectories):
        print(f"Error: Index {index} out of range (max: {len(trajectories) - 1})")
        return

    t = trajectories[index]
    trace = trajectory_to_datadog_trace(t)

    print("\n" + "=" * 60)
    print(f"TRAJECTORY {index}: {t.get('trajectory_id')}")
    print("=" * 60)
    print(f"Task Type: {t.get('task_type')}")
    print(f"LLM Model: {t.get('llm_model')}")
    print(f"Steps: {t.get('num_steps')}")
    print(f"Critical Step: {t.get('critical_failure_step')}")
    print(f"\nOriginal Failure Types: {t.get('failure_types')}")
    print(f"Mapped To: {trace['failure_type']} ({trace['severity']})")
    print(f"\nUser Prompt (truncated): {trace['input'][:200]}...")
    print(f"\nFailure Reasoning: {trace['output'][:300]}...")
    print(f"\nTags: {trace['tags']}")
    print(f"Quality Score: {trace['quality_score']}")


def main():
    parser = argparse.ArgumentParser(description="Convert AgentErrorBench to Datadog traces")
    parser.add_argument("--upload", action="store_true", help="Upload to Datadog")
    parser.add_argument("--dry-run", action="store_true", help="Preview without uploading")
    parser.add_argument("--count", type=int, default=5, help="Number of traces to convert")
    parser.add_argument("--list-failures", action="store_true", help="List failure type distribution")
    parser.add_argument("--preview", type=int, help="Preview single trajectory by index")
    parser.add_argument("--filter-type", type=str, help="Filter by failure type (e.g., runaway_loop)")

    args = parser.parse_args()

    # Load dataset
    trajectories = load_agenterrorbench()

    if args.list_failures:
        list_failure_types(trajectories)
        return

    if args.preview is not None:
        preview_trajectory(trajectories, args.preview)
        return

    # Filter if requested
    if args.filter_type:
        trajectories = [
            t for t in trajectories
            if any(args.filter_type.lower() in ft.lower() for ft in t.get("failure_types", []))
        ]
        print(f"Filtered to {len(trajectories)} trajectories with '{args.filter_type}'")

    # Limit count
    trajectories = trajectories[: args.count]

    # Convert to traces
    print(f"\nConverting {len(trajectories)} trajectories to Datadog traces...")
    traces = [trajectory_to_datadog_trace(t) for t in trajectories]

    # Show summary
    print("\nConversion Summary:")
    for trace in traces:
        print(f"  {trace['trace_id']}: {trace['failure_type']} ({trace['severity']})")

    if args.upload or args.dry_run:
        upload_traces_to_datadog(traces, dry_run=args.dry_run)
    else:
        print("\nUse --upload to send to Datadog, or --dry-run to preview")


if __name__ == "__main__":
    main()
