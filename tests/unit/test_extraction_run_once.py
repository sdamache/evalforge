"""Unit tests for extraction run-once happy path.

Tests the extraction orchestration with stubbed Gemini and fake Firestore.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.extraction.models import (
    ExtractionRunSummary,
    FailurePattern,
    FailureType,
    Severity,
    TraceOutcomeStatus,
    TriggeredBy,
)


class FakeFirestoreDocument:
    """Fake Firestore document for testing."""

    def __init__(self, doc_id: str, data: dict, exists: bool = True):
        self.id = doc_id
        self._data = data
        self.exists = exists

    def to_dict(self):
        return self._data


class FakeFirestoreCollection:
    """Fake Firestore collection for testing."""

    def __init__(self, name: str):
        self.name = name
        self.docs = {}
        self._query_filters = []

    def document(self, doc_id: str):
        return FakeFirestoreDocRef(self, doc_id)

    def where(self, field: str, op: str, value):
        # Return self to allow chaining
        self._query_filters.append((field, op, value))
        return self

    def limit(self, n: int):
        return self

    def order_by(self, field: str, direction: str = "ASCENDING"):
        return self

    def stream(self):
        # Apply filters and return matching docs
        for doc_id, data in self.docs.items():
            if self._matches_filters(data):
                yield FakeFirestoreDocument(doc_id, data)
        # Reset filters after streaming
        self._query_filters = []

    def _matches_filters(self, data: dict) -> bool:
        for field, op, value in self._query_filters:
            if op == "==" and data.get(field) != value:
                return False
        return True


class FakeFirestoreDocRef:
    """Fake Firestore document reference for testing."""

    def __init__(self, collection: FakeFirestoreCollection, doc_id: str):
        self.collection = collection
        self.doc_id = doc_id

    def get(self):
        data = self.collection.docs.get(self.doc_id)
        return FakeFirestoreDocument(
            self.doc_id,
            data if data else {},
            exists=data is not None,
        )

    def set(self, data: dict):
        self.collection.docs[self.doc_id] = data

    def update(self, data: dict):
        if self.doc_id in self.collection.docs:
            self.collection.docs[self.doc_id].update(data)
        else:
            self.collection.docs[self.doc_id] = data


class FakeFirestoreClient:
    """Fake Firestore client for testing."""

    def __init__(self):
        self.collections = {}

    def collection(self, name: str):
        if name not in self.collections:
            self.collections[name] = FakeFirestoreCollection(name)
        return self.collections[name]


class FakeFirestoreRepository:
    """Fake repository that uses in-memory storage."""

    def __init__(self, fake_client: FakeFirestoreClient, prefix: str = "evalforge_"):
        self._client = fake_client
        self.prefix = prefix

    def get_unprocessed_traces(self, batch_size: int, trace_ids=None):
        collection = self._client.collection(f"{self.prefix}raw_traces")
        if trace_ids:
            traces = []
            for trace_id in trace_ids[:batch_size]:
                if trace_id in collection.docs:
                    data = collection.docs[trace_id].copy()
                    data["trace_id"] = trace_id
                    traces.append(data)
            return traces

        # Query for unprocessed
        traces = []
        for doc_id, data in collection.docs.items():
            if not data.get("processed", False):
                trace_data = data.copy()
                trace_data["trace_id"] = doc_id
                traces.append(trace_data)
                if len(traces) >= batch_size:
                    break
        return traces

    def upsert_failure_pattern(self, pattern):
        collection = self._client.collection(f"{self.prefix}failure_patterns")
        collection.docs[pattern.source_trace_id] = pattern.to_dict()

    def mark_trace_processed(self, trace_id: str):
        collection = self._client.collection(f"{self.prefix}raw_traces")
        if trace_id in collection.docs:
            collection.docs[trace_id]["processed"] = True
            collection.docs[trace_id]["processed_at"] = datetime.now(tz=timezone.utc).isoformat()

    def save_run_summary(self, summary):
        collection = self._client.collection(f"{self.prefix}extraction_runs")
        collection.docs[summary.run_id] = summary.to_dict()

    def save_extraction_error(self, error):
        collection = self._client.collection(f"{self.prefix}extraction_errors")
        doc_id = f"{error.run_id}:{error.source_trace_id}"
        collection.docs[doc_id] = error.to_dict()

    def get_unprocessed_count(self):
        collection = self._client.collection(f"{self.prefix}raw_traces")
        return sum(1 for data in collection.docs.values() if not data.get("processed", False))

    def get_last_run_summary(self):
        collection = self._client.collection(f"{self.prefix}extraction_runs")
        if not collection.docs:
            return None
        return list(collection.docs.values())[-1]


@pytest.fixture
def fake_firestore():
    """Provide a fake Firestore client with test data."""
    client = FakeFirestoreClient()

    # Add test traces
    raw_traces = client.collection("evalforge_raw_traces")
    raw_traces.docs["trace_001"] = {
        "trace_id": "trace_001",
        "processed": False,
        "failure_type": "llm_error",
        "severity": "high",
        "trace_payload": {
            "model": "gpt-4",
            "prompt": "What is 2+2?",
            "response": "The answer is 5.",
            "error": None,
        },
    }
    raw_traces.docs["trace_002"] = {
        "trace_id": "trace_002",
        "processed": False,
        "failure_type": "tool_error",
        "severity": "medium",
        "trace_payload": {
            "model": "gpt-4",
            "prompt": "Search for weather",
            "tool_calls": [{"tool": "calculator", "input": "weather"}],
            "error": "Wrong tool",
        },
    }

    return client


@pytest.fixture
def mock_gemini_response():
    """Provide a mock Gemini response."""
    return {
        "title": "Math calculation hallucination",
        "failure_type": "hallucination",
        "trigger_condition": "Simple arithmetic question",
        "summary": "Model incorrectly calculated 2+2 as 5.",
        "root_cause_hypothesis": "Arithmetic error in model reasoning.",
        "evidence": {
            "signals": ["response contains '5' instead of '4'"],
            "excerpt": "answer is 5",
        },
        "recommended_actions": ["Add math verification layer"],
        "reproduction_context": {
            "input_pattern": "What is [number]+[number]?",
            "required_state": None,
            "tools_involved": [],
        },
        "severity": "high",
        "confidence": 0.9,
        "confidence_rationale": "Clear arithmetic error with verifiable correct answer.",
    }


def test_run_once_happy_path(fake_firestore, mock_gemini_response, monkeypatch):
    """Test successful extraction run with stubbed dependencies."""
    fake_repo = FakeFirestoreRepository(fake_firestore)

    # Mock create_firestore_repository to return our fake
    monkeypatch.setattr(
        "src.extraction.main.create_firestore_repository",
        lambda config: fake_repo,
    )

    # Mock the Gemini client
    mock_gemini = MagicMock()
    mock_gemini.extract_pattern.return_value = MagicMock(
        raw_text=json.dumps(mock_gemini_response),
        parsed_json=mock_gemini_response,
        usage_metadata={"total_token_count": 100},
    )
    mock_gemini.get_model_info.return_value = {
        "model": "gemini-2.5-flash",
        "temperature": 0.2,
        "max_output_tokens": 4096,
        "location": "us-central1",
    }

    monkeypatch.setattr(
        "src.extraction.main.create_gemini_client",
        lambda config: mock_gemini,
    )

    # Import after patching
    from src.extraction.main import run_extraction

    # Run extraction
    summary = run_extraction(
        batch_size=10,
        triggered_by=TriggeredBy.MANUAL,
        dry_run=False,
    )

    # Verify summary
    assert summary.picked_up_count == 2
    assert summary.stored_count == 2
    assert summary.error_count == 0
    assert summary.validation_failed_count == 0
    assert summary.timed_out_count == 0

    # Verify traces were marked processed
    assert fake_firestore.collection("evalforge_raw_traces").docs["trace_001"].get("processed") is True
    assert fake_firestore.collection("evalforge_raw_traces").docs["trace_002"].get("processed") is True

    # Verify patterns were stored
    patterns = fake_firestore.collection("evalforge_failure_patterns").docs
    assert "trace_001" in patterns
    assert "trace_002" in patterns


def test_run_once_dry_run(fake_firestore, mock_gemini_response, monkeypatch):
    """Test dry run mode doesn't write to Firestore."""
    fake_repo = FakeFirestoreRepository(fake_firestore)

    monkeypatch.setattr(
        "src.extraction.main.create_firestore_repository",
        lambda config: fake_repo,
    )

    # Mock the Gemini client
    mock_gemini = MagicMock()
    mock_gemini.extract_pattern.return_value = MagicMock(
        raw_text=json.dumps(mock_gemini_response),
        parsed_json=mock_gemini_response,
        usage_metadata={"total_token_count": 100},
    )
    mock_gemini.get_model_info.return_value = {
        "model": "gemini-2.5-flash",
        "temperature": 0.2,
        "max_output_tokens": 4096,
        "location": "us-central1",
    }

    monkeypatch.setattr(
        "src.extraction.main.create_gemini_client",
        lambda config: mock_gemini,
    )

    from src.extraction.main import run_extraction

    # Run extraction in dry_run mode
    summary = run_extraction(
        batch_size=10,
        triggered_by=TriggeredBy.MANUAL,
        dry_run=True,
    )

    # Verify summary shows success
    assert summary.picked_up_count == 2
    assert summary.stored_count == 2

    # Verify traces were NOT marked processed
    assert fake_firestore.collection("evalforge_raw_traces").docs["trace_001"].get("processed") is False
    assert fake_firestore.collection("evalforge_raw_traces").docs["trace_002"].get("processed") is False

    # Verify patterns were NOT stored
    patterns = fake_firestore.collection("evalforge_failure_patterns").docs
    assert len(patterns) == 0


def test_run_once_handles_validation_error(fake_firestore, monkeypatch):
    """Test extraction handles Gemini output that fails schema validation."""
    fake_repo = FakeFirestoreRepository(fake_firestore)

    monkeypatch.setattr(
        "src.extraction.main.create_firestore_repository",
        lambda config: fake_repo,
    )

    # Mock Gemini to return invalid output (missing required fields)
    mock_gemini = MagicMock()
    mock_gemini.extract_pattern.return_value = MagicMock(
        raw_text='{"title": "Test"}',  # Missing required fields
        parsed_json={"title": "Test"},
        usage_metadata={"total_token_count": 50},
    )
    mock_gemini.get_model_info.return_value = {
        "model": "gemini-2.5-flash",
        "temperature": 0.2,
        "max_output_tokens": 4096,
        "location": "us-central1",
    }

    monkeypatch.setattr(
        "src.extraction.main.create_gemini_client",
        lambda config: mock_gemini,
    )

    from src.extraction.main import run_extraction

    # Run extraction
    summary = run_extraction(
        batch_size=10,
        triggered_by=TriggeredBy.MANUAL,
        dry_run=False,
    )

    # Verify validation failures were recorded
    assert summary.picked_up_count == 2
    assert summary.stored_count == 0
    assert summary.validation_failed_count == 2

    # Verify error records were stored
    errors = fake_firestore.collection("evalforge_extraction_errors").docs
    assert len(errors) == 2


def test_run_once_with_explicit_trace_ids(fake_firestore, mock_gemini_response, monkeypatch):
    """Test extraction with explicit trace IDs."""
    fake_repo = FakeFirestoreRepository(fake_firestore)

    monkeypatch.setattr(
        "src.extraction.main.create_firestore_repository",
        lambda config: fake_repo,
    )

    # Mock the Gemini client
    mock_gemini = MagicMock()
    mock_gemini.extract_pattern.return_value = MagicMock(
        raw_text=json.dumps(mock_gemini_response),
        parsed_json=mock_gemini_response,
        usage_metadata={"total_token_count": 100},
    )
    mock_gemini.get_model_info.return_value = {
        "model": "gemini-2.5-flash",
        "temperature": 0.2,
        "max_output_tokens": 4096,
        "location": "us-central1",
    }

    monkeypatch.setattr(
        "src.extraction.main.create_gemini_client",
        lambda config: mock_gemini,
    )

    from src.extraction.main import run_extraction

    # Run extraction with specific trace ID
    summary = run_extraction(
        batch_size=10,
        triggered_by=TriggeredBy.MANUAL,
        dry_run=False,
        trace_ids=["trace_001"],  # Only process one trace
    )

    # Verify only one trace processed
    assert summary.picked_up_count == 1
    assert summary.stored_count == 1


def test_parse_gemini_output_valid():
    """Test parsing a valid Gemini response."""
    from src.extraction.main import _parse_gemini_output

    parsed_json = {
        "title": "Test Pattern",
        "failure_type": "hallucination",
        "trigger_condition": "Test condition",
        "summary": "Test summary",
        "root_cause_hypothesis": "Test hypothesis",
        "evidence": {
            "signals": ["signal1", "signal2"],
            "excerpt": "test excerpt with user@email.com",  # Should be redacted
        },
        "recommended_actions": ["action1"],
        "reproduction_context": {
            "input_pattern": "test pattern",
            "required_state": None,
            "tools_involved": ["tool1"],
        },
        "severity": "high",
        "confidence": 0.85,
        "confidence_rationale": "Test rationale",
    }

    pattern = _parse_gemini_output(parsed_json, "trace_123")

    assert pattern.pattern_id == "pattern_trace_123"
    assert pattern.source_trace_id == "trace_123"
    assert pattern.failure_type == FailureType.HALLUCINATION
    assert pattern.confidence == 0.85
    # Email should be redacted in excerpt
    assert "user@email.com" not in (pattern.evidence.excerpt or "")


def test_generate_pattern_id():
    """Test pattern ID generation is stable."""
    from src.extraction.main import _generate_pattern_id

    pattern_id = _generate_pattern_id("trace_abc123")
    assert pattern_id == "pattern_trace_abc123"

    # Should be deterministic
    assert _generate_pattern_id("trace_abc123") == pattern_id
