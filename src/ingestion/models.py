"""Domain models for Datadog failure ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
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
        """Serialize to Firestore-friendly dict."""
        return asdict(self)


@dataclass
class SourceTraceReference:
    """Minimal information to locate the original trace in Datadog."""

    trace_id: str
    datadog_url: str
    datadog_site: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExportPackage:
    """Bundle sent to downstream systems when exporting a captured failure."""

    failure_trace_id: str
    exported_at: datetime
    destination: str
    status: str
    status_detail: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
