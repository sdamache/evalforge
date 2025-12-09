import pytest
from datadog_api_client.exceptions import ApiException

from src.ingestion import datadog_client


def test_fetch_recent_failures_handles_rate_limit(monkeypatch):
    class FakeSpan:
        def to_dict(self):
            return {"trace_id": "t-rate", "trace_payload": {}}

    class FakePage:
        def __init__(self, after=None):
            self.after = after

    class FakeMeta:
        def __init__(self, after=None):
            self.page = FakePage(after=after)

    class FakeResponse:
        def __init__(self, after=None):
            self.data = [FakeSpan()]
            self.meta = FakeMeta(after=after)

    class FakeApi:
        def __init__(self):
            self.calls = 0

        def list_spans(self, *_, **__):
            self.calls += 1
            if self.calls == 1:
                headers = {
                    "Retry-After": "0",
                    "X-RateLimit-Name": "core",
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": "1",
                }
                exc = ApiException(status=429)
                exc.status = 429
                exc.headers = headers
                raise exc
            headers = {
                "X-RateLimit-Name": "core",
                "X-RateLimit-Remaining": "299",
                "X-RateLimit-Reset": "60",
            }
            return FakeResponse(after=None), None, headers

    monkeypatch.setenv("DATADOG_API_KEY", "test-key")
    monkeypatch.setenv("DATADOG_APP_KEY", "test-app")
    monkeypatch.setenv("DATADOG_SITE", "datadoghq.com")
    monkeypatch.setenv("TRACE_LOOKBACK_HOURS", "24")
    monkeypatch.setenv("QUALITY_THRESHOLD", "0.5")
    monkeypatch.setattr(datadog_client, "_create_api", lambda settings: FakeApi())
    monkeypatch.setattr(datadog_client, "_build_request", lambda **kwargs: {})
    monkeypatch.setattr(datadog_client.time, "sleep", lambda *_args, **_kwargs: None)

    events = datadog_client.fetch_recent_failures()
    assert events and events[0]["trace_id"] == "t-rate"
    rate_limit = datadog_client.get_last_rate_limit_state()
    assert rate_limit["name"] == "core"


def test_fetch_recent_failures_credentials_error(monkeypatch):
    class FakeApi:
        def list_spans(self, *_, **__):
            raise ApiException(status=401, reason="Unauthorized")

    monkeypatch.setenv("DATADOG_API_KEY", "bad")
    monkeypatch.setenv("DATADOG_APP_KEY", "bad")
    monkeypatch.setenv("DATADOG_SITE", "datadoghq.com")
    monkeypatch.setattr(datadog_client, "_create_api", lambda settings: FakeApi())
    monkeypatch.setattr(datadog_client, "_build_request", lambda **kwargs: {})

    with pytest.raises(datadog_client.CredentialError):
        datadog_client.fetch_recent_failures()
