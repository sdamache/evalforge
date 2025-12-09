"""Datadog client helper to fetch recent LLM failure traces."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional

from datadog_api_client import ApiClient, Configuration
from datadog_api_client.exceptions import ApiException
from datadog_api_client.v2.api.spans_api import SpansApi
from datadog_api_client.v2.model.spans_list_request import SpansListRequest
from datadog_api_client.v2.model.spans_list_request_attributes import SpansListRequestAttributes
from datadog_api_client.v2.model.spans_list_request_data import SpansListRequestData
from datadog_api_client.v2.model.spans_list_request_page import SpansListRequestPage
from datadog_api_client.v2.model.spans_list_request_type import SpansListRequestType
from datadog_api_client.v2.model.spans_query_filter import SpansQueryFilter
from datadog_api_client.v2.model.spans_query_options import SpansQueryOptions
from datadog_api_client.v2.model.spans_sort import SpansSort
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



def _build_query(
    *,
    service_name: Optional[str],
    quality_threshold: float,
) -> str:
    """Construct the Datadog search query for failures."""
    clauses = [
        f"llm_obs.quality_score:<{quality_threshold}",
        "http.status_code:[400 TO *]",
        "llm_obs.evaluations.hallucination:true",
        "llm_obs.evaluations.prompt_injection:true",
        "llm_obs.evaluations.toxicity_score:[0.7 TO *]",
        "llm_obs.guardrails.failed:true",
    ]
    query = "(" + " OR ".join(clauses) + ")"
    if service_name:
        query = f"{query} service:{service_name}"
    return query


def _build_request(
    *,
    lookback_hours: int,
    quality_threshold: float,
    service_name: Optional[str],
    page_cursor: Optional[str] = None,
) -> SpansListRequest:
    time_range = f"now-{lookback_hours}h"
    query = _build_query(service_name=service_name, quality_threshold=quality_threshold)
    attributes = SpansListRequestAttributes(
        filter=SpansQueryFilter(_from=time_range, to="now", query=query),
        options=SpansQueryOptions(timezone="UTC"),
        page=SpansListRequestPage(limit=100, cursor=page_cursor),
        sort=SpansSort("-timestamp"),
    )
    return SpansListRequest(
        data=SpansListRequestData(
            attributes=attributes,
            type=SpansListRequestType("search_request"),
        )
    )


def _create_api(settings: Settings) -> SpansApi:
    configuration = Configuration()
    configuration.server_variables["site"] = settings.datadog.site
    configuration.api_key = {"apiKeyAuth": settings.datadog.api_key, "appKeyAuth": settings.datadog.app_key}
    api_client = ApiClient(configuration)
    return SpansApi(api_client)


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

    Returns a list of span dicts from the Datadog Spans API.
    """
    settings = load_settings()
    lookback = trace_lookback_hours or settings.datadog.trace_lookback_hours
    quality = quality_threshold if quality_threshold is not None else settings.datadog.quality_threshold

    api = _create_api(settings)

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
            request = _build_request(
                lookback_hours=lookback,
                quality_threshold=quality,
                service_name=service_name,
                page_cursor=cursor,
            )
            try:
                response, _, headers = api.list_spans(body=request)
            except ApiException as exc:
                headers = getattr(exc, "headers", {}) or {}
                if exc.status == 429:
                    rate_limit_state = _extract_rate_limit_state(headers) or get_last_rate_limit_state()
                    if rate_limit_state:
                        global _LAST_RATE_LIMIT_STATE
                        _LAST_RATE_LIMIT_STATE = rate_limit_state
                    retry_after_raw = headers.get("Retry-After") or headers.get("retry-after")
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
                        raise RateLimitError(retry_after, rate_limit_state) from exc
                    time.sleep(backoff_seconds)
                    continue
                if exc.status in (401, 403):
                    raise CredentialError("Datadog credentials are missing or invalid") from exc
                raise
            except Exception:
                raise

            spans = getattr(response, "data", []) or []
            for span in spans:
                events.append(span.to_dict() if hasattr(span, "to_dict") else dict(span))
            rate_limit_state = _extract_rate_limit_state(headers)
            if rate_limit_state:
                _LAST_RATE_LIMIT_STATE = rate_limit_state
            cursor = getattr(getattr(getattr(response, "meta", None), "page", None), "after", None)
            attempts = 0
            if not cursor:
                break
        duration = time.perf_counter() - start
        logger.info(
            "datadog_query_success",
            extra={"event": "datadog_query_success", "count": len(events), "duration_sec": round(duration, 3)},
        )
    except Exception as exc:  # broad catch to surface in structured logs
        log_error(logger, "Failed to fetch Datadog failures", error=exc)
        raise

    return events
