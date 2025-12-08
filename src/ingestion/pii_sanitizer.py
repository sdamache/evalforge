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


def sanitize_trace(trace: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """
    Strip PII-like fields and compute a user hash if possible.

    Returns (sanitized_payload, user_hash_or_empty).
    """
    payload = dict(trace.get("trace_payload", {}))
    salt = os.getenv("PII_SALT", "evalforge")

    user_id = None
    user_container = payload.get("user") if isinstance(payload.get("user"), dict) else trace.get("user")
    if isinstance(user_container, dict):
        user_id = user_container.get("id") or user_container.get("user_id")
    elif isinstance(trace.get("user"), dict):
        user_id = trace["user"].get("id") or trace["user"].get("user_id")

    # Strip configured fields
    for dotted in PII_FIELDS_TO_STRIP:
        _strip_nested(payload, dotted)

    user_hash = ""

    if user_id:
        user_hash = _hash_user_id(str(user_id), salt)

    # Redact free-text prompts/responses if present
    for key in ("input", "output", "prompt", "response"):
        if key in payload:
            payload[key] = "[redacted]"

    return payload, user_hash
