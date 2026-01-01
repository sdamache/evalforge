#!/usr/bin/env python3
"""Seed test traces using real AgentErrorBench data for extraction demo."""
import os
import json
import hashlib
from datetime import datetime, timezone
os.environ['GOOGLE_CLOUD_PROJECT'] = 'konveyn2ai'

from datasets import load_dataset
from google.cloud import firestore

# Failure type mapping from AgentErrorBench to EvalForge types
FAILURE_TYPE_MAPPING = {
    "misalignment": "hallucination",
    "planning_error": "hallucination",
    "reasoning_error": "hallucination",
    "knowledge_error": "hallucination",
    "hallucination": "hallucination",
    "repetition": "runaway_loop",
    "step_limit": "runaway_loop",
    "tool_use_error": "client_error",
    "tool_execution_error": "client_error",
    "parameter_error": "client_error",
    "observation_error": "quality_degradation",
    "constraint_ignorance": "quality_degradation",
}

SEVERITY_MAPPING = {
    "runaway_loop": "critical",
    "hallucination": "high",
    "client_error": "medium",
    "quality_degradation": "medium",
}

def map_failure_type(failure_types):
    if not failure_types:
        return "unknown", "medium"
    primary = failure_types[0].lower()
    for key, value in FAILURE_TYPE_MAPPING.items():
        if key in primary:
            return value, SEVERITY_MAPPING.get(value, "medium")
    return "unknown", "medium"

print("Loading AgentErrorBench dataset...")
dataset = load_dataset("davide221/agenterrorbench", split="train")

db = firestore.Client(project='konveyn2ai', database='evalforge')
collection = db.collection('evalforge_raw_traces')

# Select 5 diverse trajectories
selected_indices = [0, 25, 50, 75, 100]  # Spread across dataset
seeded = 0

for idx in selected_indices:
    if idx >= len(dataset):
        continue

    traj = dataset[idx]
    trajectory_id = traj["trajectory_id"]

    # Parse full trajectory
    try:
        full_traj = json.loads(traj["full_trajectory"]) if isinstance(traj["full_trajectory"], str) else traj["full_trajectory"]
        messages = full_traj.get("messages", [])
    except:
        messages = []

    # Get failure info
    failure_types = traj.get("failure_types", [])
    failure_reasonings = traj.get("failure_reasonings", [])
    failure_type, severity = map_failure_type(failure_types)

    # Extract first user message as input (truncated)
    user_input = "Agent task execution"
    for msg in messages[:5]:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if len(content) > 50:
                user_input = content[:500]
                break

    # Use failure reasoning as output context
    output_context = failure_reasonings[0] if failure_reasonings else f"Agent failed at step {traj.get('critical_failure_step', 'unknown')}"
    output_context = output_context[:500]

    # Generate a realistic trace_id from trajectory_id
    trace_id = hashlib.sha256(trajectory_id.encode()).hexdigest()[:32]

    trace_data = {
        "trace_id": trace_id,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "failure_type": failure_type,
        "severity": severity,
        "service_name": f"{traj.get('task_type', 'agent')}-agent",
        "processed": False,
        "recurrence_count": 1,
        "status": "new",
        "export_status": "pending",
        "status_history": [{"status": "new", "actor": "ingestion", "timestamp": datetime.now(timezone.utc).isoformat()}],
        "trace_payload": {
            "input": user_input,
            "output": output_context,
            "name": f"agent_trajectory_{traj.get('task_type', 'unknown')}",
            "span_kind": "llm",
            "status": "error",
            "duration": traj.get("num_steps", 1) * 1000000000,  # Simulate duration
            "metadata": {
                "model": traj.get("llm_model", "unknown"),
                "num_steps": traj.get("num_steps", 0),
                "critical_failure_step": traj.get("critical_failure_step", -1),
                "failure_types_original": failure_types,
                "trajectory_length": traj.get("trajectory_length", 0),
                "source_dataset": "agenterrorbench",
                "source_trajectory_id": trajectory_id
            },
            "tags": [
                f"failure_type:{failure_type}",
                f"severity:{severity}",
                f"task_type:{traj.get('task_type', 'unknown')}",
                f"model:{traj.get('llm_model', 'unknown')}",
                "source:agenterrorbench"
            ]
        }
    }

    doc_ref = collection.document(trace_id)
    doc_ref.set(trace_data)
    print(f"  ✓ Seeded: {trace_id[:16]}... ({failure_type}, {traj.get('task_type')})")
    seeded += 1

print(f"\nSeeded {seeded} traces with real AgentErrorBench content.")
print("Run extraction service to process these traces.")
