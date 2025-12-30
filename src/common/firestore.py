"""Shared Firestore utilities for Evalforge services.

This module provides a consistent interface for Firestore operations
across ingestion, extraction, and API services.

Usage:
    from src.common.firestore import get_firestore_client, compute_backlog_size

    client = get_firestore_client()
    collection = client.collection("evalforge_raw_traces")
"""

from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

from src.common.config import FirestoreConfig, load_firestore_config

if TYPE_CHECKING:
    from google.cloud.firestore import Client as FirestoreClient


class FirestoreError(Exception):
    """Base exception for Firestore-related errors."""

    pass


def get_firestore_client(
    config: Optional[FirestoreConfig] = None,
) -> "FirestoreClient":
    """Get a configured Firestore client.

    This is the canonical way to obtain a Firestore client across all
    Evalforge services. It handles:
    - Lazy import of google-cloud-firestore
    - Configuration from environment or explicit config
    - Proper project and database ID setup

    Args:
        config: Optional FirestoreConfig. If not provided, loads from environment.

    Returns:
        Configured Firestore client.

    Raises:
        FirestoreError: If google-cloud-firestore is not installed or
            client initialization fails.
    """
    try:
        from google.cloud import firestore
    except ImportError as e:
        raise FirestoreError(
            "google-cloud-firestore not installed. Run: pip install google-cloud-firestore"
        ) from e

    if config is None:
        config = load_firestore_config()

    kwargs: Dict[str, Any] = {}
    if config.project_id:
        kwargs["project"] = config.project_id
    if config.database_id:
        kwargs["database"] = config.database_id

    try:
        return firestore.Client(**kwargs)
    except Exception as e:
        raise FirestoreError(f"Failed to initialize Firestore client: {e}") from e


def compute_backlog_size(
    client: "FirestoreClient",
    collection_name: str,
) -> Optional[int]:
    """Compute the number of documents in a collection.

    Uses streaming count for efficiency. Falls back to manual counting
    for compatibility with test doubles.

    Args:
        client: Firestore client.
        collection_name: Name of the collection to count.

    Returns:
        Number of documents, or None if counting fails.
    """
    collection = client.collection(collection_name)

    # Try stream counting (most reliable)
    try:
        return sum(1 for _ in collection.stream())
    except Exception:
        pass

    # Fallback for test doubles with .docs attribute
    docs = getattr(collection, "docs", None)
    if isinstance(docs, dict):
        return len(docs)

    return None


def get_collection_prefix(config: Optional[FirestoreConfig] = None) -> str:
    """Get the collection prefix from config or environment.

    Args:
        config: Optional FirestoreConfig. If not provided, loads from environment.

    Returns:
        Collection prefix string (e.g., "evalforge_").
    """
    if config is None:
        config = load_firestore_config()
    return config.collection_prefix


# Standard collection names
def raw_traces_collection(prefix: Optional[str] = None) -> str:
    """Get the raw traces collection name."""
    prefix = prefix or get_collection_prefix()
    return f"{prefix}raw_traces"


def failure_patterns_collection(prefix: Optional[str] = None) -> str:
    """Get the failure patterns collection name."""
    prefix = prefix or get_collection_prefix()
    return f"{prefix}failure_patterns"


def extraction_runs_collection(prefix: Optional[str] = None) -> str:
    """Get the extraction runs collection name."""
    prefix = prefix or get_collection_prefix()
    return f"{prefix}extraction_runs"


def extraction_errors_collection(prefix: Optional[str] = None) -> str:
    """Get the extraction errors collection name."""
    prefix = prefix or get_collection_prefix()
    return f"{prefix}extraction_errors"


def suggestions_collection(prefix: Optional[str] = None) -> str:
    """Get the suggestions collection name for deduplication service."""
    prefix = prefix or get_collection_prefix()
    return f"{prefix}suggestions"


def eval_test_runs_collection(prefix: Optional[str] = None) -> str:
    """Get the eval test generator run summaries collection name."""
    prefix = prefix or get_collection_prefix()
    return f"{prefix}eval_test_runs"


def eval_test_errors_collection(prefix: Optional[str] = None) -> str:
    """Get the eval test generator errors collection name."""
    prefix = prefix or get_collection_prefix()
    return f"{prefix}eval_test_errors"


def runbook_runs_collection(prefix: Optional[str] = None) -> str:
    """Get the runbook generator run summaries collection name."""
    prefix = prefix or get_collection_prefix()
    return f"{prefix}runbook_runs"


def runbook_errors_collection(prefix: Optional[str] = None) -> str:
    """Get the runbook generator errors collection name."""
    prefix = prefix or get_collection_prefix()
    return f"{prefix}runbook_errors"


def guardrail_runs_collection(prefix: Optional[str] = None) -> str:
    """Get the guardrail generator run summaries collection name."""
    prefix = prefix or get_collection_prefix()
    return f"{prefix}guardrail_runs"


def guardrail_errors_collection(prefix: Optional[str] = None) -> str:
    """Get the guardrail generator errors collection name."""
    prefix = prefix or get_collection_prefix()
    return f"{prefix}guardrail_errors"
