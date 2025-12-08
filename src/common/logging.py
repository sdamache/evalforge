"""Structured logging helpers for ingestion and API services."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional


_RESERVED_RECORD_KEYS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
}


class JsonFormatter(logging.Formatter):
    """Render log records as JSON with consistent keys."""

    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Collect extra fields added via the `extra` kwarg.
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_KEYS:
                continue
            base[key] = value

        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(base, default=str, ensure_ascii=True)


def _ensure_configured(level: int = logging.INFO) -> None:
    """Configure a shared JSON logger once."""
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.setLevel(level)
    root.addHandler(handler)


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a logger configured for JSON output."""
    _ensure_configured(level)
    logger = logging.getLogger(name)
    logger.propagate = True
    return logger


def log_decision(
    logger: logging.Logger,
    *,
    trace_id: Optional[str],
    action: str,
    outcome: str,
    **context: Any,
) -> None:
    """Emit a structured decision log."""
    logger.info(
        "decision",
        extra={"event": "decision", "trace_id": trace_id, "action": action, "outcome": outcome, **context},
    )


def log_trace(
    logger: logging.Logger,
    message: str,
    *,
    trace_id: Optional[str] = None,
    **context: Any,
) -> None:
    """Emit an info log tied to a trace."""
    logger.info(message, extra={"trace_id": trace_id, **context})


def log_error(
    logger: logging.Logger,
    message: str,
    *,
    trace_id: Optional[str] = None,
    error: Optional[BaseException] = None,
    **context: Any,
) -> None:
    """Emit an error log with optional exception and trace correlation."""
    logger.error(
        message,
        extra={"trace_id": trace_id, **context},
        exc_info=error if error else None,
    )


def log_audit(
    logger: logging.Logger,
    *,
    actor: Optional[str],
    action: str,
    target: Optional[str] = None,
    status: str = "succeeded",
    **context: Any,
) -> None:
    """Emit an audit log for export actions."""
    logger.info(
        "audit",
        extra={
            "event": "audit",
            "actor": actor,
            "action": action,
            "target": target,
            "status": status,
            **context,
        },
    )
