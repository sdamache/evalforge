"""Datadog client helper to fetch recent LLM failure traces."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from typing import Any, Dict, List, Optional

import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.common.config import Settings, load_settings
from src.common.logging import get_logger, log_error

logger = get_logger(__name__)
_LAST_RATE_LIMIT_STATE: Dict[str, Any] | None = None


class RateLimitError(Exception):
    """Raised when Datadog rate limits are exceeded after retries."""

    def __init__(self, retry_after: Optional[int], rate_limit_state: Optional[Dict[str, Any]] = None):
        self.retry_after = retry_after
        self.rate_limit_state = rate_limit_state or {}
        super().__init__(
            f"Datadog rate limit exceeded; retry after {retry_after if retry_after is not None else 'backoff'} seconds"
        )


class CredentialError(Exception):
    """Raised when Datadog credentials are missing or invalid."""



def _build_query_params(
    *,
    settings: Settings,
    lookback_hours: int,
    quality_threshold: float,
    service_name: Optional[str],
    page_cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build query parameters for LLM Observability Export API.

    Uses the Export API filter syntax instead of complex query strings.
    Note: The Export API uses simpler filtering - we filter by status and tags
    rather than complex query clauses.
    """
    now = datetime.now(tz=timezone.utc)
    from_time = now - timedelta(hours=lookback_hours)

    params: Dict[str, Any] = {
        "filter[from]": from_time.isoformat(),
        "filter[to]": now.isoformat(),
        "filter[span_kind]": "llm",  # Only LLM spans
        "filter[status]": "error",   # Only failures
        "page[limit]": 100,
        "sort": "-timestamp"
    }

    # Add ml_app filter if service_name is provided
    if service_name:
        params["filter[ml_app]"] = service_name

    # Add pagination cursor if provided
    if page_cursor:
        params["page[cursor]"] = page_cursor

    return params


def _build_request_url(settings: Settings) -> str:
    """Build the LLM Observability Export API URL."""
    return f"https://api.{settings.datadog.site}/api/v2/llm-obs/v1/spans/events"


def _build_headers(settings: Settings) -> Dict[str, str]:
    """Build HTTP headers for LLM Observability Export API."""
    return {
        "DD-API-KEY": settings.datadog.api_key,
        "DD-APPLICATION-KEY": settings.datadog.app_key,
    }


def _extract_rate_limit_state(headers: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not headers:
        return None
    lookup = {k.lower(): v for k, v in headers.items()}
    def _get(name: str) -> Optional[str]:
        return lookup.get(name.lower())
    name = _get("x-ratelimit-name")
    limit = _get("x-ratelimit-limit")
    remaining = _get("x-ratelimit-remaining")
    reset = _get("x-ratelimit-reset")
    period = _get("x-ratelimit-period")
    if not any([name, limit, remaining, reset, period]):
        return None
    return {
        "name": name,
        "limit": int(limit) if limit is not None else None,
        "remaining": int(remaining) if remaining is not None else None,
        "reset": int(reset) if reset is not None else None,
        "period": int(period) if period is not None else None,
        "observed_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def get_last_rate_limit_state() -> Dict[str, Any]:
    return _LAST_RATE_LIMIT_STATE or {"name": None, "limit": None, "remaining": None, "reset": None, "period": None, "observed_at": None}


# Do not retry when credentials are invalid; allow rate-limit errors to surface after bounded retries.
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=8),
    retry=retry_if_exception(lambda exc: not isinstance(exc, CredentialError) and not isinstance(exc, RateLimitError)),
    reraise=True,
)
def fetch_recent_failures(
    *,
    trace_lookback_hours: Optional[int] = None,
    quality_threshold: Optional[float] = None,
    service_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch recent Datadog LLM traces that meet failure criteria.

    Uses the LLM Observability Export API to retrieve error spans.
    Returns a list of span dicts from the Datadog LLM Observability Export API.
    """
    settings = load_settings()
    lookback = trace_lookback_hours or settings.datadog.trace_lookback_hours
    quality = quality_threshold if quality_threshold is not None else settings.datadog.quality_threshold

    url = _build_request_url(settings)
    headers = _build_headers(settings)

    events: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    attempts = 0
    try:
        start = time.perf_counter()
        logger.info(
            "query_datadog",
            extra={
                "event": "datadog_query",
                "lookback_hours": lookback,
                "quality_threshold": quality,
                "service_name": service_name,
                "page_cursor": cursor,
            },
        )
        while True:
            params = _build_query_params(
                settings=settings,
                lookback_hours=lookback,
                quality_threshold=quality,
                service_name=service_name,
                page_cursor=cursor,
            )

            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)

                # Extract rate limit info from response headers
                response_headers = dict(response.headers)
                rate_limit_state = _extract_rate_limit_state(response_headers)
                if rate_limit_state:
                    global _LAST_RATE_LIMIT_STATE
                    _LAST_RATE_LIMIT_STATE = rate_limit_state

                # Handle HTTP errors
                if response.status_code == 429:
                    retry_after_raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
                    retry_after = int(retry_after_raw) if retry_after_raw is not None else None
                    attempts += 1
                    backoff_seconds = min(max(retry_after or attempts, 1), settings.datadog.rate_limit_max_sleep)
                    logger.warning(
                        "datadog_rate_limited",
                        extra={
                            "event": "datadog_rate_limited",
                            "retry_after": retry_after,
                            "attempt": attempts,
                            "backoff_seconds": backoff_seconds,
                        },
                    )
                    if attempts >= 3:
                        raise RateLimitError(retry_after, rate_limit_state or get_last_rate_limit_state())
                    time.sleep(backoff_seconds)
                    continue

                if response.status_code in (401, 403):
                    raise CredentialError("Datadog credentials are missing or invalid")

                # Raise for other HTTP errors
                response.raise_for_status()

                # Parse response
                data = response.json()
                spans = data.get("data", [])

                # Extract span attributes from LLM Observability Export API response format
                for span_resource in spans:
                    span_attrs = span_resource.get("attributes", {})
                    # Convert Export API format to internal format
                    event = {
                        "trace_id": span_attrs.get("trace_id"),
                        "span_id": span_attrs.get("span_id"),
                        "name": span_attrs.get("name"),
                        "span_kind": span_attrs.get("span_kind"),
                        "status": span_attrs.get("status"),
                        "ml_app": span_attrs.get("ml_app"),
                        "service_name": span_attrs.get("ml_app"),  # ml_app is the service name in LLM Obs
                        "start_ns": span_attrs.get("start_ns"),
                        "duration": span_attrs.get("duration"),
                        "tags": span_attrs.get("tags", []),
                        "metadata": span_attrs.get("metadata", {}),
                        "input": span_attrs.get("input"),
                        "output": span_attrs.get("output"),
                        "metrics": span_attrs.get("metrics", {}),
                    }
                    events.append(event)

                # Extract pagination cursor from response
                meta = data.get("meta", {})
                page_info = meta.get("page")
                cursor = page_info.get("after") if page_info else None

                attempts = 0  # Reset attempts on success
                if not cursor:
                    break

            except requests.RequestException as exc:
                # Handle network/connection errors
                log_error(logger, "HTTP request failed", error=exc)
                raise

        duration = time.perf_counter() - start
        logger.info(
            "datadog_query_success",
            extra={"event": "datadog_query_success", "count": len(events), "duration_sec": round(duration, 3)},
        )
    except Exception as exc:  # broad catch to surface in structured logs
        log_error(logger, "Failed to fetch Datadog failures", error=exc)
        raise

    return events
