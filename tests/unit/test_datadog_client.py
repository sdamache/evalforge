import pytest
import responses
from responses import matchers

from src.ingestion import datadog_client


@responses.activate
def test_fetch_recent_failures_handles_rate_limit(monkeypatch):
    """Test that rate limiting is handled correctly with retries."""
    monkeypatch.setenv("DATADOG_API_KEY", "test-key")
    monkeypatch.setenv("DATADOG_APP_KEY", "test-app")
    monkeypatch.setenv("DATADOG_SITE", "datadoghq.com")
    monkeypatch.setenv("TRACE_LOOKBACK_HOURS", "24")
    monkeypatch.setenv("QUALITY_THRESHOLD", "0.5")
    monkeypatch.setattr(datadog_client.time, "sleep", lambda *_args, **_kwargs: None)

    # First call returns 429 (rate limited)
    responses.add(
        responses.GET,
        "https://api.datadoghq.com/api/v2/llm-obs/v1/spans/events",
        status=429,
        headers={
            "Retry-After": "0",
            "X-RateLimit-Name": "core",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1",
        },
    )

    # Second call succeeds
    responses.add(
        responses.GET,
        "https://api.datadoghq.com/api/v2/llm-obs/v1/spans/events",
        json={
            "data": [
                {
                    "id": "test-span-1",
                    "type": "span",
                    "attributes": {
                        "trace_id": "t-rate",
                        "span_id": "s-rate",
                        "name": "test-span",
                        "status": "error",
                        "ml_app": "test-app",
                    }
                }
            ],
            "meta": {"page": None}
        },
        status=200,
        headers={
            "X-RateLimit-Name": "core",
            "X-RateLimit-Remaining": "299",
            "X-RateLimit-Reset": "60",
        },
    )

    events = datadog_client.fetch_recent_failures()
    assert len(events) == 1
    assert events[0]["trace_id"] == "t-rate"
    rate_limit = datadog_client.get_last_rate_limit_state()
    assert rate_limit["name"] == "core"


@responses.activate
def test_fetch_recent_failures_credentials_error(monkeypatch):
    """Test that credential errors are raised properly."""
    monkeypatch.setenv("DATADOG_API_KEY", "bad")
    monkeypatch.setenv("DATADOG_APP_KEY", "bad")
    monkeypatch.setenv("DATADOG_SITE", "datadoghq.com")

    responses.add(
        responses.GET,
        "https://api.datadoghq.com/api/v2/llm-obs/v1/spans/events",
        status=401,
        json={"errors": ["Unauthorized"]},
    )

    with pytest.raises(datadog_client.CredentialError):
        datadog_client.fetch_recent_failures()
