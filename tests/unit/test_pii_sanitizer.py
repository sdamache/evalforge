import os

from src.ingestion import pii_sanitizer


def test_sanitize_trace_strips_pii_and_hashes_user_id(monkeypatch):
    monkeypatch.setenv("PII_SALT", "salt123")
    # Datadog event structure (Export API format)
    trace = {
        "input": {"messages": [{"content": "sensitive prompt"}]},
        "output": {"messages": [{"content": "sensitive response"}]},
        "metadata": {
            "user.email": "a@example.com",
            "user_id": "user-1",
            "client.ip": "1.1.1.1",
        },
        "tags": [
            "env:prod",
            "user.email:a@example.com",
            "pii:ssn:123-45-6789",
        ],
    }

    sanitized, user_hash = pii_sanitizer.sanitize_trace(trace)

    # Check PII fields stripped from metadata
    assert "user.email" not in sanitized.get("metadata", {})
    assert "user_id" not in sanitized.get("metadata", {})
    assert "client.ip" not in sanitized.get("metadata", {})

    # Check PII tags filtered out
    assert "user.email:a@example.com" not in sanitized["tags"]
    assert "pii:ssn:123-45-6789" not in sanitized["tags"]
    assert "env:prod" in sanitized["tags"]  # non-PII tag preserved

    # Check input/output redacted
    assert sanitized["input"] == "[redacted]"
    assert sanitized["output"] == "[redacted]"

    # sha256("user-1salt123")
    assert user_hash == "f8a4fb1973ba67e63187f3bf55289a5959dd5be244805edf09165b151e3157f3"


def test_sanitize_trace_handles_missing_user(monkeypatch):
    monkeypatch.delenv("PII_SALT", raising=False)
    # Trace without user_id
    trace = {
        "input": {"messages": [{"content": "hi"}]},
        "output": None,
        "metadata": {},
        "tags": [],
    }
    sanitized, user_hash = pii_sanitizer.sanitize_trace(trace)
    assert user_hash == ""
    assert sanitized["input"] == "[redacted]"
