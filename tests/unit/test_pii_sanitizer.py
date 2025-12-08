import os

from src.ingestion import pii_sanitizer


def test_sanitize_trace_strips_pii_and_hashes_user_id(monkeypatch):
    monkeypatch.setenv("PII_SALT", "salt123")
    trace = {
        "trace_payload": {
            "user": {"email": "a@example.com", "id": "user-1"},
            "client": {"ip": "1.1.1.1"},
            "request": {"headers": {"authorization": "secret", "cookie": "session"}},
            "input": "sensitive prompt",
            "output": "sensitive response",
        }
    }

    sanitized, user_hash = pii_sanitizer.sanitize_trace(trace)

    assert "user" in sanitized  # container may remain
    assert "email" not in sanitized["user"]
    assert "id" not in sanitized["user"]
    assert sanitized.get("client", {}).get("ip") is None
    assert sanitized.get("request", {}).get("headers", {}).get("authorization") is None
    assert sanitized["input"] == "[redacted]"
    assert sanitized["output"] == "[redacted]"
    # sha256("user-1salt123")
    assert user_hash == "f8a4fb1973ba67e63187f3bf55289a5959dd5be244805edf09165b151e3157f3"


def test_sanitize_trace_handles_missing_user(monkeypatch):
    monkeypatch.delenv("PII_SALT", raising=False)
    sanitized, user_hash = pii_sanitizer.sanitize_trace({"trace_payload": {"input": "hi"}})
    assert user_hash == ""
    assert sanitized["input"] == "[redacted]"
