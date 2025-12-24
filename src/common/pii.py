"""Shared PII detection and redaction utilities.

This module provides centralized PII handling used across:
- Ingestion: Strip PII fields from Datadog traces before storage
- Extraction: Redact PII from Gemini-generated evidence excerpts

Having a single source of truth for PII patterns ensures consistent
privacy protection across all Evalforge services.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple

# ============================================================================
# PII Field Paths (for structured data stripping)
# ============================================================================

# Fields to strip from trace payloads (dotted paths for nested access)
PII_FIELDS_TO_STRIP: Set[str] = {
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

# ============================================================================
# PII Regex Patterns (for text redaction)
# ============================================================================

# Patterns with their replacement placeholders
# Order matters - more specific patterns should come first
PII_PATTERNS: List[Tuple[str, str]] = [
    # Email addresses
    (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL_REDACTED]"),
    # Phone numbers (various formats)
    (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "[PHONE_REDACTED]"),
    (r"\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}", "[PHONE_REDACTED]"),
    # Social Security Numbers
    (r"\b\d{3}-\d{2}-\d{4}\b", "[SSN_REDACTED]"),
    # Credit card numbers (basic pattern)
    (r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", "[CARD_REDACTED]"),
    # IP addresses
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[IP_REDACTED]"),
    # API keys and tokens (common patterns)
    (r"sk-[a-zA-Z0-9]{20,}", "[API_KEY_REDACTED]"),
    (r"Bearer\s+[a-zA-Z0-9._-]+", "[BEARER_TOKEN_REDACTED]"),
    (r"api[_-]?key[\"']?\s*[:=]\s*[\"']?[a-zA-Z0-9._-]+", "[API_KEY_REDACTED]"),
    # JWT tokens
    (r"eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*", "[JWT_REDACTED]"),
    # AWS keys
    (r"AKIA[0-9A-Z]{16}", "[AWS_KEY_REDACTED]"),
    # Passwords in common formats
    (r"password[\"']?\s*[:=]\s*[\"']?[^\s\"']+", "[PASSWORD_REDACTED]"),
    # Names after common prefixes (basic heuristic)
    (r"(?:user|name|customer)[\"']?\s*[:=]\s*[\"']?[A-Z][a-z]+\s+[A-Z][a-z]+", "[NAME_REDACTED]"),
]

# Compiled patterns for efficiency
_COMPILED_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(pattern, re.IGNORECASE), replacement)
    for pattern, replacement in PII_PATTERNS
]

# ============================================================================
# Text Redaction Functions
# ============================================================================


def redact_pii_text(text: str) -> str:
    """Apply PII redaction patterns to text.

    Args:
        text: The text to redact.

    Returns:
        Text with PII patterns replaced by redaction placeholders.
    """
    result = text
    for pattern, replacement in _COMPILED_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def has_pii(text: str) -> bool:
    """Check if text contains detectable PII patterns.

    This is a best-effort check - it cannot guarantee no PII exists.

    Args:
        text: The text to check.

    Returns:
        True if any PII patterns detected, False otherwise.
    """
    for pattern, _ in _COMPILED_PATTERNS:
        if pattern.search(text):
            return True
    return False


def truncate_text(
    text: str,
    max_length: int = 500,
    preserve_word_boundary: bool = True,
) -> str:
    """Truncate text to maximum length, optionally preserving word boundaries.

    Args:
        text: The text to truncate.
        max_length: Maximum allowed length.
        preserve_word_boundary: If True, try to break at word boundary.

    Returns:
        Truncated text with ellipsis if needed.
    """
    if len(text) <= max_length:
        return text

    truncated = text[: max_length - 3]

    if preserve_word_boundary:
        last_space = truncated.rfind(" ")
        if last_space > max_length // 2:
            truncated = truncated[:last_space]

    return truncated + "..."


def redact_and_truncate(
    text: Optional[str],
    max_length: int = 500,
) -> Optional[str]:
    """Redact PII and truncate text for safe storage.

    This is the recommended entry point for processing user-visible excerpts.

    Args:
        text: The raw text to process (can be None).
        max_length: Maximum allowed length after processing.

    Returns:
        Redacted and truncated text, or None if input was empty.
    """
    if not text:
        return None

    redacted = redact_pii_text(text)
    return truncate_text(redacted, max_length)


# ============================================================================
# Structured Data Stripping Functions
# ============================================================================


def _strip_nested_field(data: Dict[str, Any], dotted_path: str) -> None:
    """Remove a field from nested dict using dotted path notation.

    Args:
        data: The dictionary to modify in place.
        dotted_path: Dot-separated path (e.g., "user.email").
    """
    parts = dotted_path.split(".")
    target = data
    for i, key in enumerate(parts):
        if not isinstance(target, dict) or key not in target:
            return
        if i == len(parts) - 1:
            target.pop(key, None)
            return
        target = target.get(key)


def strip_pii_fields(
    data: Dict[str, Any],
    fields: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Strip PII fields from a dictionary.

    Modifies the dictionary in place and also returns it for chaining.

    Args:
        data: The dictionary to strip PII from.
        fields: Set of dotted field paths to strip. Defaults to PII_FIELDS_TO_STRIP.

    Returns:
        The modified dictionary (same reference as input).
    """
    fields = fields or PII_FIELDS_TO_STRIP

    for dotted in fields:
        _strip_nested_field(data, dotted)
        # Also try flat key variants (Datadog uses both "user.email" and "user_email")
        flat_key = dotted.replace(".", "_")
        if flat_key in data:
            data.pop(flat_key, None)

    return data


def filter_pii_tags(tags: List[str]) -> List[str]:
    """Remove PII-containing tags from a tags list.

    Strips tags matching:
    - pii:* (explicit PII tags)
    - user.* / user_* (user-related tags which may contain PII)

    Args:
        tags: List of tag strings.

    Returns:
        Filtered list with PII tags removed.
    """
    filtered = []
    for tag in tags:
        # Strip explicit PII tags
        if tag.startswith("pii:"):
            continue
        # Strip user-related tags
        if tag.startswith("user.") or tag.startswith("user_"):
            continue
        filtered.append(tag)
    return filtered


def hash_user_id(user_id: str, salt: str = "evalforge") -> str:
    """Compute a salted hash of a user ID for pseudonymization.

    Args:
        user_id: The user identifier to hash.
        salt: Salt value (should be from PII_SALT env var in production).

    Returns:
        SHA256 hash of the salted user ID.
    """
    return hashlib.sha256((user_id + salt).encode("utf-8")).hexdigest()
