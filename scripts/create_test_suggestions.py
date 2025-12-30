#!/usr/bin/env python3
"""Create test suggestions in Firestore for dashboard testing.

Usage:
    PYTHONPATH=src python scripts/create_test_suggestions.py
"""

import os
import uuid
from datetime import datetime, timezone

from google.cloud import firestore


def create_test_suggestions():
    """Create sample pending suggestions for dashboard testing."""

    # Initialize Firestore
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "konveyn2ai")
    database_id = os.environ.get("FIRESTORE_DATABASE_ID", "evalforge")

    db = firestore.Client(project=project_id, database=database_id)
    collection = db.collection("evalforge_suggestions")

    # Sample suggestions
    test_suggestions = [
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "eval",
            "severity": "critical",
            "title": "Add hallucination detection eval",
            "description": "LLM produced factually incorrect response about company policies",
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "source_trace_id": "trace-001",
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "guardrail",
            "severity": "high",
            "title": "Block PII in responses",
            "description": "Model leaked customer email addresses in support chat",
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "source_trace_id": "trace-002",
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "runbook",
            "severity": "medium",
            "title": "Add retry logic for timeout errors",
            "description": "Gemini API timeouts causing cascading failures",
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "source_trace_id": "trace-003",
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "eval",
            "severity": "high",
            "title": "Add tone consistency eval",
            "description": "Model switching between formal and casual tone mid-conversation",
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "source_trace_id": "trace-004",
        },
        {
            "suggestion_id": str(uuid.uuid4()),
            "type": "guardrail",
            "severity": "low",
            "title": "Limit response length",
            "description": "Some responses exceeding 4000 tokens causing UI issues",
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "source_trace_id": "trace-005",
        },
    ]

    print(f"Creating {len(test_suggestions)} test suggestions...")
    print(f"Project: {project_id}, Database: {database_id}")
    print(f"Collection: evalforge_suggestions")
    print()

    for suggestion in test_suggestions:
        doc_ref = collection.document(suggestion["suggestion_id"])
        doc_ref.set(suggestion)
        print(f"  Created: {suggestion['suggestion_id'][:8]}... | {suggestion['type']:10} | {suggestion['severity']:8} | {suggestion['title'][:40]}")

    print()
    print(f"Done! Created {len(test_suggestions)} pending suggestions.")
    print()
    print("Refresh your Datadog App Builder dashboard to see them.")


if __name__ == "__main__":
    create_test_suggestions()
