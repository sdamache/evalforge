"""Integration hook to forward ExportPackage payloads to downstream modules."""

from __future__ import annotations

from typing import Any, Dict

from src.common.logging import get_logger, log_error

logger = get_logger(__name__)


def forward_export(export_package: Dict[str, Any]) -> None:
    """
    Forward an export package to downstream handlers.

    This is a placeholder bridge where actual generator integrations would be invoked.
    """
    destination = export_package.get("destination")
    try:
        # TODO: wire to eval/guardrail/runbook generators
        logger.info("forward_export", extra={"event": "export_forwarded", "destination": destination})
    except Exception as exc:
        log_error(logger, "Failed to forward export package", error=exc, trace_id=export_package.get("failure_trace_id"))
        raise
