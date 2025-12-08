"""Datadog client helper to fetch recent LLM failure traces."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from datadog_api_client import ApiClient, Configuration
from datadog_api_client.v2.api.spans_api import SpansApi
from datadog_api_client.v2.model.spans_list_request import SpansListRequest
from datadog_api_client.v2.model.spans_list_request_attributes import SpansListRequestAttributes
from datadog_api_client.v2.model.spans_list_request_data import SpansListRequestData
from datadog_api_client.v2.model.spans_list_request_page import SpansListRequestPage
from datadog_api_client.v2.model.spans_list_request_type import SpansListRequestType
from datadog_api_client.v2.model.spans_query_filter import SpansQueryFilter
from datadog_api_client.v2.model.spans_query_options import SpansQueryOptions
from datadog_api_client.v2.model.spans_sort import SpansSort
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.common.config import Settings, load_settings
from src.common.logging import get_logger, log_error

logger = get_logger(__name__)


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
) -> SpansListRequest:
    time_range = f"now-{lookback_hours}h"
    query = _build_query(service_name=service_name, quality_threshold=quality_threshold)
    attributes = SpansListRequestAttributes(
        filter=SpansQueryFilter(_from=time_range, to="now", query=query),
        options=SpansQueryOptions(timezone="UTC"),
        page=SpansListRequestPage(limit=100),
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


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=8),
    retry=retry_if_exception_type(Exception),
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

    request = _build_request(
        lookback_hours=lookback,
        quality_threshold=quality,
        service_name=service_name,
    )

    api = _create_api(settings)

    events: List[Dict[str, Any]] = []
    try:
        logger.info(
            "query_datadog",
            extra={
                "event": "datadog_query",
                "lookback_hours": lookback,
                "quality_threshold": quality,
                "service_name": service_name,
            },
        )
        for span in api.list_spans_with_pagination(body=request):
            events.append(span.to_dict() if hasattr(span, "to_dict") else dict(span))
        logger.info("datadog_query_success", extra={"event": "datadog_query_success", "count": len(events)})
    except Exception as exc:  # broad catch to surface in structured logs
        log_error(logger, "Failed to fetch Datadog failures", error=exc)
        raise

    return events
