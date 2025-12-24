"""Trace serialization and truncation utilities.

Per research.md: If a trace payload exceeds 200KB, truncate to the last 100KB
before sending to Gemini. This focuses on the most recent context where
failures manifest and controls latency/cost.
"""

import json
from typing import Any, Dict, Tuple

# Size limits in bytes (per research.md)
MAX_PAYLOAD_SIZE_BYTES = 200 * 1024  # 200KB threshold
TRUNCATED_SIZE_BYTES = 100 * 1024  # Keep last 100KB after truncation


def serialize_trace_payload(payload: Dict[str, Any]) -> str:
    """Serialize a trace payload to JSON string.

    Args:
        payload: The trace payload dict to serialize.

    Returns:
        JSON string representation of the payload.
    """
    return json.dumps(payload, indent=2, default=str)


def get_payload_size(payload: Dict[str, Any]) -> int:
    """Get the size of a trace payload in bytes when serialized.

    Args:
        payload: The trace payload dict.

    Returns:
        Size in bytes of the JSON-serialized payload.
    """
    return len(serialize_trace_payload(payload).encode("utf-8"))


def truncate_trace_payload(
    payload: Dict[str, Any],
    max_size_bytes: int = MAX_PAYLOAD_SIZE_BYTES,
    truncated_size_bytes: int = TRUNCATED_SIZE_BYTES,
) -> Tuple[Dict[str, Any], bool]:
    """Truncate a trace payload if it exceeds the size limit.

    Strategy: Keep the structural keys and truncate large string values
    from the end, preserving the most recent context (end of logs,
    responses, etc.).

    Args:
        payload: The trace payload dict.
        max_size_bytes: Threshold above which truncation occurs.
        truncated_size_bytes: Target size after truncation.

    Returns:
        Tuple of (possibly truncated payload, was_truncated bool).
    """
    current_size = get_payload_size(payload)

    if current_size <= max_size_bytes:
        return payload, False

    # Need to truncate - work on a copy
    truncated = _truncate_payload_recursive(
        payload.copy(),
        current_size,
        truncated_size_bytes,
    )

    return truncated, True


def _truncate_payload_recursive(
    data: Any,
    current_size: int,
    target_size: int,
) -> Any:
    """Recursively truncate large values in the payload.

    Strategy:
    1. Find the largest string values
    2. Truncate them from the beginning (keep end for recency)
    3. Repeat until under target size

    Args:
        data: The data to truncate (dict, list, or primitive).
        current_size: Current total size estimate.
        target_size: Target size to achieve.

    Returns:
        Truncated data structure.
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            result[key] = _truncate_payload_recursive(value, current_size, target_size)
        return result
    elif isinstance(data, list):
        # For lists, truncate from the beginning (keep recent items at end)
        result = [_truncate_payload_recursive(item, current_size, target_size) for item in data]

        # If list is very large, keep only the last portion
        if len(result) > 100:
            result = result[-100:]
            result.insert(0, f"[...{len(data) - 100} earlier items truncated...]")

        return result
    elif isinstance(data, str):
        # Truncate long strings, keeping the end (most recent context)
        if len(data) > 10000:
            truncate_to = min(10000, max(1000, target_size // 10))
            return f"[...truncated {len(data) - truncate_to} chars...]" + data[-truncate_to:]
        return data
    else:
        return data


def prepare_trace_for_extraction(
    trace_data: Dict[str, Any],
    max_size_bytes: int = MAX_PAYLOAD_SIZE_BYTES,
    truncated_size_bytes: int = TRUNCATED_SIZE_BYTES,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Prepare a raw trace for extraction, including truncation if needed.

    This is the main entry point for trace preparation. It:
    1. Extracts the relevant payload fields
    2. Truncates if oversized
    3. Returns both the prepared payload and metadata about the preparation

    Args:
        trace_data: The raw trace document from Firestore.
        max_size_bytes: Threshold above which truncation occurs.
        truncated_size_bytes: Target size after truncation.

    Returns:
        Tuple of (prepared_payload, preparation_metadata).
        Metadata includes: original_size, final_size, was_truncated.
    """
    # Extract core fields for extraction
    # The trace_payload is the main content; other fields provide context
    payload_to_extract = {
        "trace_id": trace_data.get("trace_id", "unknown"),
        "failure_type": trace_data.get("failure_type", "unknown"),
        "severity": trace_data.get("severity", "unknown"),
        "service_name": trace_data.get("service_name"),
        "trace_payload": trace_data.get("trace_payload", {}),
    }

    # Remove None values for cleaner output
    payload_to_extract = {k: v for k, v in payload_to_extract.items() if v is not None}

    original_size = get_payload_size(payload_to_extract)
    prepared_payload, was_truncated = truncate_trace_payload(
        payload_to_extract,
        max_size_bytes,
        truncated_size_bytes,
    )
    final_size = get_payload_size(prepared_payload)

    metadata = {
        "original_size_bytes": original_size,
        "final_size_bytes": final_size,
        "was_truncated": was_truncated,
    }

    return prepared_payload, metadata


def validate_trace_has_required_fields(trace_data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate that a trace has the minimum required fields for extraction.

    Args:
        trace_data: The raw trace document from Firestore.

    Returns:
        Tuple of (is_valid, error_message).
        If valid, error_message is empty string.
    """
    required_fields = ["trace_id"]

    missing = [f for f in required_fields if not trace_data.get(f)]
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"

    # Check that trace_payload exists and has content
    payload = trace_data.get("trace_payload")
    if not payload:
        return False, "trace_payload is empty or missing"

    if not isinstance(payload, dict):
        return False, f"trace_payload must be a dict, got {type(payload).__name__}"

    return True, ""
