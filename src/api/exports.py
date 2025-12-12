"""Helpers to build and persist export packages for failures."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from google.cloud import firestore
except ImportError:  # pragma: no cover - patched in tests
    firestore = None

from src.common.config import load_settings
from src.common.logging import get_logger, log_error
from src.ingestion.models import ExportPackage

logger = get_logger(__name__)


def create_export(
    firestore_client: firestore.Client,
    failure_id: str,
    destination: str,
    status: str = "pending",
    status_detail: Optional[str] = None,
    actor: str = "api",
) -> Dict[str, Any]:
    """Create and persist an ExportPackage record."""
    if firestore is None:
        raise ImportError("google-cloud-firestore is not installed")
    settings = load_settings()
    exported_at = datetime.now(tz=timezone.utc)

    package = ExportPackage(
        failure_trace_id=failure_id,
        exported_at=exported_at,
        destination=destination,
        status=status,
        status_detail=status_detail,
    )

    try:
        collection = firestore_client.collection(f"{settings.firestore.collection_prefix}exports")
        doc_ref = collection.document()
        doc_ref.set(package.to_dict())
        # Update the FailureCapture status history and export fields.
        try:
            capture_ref = firestore_client.collection(f"{settings.firestore.collection_prefix}raw_traces").document(
                failure_id
            )
            existing = capture_ref.get()
            data = existing.to_dict() if hasattr(existing, "to_dict") else {}
            history = data.get("status_history") or []
            history.append(
                {
                    "status": "exported",
                    "actor": actor,
                    "destination": destination,
                    "timestamp": exported_at.isoformat(),
                }
            )
            capture_ref.set(
                {
                    "export_status": status,
                    "export_destination": destination,
                    "export_reference": doc_ref.id,
                    "status": "exported",
                    "status_history": history,
                },
                merge=True,
            )
        except Exception as exc:  # capture update failures should not block export record creation
            log_error(logger, "Failed to update capture export status", error=exc, trace_id=failure_id)
        logger.info(
            "export_created",
            extra={
                "event": "export_created",
                "failure_trace_id": failure_id,
                "destination": destination,
                "status": status,
                "doc_id": doc_ref.id,
            },
        )
    except Exception as exc:
        log_error(logger, "Failed to create export package", error=exc, trace_id=failure_id)
        raise

    payload = package.to_dict()
    payload["id"] = doc_ref.id
    return payload
