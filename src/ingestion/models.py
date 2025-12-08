"""Domain models for Datadog failure ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class FailureCapture:
    """Normalized record of a production LLM failure captured from Datadog."""

    trace_id: str
    fetched_at: datetime
    failure_type: str
    trace_payload: Dict[str, Any] = field(default_factory=dict)
    service_name: str = ""
    severity: str = ""
    status_code: Optional[int] = None
    quality_score: Optional[float] = None
    user_hash: Optional[str] = None
    processed: bool = False
    recurrence_count: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to Firestore-friendly dict aligned with the contract."""
        fetched_at = self.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        payload: Dict[str, Any] = {
            "trace_id": self.trace_id,
            "fetched_at": fetched_at.isoformat(),
            "failure_type": self.failure_type,
            "trace_payload": self.trace_payload,
            "service_name": self.service_name,
            "severity": self.severity,
            "processed": self.processed,
            "recurrence_count": self.recurrence_count,
        }
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        if self.quality_score is not None:
            payload["quality_score"] = self.quality_score
        if self.user_hash is not None:
            payload["user_hash"] = self.user_hash
        return payload


@dataclass
class SourceTraceReference:
    """Minimal information to locate the original trace in Datadog."""

    trace_id: str
    datadog_url: str
    datadog_site: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "datadog_url": self.datadog_url,
            "datadog_site": self.datadog_site,
        }


@dataclass
class ExportPackage:
    """Bundle sent to downstream systems when exporting a captured failure."""

    failure_trace_id: str
    exported_at: datetime
    destination: str
    status: str
    status_detail: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        exported_at = self.exported_at
        if exported_at.tzinfo is None:
            exported_at = exported_at.replace(tzinfo=timezone.utc)
        payload: Dict[str, Any] = {
            "failure_trace_id": self.failure_trace_id,
            "exported_at": exported_at.isoformat(),
            "destination": self.destination,
            "status": self.status,
        }
        if self.status_detail is not None:
            payload["status_detail"] = self.status_detail
        return payload
