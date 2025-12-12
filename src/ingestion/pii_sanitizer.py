"""Helpers to strip PII and compute user hashes for Datadog trace payloads."""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Tuple

PII_FIELDS_TO_STRIP = {
    "user.email",
    "user.name",
    "user.phone",
    "user.address",
    "user.id",
    "user.user_id",
    "user.ip",
    "client.ip",
    "session_id",
    "request.headers.authorization",
    "request.headers.cookie",
}


def _hash_user_id(user_id: str, salt: str) -> str:
    digest = hashlib.sha256((user_id + salt).encode("utf-8")).hexdigest()
    return digest


def _strip_nested(data: Dict[str, Any], dotted_path: str) -> None:
    parts = dotted_path.split(".")
    target = data
    for i, key in enumerate(parts):
        if not isinstance(target, dict) or key not in target:
            return
        if i == len(parts) - 1:
            target.pop(key, None)
            return
        target = target.get(key)


def _filter_pii_tags(tags: list[str]) -> list[str]:
    """
    Remove PII-containing tags from the tags list.

    Strips tags matching:
    - pii:* (explicit PII tags)
    - user.* (user-related tags, which may contain PII)

    Per spec/research.md: only user.id is allowed (for hashing), all other
    user.* tags should be dropped to prevent PII leakage.
    """
    filtered = []
    for tag in tags:
        # Strip explicit PII tags
        if tag.startswith("pii:"):
            continue
        # Strip user.* tags (user_id extraction happens separately)
        if tag.startswith("user.") or tag.startswith("user_"):
            continue
        filtered.append(tag)
    return filtered


def sanitize_trace(trace: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """
    Strip PII-like fields and compute a user hash if possible.

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
    # Build payload from relevant trace fields (not trace_payload which doesn't exist in our structure)
    payload = {
        "input": trace.get("input"),
        "output": trace.get("output"),
        "metadata": dict(trace.get("metadata", {})),
        "tags": _filter_pii_tags(trace.get("tags", [])),  # Filter PII tags before storage
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
    for dotted in PII_FIELDS_TO_STRIP:
        _strip_nested(payload, dotted)
        # Also strip flat keys in metadata (Datadog uses flat "user.email" keys)
        if "metadata" in payload and isinstance(payload["metadata"], dict):
            payload["metadata"].pop(dotted, None)
            # Also try with underscores (user_id vs user.id)
            payload["metadata"].pop(dotted.replace(".", "_"), None)

    user_hash = ""
    if user_id:
        user_hash = _hash_user_id(str(user_id), salt)

    # Redact free-text prompts/responses if present
    for key in ("input", "output", "prompt", "response"):
        if key in payload and payload[key]:
            payload[key] = "[redacted]"

    return payload, user_hash
