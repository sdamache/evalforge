#!/usr/bin/env python3
"""Create test suggestions in Firestore for dashboard testing.

Usage:
    PYTHONPATH=src python scripts/create_test_suggestions.py [--clear]

Options:
    --clear     Clear existing pending suggestions before creating new ones
"""

import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

from google.cloud import firestore


def clear_pending_suggestions(collection):
    """Delete all pending suggestions."""
    print("Clearing existing pending suggestions...")
    pending_docs = collection.where("status", "==", "pending").stream()
    deleted = 0
    for doc in pending_docs:
        doc.reference.delete()
        deleted += 1
    print(f"  Deleted {deleted} pending suggestions")
    print()


def create_test_suggestions(clear_first: bool = False):
    """Create comprehensive test suggestions for dashboard testing."""

    # Initialize Firestore
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "konveyn2ai")
    database_id = os.environ.get("FIRESTORE_DATABASE_ID", "evalforge")

    db = firestore.Client(project=project_id, database=database_id)
    collection = db.collection("evalforge_suggestions")

    if clear_first:
        clear_pending_suggestions(collection)

    now = datetime.now(timezone.utc)

    # Comprehensive test suggestions covering all types, severities, and edge cases
    test_suggestions = [
        # CRITICAL severity - should appear first in sorted view
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "eval",
            "severity": "critical",
            "title": "Add hallucination detection eval",
            "description": "LLM produced factually incorrect response about company policies. Customer received wrong refund information leading to escalation.",
            "status": "pending",
            "created_at": now - timedelta(hours=5),  # Oldest critical
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
            "pattern": {
                "failure_type": "hallucination",
                "severity": "critical",
                "trigger_condition": "factual_query",
                "example_input": "What is the refund policy?",
                "example_output": "You can get a full refund within 90 days (incorrect: actual is 30 days)",
            },
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "guardrail",
            "severity": "critical",
            "title": "Block credit card number exposure",
            "description": "Model repeated back customer's full credit card number in chat response.",
            "status": "pending",
            "created_at": now - timedelta(hours=2),  # Newer critical
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
            "pattern": {
                "failure_type": "pii_exposure",
                "severity": "critical",
                "trigger_condition": "payment_context",
            },
        },

        # HIGH severity
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "eval",
            "severity": "high",
            "title": "Add tone consistency eval",
            "description": "Model switching between formal and casual tone mid-conversation, confusing customers.",
            "status": "pending",
            "created_at": now - timedelta(hours=8),
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
            "pattern": {
                "failure_type": "tone_inconsistency",
                "severity": "high",
                "trigger_condition": "multi_turn_conversation",
            },
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "guardrail",
            "severity": "high",
            "title": "Block email address exposure",
            "description": "Model leaked customer email addresses in support chat responses.",
            "status": "pending",
            "created_at": now - timedelta(hours=6),
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
            "pattern": {
                "failure_type": "pii_exposure",
                "severity": "high",
                "trigger_condition": "customer_lookup",
            },
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "runbook",
            "severity": "high",
            "title": "Add circuit breaker for API failures",
            "description": "Cascading failures when Gemini API returns 503 errors repeatedly.",
            "status": "pending",
            "created_at": now - timedelta(hours=4),
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
            "pattern": {
                "failure_type": "infrastructure_error",
                "severity": "high",
                "trigger_condition": "api_overload",
            },
        },

        # MEDIUM severity
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "eval",
            "severity": "medium",
            "title": "Add response completeness eval",
            "description": "Model sometimes provides partial answers that don't fully address the user's question.",
            "status": "pending",
            "created_at": now - timedelta(hours=12),
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
            "pattern": {
                "failure_type": "incomplete_response",
                "severity": "medium",
                "trigger_condition": "complex_query",
            },
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "guardrail",
            "severity": "medium",
            "title": "Detect and block competitor mentions",
            "description": "Model recommending competitor products when asked about alternatives.",
            "status": "pending",
            "created_at": now - timedelta(hours=10),
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "runbook",
            "severity": "medium",
            "title": "Add retry logic for timeout errors",
            "description": "Gemini API timeouts causing user-facing errors instead of graceful degradation.",
            "status": "pending",
            "created_at": now - timedelta(hours=3),
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
        },

        # LOW severity
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "eval",
            "severity": "low",
            "title": "Add grammar check eval",
            "description": "Occasional grammatical errors in responses, mostly minor typos.",
            "status": "pending",
            "created_at": now - timedelta(hours=24),
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "guardrail",
            "severity": "low",
            "title": "Limit response length to 500 words",
            "description": "Some responses exceeding 4000 tokens causing UI scroll issues.",
            "status": "pending",
            "created_at": now - timedelta(hours=18),
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "runbook",
            "severity": "low",
            "title": "Add request logging for debugging",
            "description": "Missing detailed logs for troubleshooting intermittent issues.",
            "status": "pending",
            "created_at": now - timedelta(hours=15),
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
        },

        # Additional variety for testing filters and pagination
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "eval",
            "severity": "high",
            "title": "Add safety eval for harmful content",
            "description": "Model occasionally generates mildly inappropriate jokes when asked to be funny.",
            "status": "pending",
            "created_at": now - timedelta(minutes=30),
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "guardrail",
            "severity": "medium",
            "title": "Block internal system prompts in output",
            "description": "System prompt partially leaked in one response during prompt injection attempt.",
            "status": "pending",
            "created_at": now - timedelta(minutes=45),
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
            "pattern": {
                "failure_type": "prompt_injection",
                "severity": "medium",
                "trigger_condition": "adversarial_input",
            },
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "runbook",
            "severity": "critical",
            "title": "Add fallback for model unavailability",
            "description": "No graceful degradation when primary model is down - entire service fails.",
            "status": "pending",
            "created_at": now - timedelta(minutes=15),
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "eval",
            "severity": "medium",
            "title": "Add context retention eval",
            "description": "Model forgetting context from earlier in long conversations.",
            "status": "pending",
            "created_at": now - timedelta(hours=1),
            "source_trace_id": f"trace-{uuid.uuid4().hex[:8]}",
        },
    ]

    print(f"Creating {len(test_suggestions)} test suggestions...")
    print(f"Project: {project_id}, Database: {database_id}")
    print(f"Collection: evalforge_suggestions")
    print()
    print(f"{'ID':<10} {'TYPE':<12} {'SEVERITY':<10} {'AGE':<8} TITLE")
    print("-" * 80)

    for suggestion in test_suggestions:
        doc_ref = collection.document(suggestion["suggestion_id"])
        doc_ref.set(suggestion)

        # Calculate age for display
        age_delta = now - suggestion["created_at"]
        if age_delta.total_seconds() < 3600:
            age_str = f"{int(age_delta.total_seconds() / 60)}m"
        else:
            age_str = f"{int(age_delta.total_seconds() / 3600)}h"

        print(f"{suggestion['suggestion_id'][:8]}.. {suggestion['type']:<12} {suggestion['severity']:<10} {age_str:<8} {suggestion['title'][:40]}")

    print()
    print(f"✅ Created {len(test_suggestions)} pending suggestions")
    print()

    # Summary by type and severity
    by_type = {}
    by_severity = {}
    for s in test_suggestions:
        by_type[s["type"]] = by_type.get(s["type"], 0) + 1
        by_severity[s["severity"]] = by_severity.get(s["severity"], 0) + 1

    print("Summary:")
    print(f"  By Type:     {by_type}")
    print(f"  By Severity: {by_severity}")
    print()
    print("Refresh your Datadog App Builder dashboard to see them.")


if __name__ == "__main__":
    clear_flag = "--clear" in sys.argv
    create_test_suggestions(clear_first=clear_flag)
