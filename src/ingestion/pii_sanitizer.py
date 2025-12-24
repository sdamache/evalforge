"""Helpers to strip PII and compute user hashes for Datadog trace payloads.

This module provides the ingestion-specific sanitization workflow,
using shared PII utilities from src/common/pii.py.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Tuple

from src.common.pii import (
    PII_FIELDS_TO_STRIP,
    filter_pii_tags,
    hash_user_id,
    strip_pii_fields,
)


def sanitize_trace(trace: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Strip PII-like fields and compute a user hash if possible.

    Accepts trace event from Datadog client with structure:
    {
        "input": {...},
        "output": {...},
        "metadata": {...},
        "tags": [...],
        "metrics": {...},
        ...
    }

    Returns (sanitized_payload, user_hash_or_empty).
    """
    # Build payload from relevant trace fields
    payload: Dict[str, Any] = {
        "input": trace.get("input"),
        "output": trace.get("output"),
        "metadata": dict(trace.get("metadata", {})),
        "tags": filter_pii_tags(trace.get("tags", [])),
        "metrics": dict(trace.get("metrics", {})),
        "name": trace.get("name"),
        "span_kind": trace.get("span_kind"),
        "status": trace.get("status"),
        "duration": trace.get("duration"),
    }

    salt = os.getenv("PII_SALT", "evalforge")

    # Extract user_id from metadata or tags for hashing
    user_id = None
    metadata = trace.get("metadata", {})
    if isinstance(metadata, dict):
        user_id = metadata.get("user_id") or metadata.get("user.id")

    # Also check tags for user information
    if not user_id:
        for tag in trace.get("tags", []):
            if tag.startswith("user.id:") or tag.startswith("user_id:"):
                user_id = tag.split(":", 1)[1]
                break

    # Strip configured PII fields from payload
    strip_pii_fields(payload, PII_FIELDS_TO_STRIP)

    # Also strip from nested metadata using both dot and underscore variants
    if "metadata" in payload and isinstance(payload["metadata"], dict):
        for dotted in PII_FIELDS_TO_STRIP:
            payload["metadata"].pop(dotted, None)
            payload["metadata"].pop(dotted.replace(".", "_"), None)

    user_hash = ""
    if user_id:
        user_hash = hash_user_id(str(user_id), salt)

    # Redact free-text prompts/responses if present
    for key in ("input", "output", "prompt", "response"):
        if key in payload and payload[key]:
            payload[key] = "[redacted]"

    return payload, user_hash
