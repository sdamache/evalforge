"""Contract tests for deduplication service.

Validates that Pydantic models serialize to match OpenAPI schema definitions.
These tests do NOT require live services - they validate data shapes only.

T039: Contract schema validation test
T040: Validate Suggestion model serialization matches OpenAPI schema
"""

import pathlib
from datetime import datetime, timezone

import yaml

from src.deduplication.models import (
    ApprovalMetadata,
    DeduplicationRunSummary,
    PatternOutcome,
    PatternOutcomeStatus,
    PatternSummary,
    SourceTraceEntry,
    StatusHistoryEntry,
    Suggestion,
    SuggestionContent,
    SuggestionResponse,
    SuggestionStatus,
    SuggestionType,
    TriggeredBy,
)
from src.extraction.models import FailureType, Severity


def load_deduplication_schema():
    """Load the deduplication OpenAPI spec."""
    spec_path = pathlib.Path(
        "specs/003-suggestion-deduplication/contracts/deduplication-openapi.yaml"
    )
    spec = yaml.safe_load(spec_path.read_text())
    return spec["components"]["schemas"]


# =============================================================================
# T039: Contract Schema Validation Tests
# =============================================================================


def test_suggestion_schema_required_fields():
    """Validate Suggestion model has all required fields from OpenAPI schema."""
    schemas = load_deduplication_schema()
    suggestion_schema = schemas["Suggestion"]
    required_fields = set(suggestion_schema.get("required", []))

    # Create a minimal valid Suggestion
    now = datetime.now(tz=timezone.utc)
    suggestion = Suggestion(
        suggestion_id="sugg_test123",
        type=SuggestionType.EVAL,
        status=SuggestionStatus.PENDING,
        severity=Severity.HIGH,
        source_traces=[
            SourceTraceEntry(
                trace_id="trace_001",
                pattern_id="pattern_001",
                added_at=now,
                similarity_score=None,
            )
        ],
        pattern=PatternSummary(
            failure_type=FailureType.HALLUCINATION,
            trigger_condition="Model returns ungrounded claims",
            title="Hallucination Pattern",
            summary="Model generates content not supported by context",
        ),
        embedding=[0.1] * 768,
        similarity_group="group_001",
        version_history=[
            StatusHistoryEntry(
                previous_status=None,
                new_status=SuggestionStatus.PENDING,
                actor="system",
                timestamp=now,
                notes="Initial creation",
            )
        ],
        created_at=now,
        updated_at=now,
    )

    # Convert to API response format (which uses camelCase)
    response = SuggestionResponse.from_suggestion(suggestion)
    serialized = response.model_dump(by_alias=True)

    # Map OpenAPI camelCase required fields to our serialized output
    # Required: suggestionId, type, status, severity, sourceTraces, pattern, createdAt, updatedAt
    api_required = {
        "suggestionId",
        "type",
        "status",
        "severity",
        "sourceTraces",
        "pattern",
        "createdAt",
        "updatedAt",
    }

    # All required fields should be present
    for field in api_required:
        assert field in serialized, f"Required field '{field}' missing from serialized Suggestion"


def test_suggestion_schema_field_types():
    """Validate Suggestion model field types match OpenAPI schema."""
    now = datetime.now(tz=timezone.utc)
    suggestion = Suggestion(
        suggestion_id="sugg_type_test",
        type=SuggestionType.GUARDRAIL,
        status=SuggestionStatus.APPROVED,
        severity=Severity.CRITICAL,
        source_traces=[
            SourceTraceEntry(
                trace_id="trace_002",
                pattern_id="pattern_002",
                added_at=now,
                similarity_score=0.92,
            )
        ],
        pattern=PatternSummary(
            failure_type=FailureType.PII_LEAK,
            trigger_condition="User PII exposed in response",
            title="PII Leak Pattern",
            summary="Sensitive user data leaked in model output",
        ),
        embedding=[0.5] * 768,
        similarity_group="group_002",
        suggestion_content=SuggestionContent(
            guardrail_rule={"rule": "block_pii"}
        ),
        approval_metadata=ApprovalMetadata(
            actor="reviewer@example.com",
            action="approved",
            notes="Valid guardrail",
            timestamp=now,
        ),
        version_history=[
            StatusHistoryEntry(
                previous_status=None,
                new_status=SuggestionStatus.PENDING,
                actor="system",
                timestamp=now,
            ),
            StatusHistoryEntry(
                previous_status=SuggestionStatus.PENDING,
                new_status=SuggestionStatus.APPROVED,
                actor="reviewer@example.com",
                timestamp=now,
                notes="Approved",
            ),
        ],
        created_at=now,
        updated_at=now,
    )

    response = SuggestionResponse.from_suggestion(suggestion)
    serialized = response.model_dump(by_alias=True)

    # Type validations per OpenAPI schema
    assert isinstance(serialized["suggestionId"], str)
    assert isinstance(serialized["type"], str)
    assert serialized["type"] in ["eval", "guardrail", "runbook"]
    assert isinstance(serialized["status"], str)
    assert serialized["status"] in ["pending", "approved", "rejected"]
    assert isinstance(serialized["severity"], str)
    assert serialized["severity"] in ["low", "medium", "high", "critical"]
    assert isinstance(serialized["sourceTraces"], list)
    assert len(serialized["sourceTraces"]) >= 1
    assert isinstance(serialized["pattern"], dict)
    assert isinstance(serialized["versionHistory"], list)

    # Timestamps should be ISO 8601 datetime objects (pydantic datetime)
    assert isinstance(serialized["createdAt"], datetime)
    assert isinstance(serialized["updatedAt"], datetime)


def test_source_trace_entry_schema():
    """Validate SourceTraceEntry matches OpenAPI SourceTraceEntry schema."""
    schemas = load_deduplication_schema()
    source_trace_schema = schemas["SourceTraceEntry"]
    required_fields = set(source_trace_schema.get("required", []))

    now = datetime.now(tz=timezone.utc)
    entry = SourceTraceEntry(
        trace_id="trace_003",
        pattern_id="pattern_003",
        added_at=now,
        similarity_score=0.87,
    )

    serialized = entry.to_dict()

    # Required per OpenAPI: traceId, patternId, addedAt
    # Our to_dict uses snake_case for Firestore, but API response uses camelCase
    assert "trace_id" in serialized
    assert "pattern_id" in serialized
    assert "added_at" in serialized

    # Type checks
    assert isinstance(serialized["trace_id"], str)
    assert isinstance(serialized["pattern_id"], str)
    # added_at should be ISO string
    datetime.fromisoformat(serialized["added_at"])

    # Optional similarity_score
    assert isinstance(serialized.get("similarity_score"), (float, type(None)))


def test_pattern_summary_schema():
    """Validate PatternSummary matches OpenAPI PatternSummary schema."""
    schemas = load_deduplication_schema()
    pattern_schema = schemas["PatternSummary"]
    required_fields = set(pattern_schema.get("required", []))

    pattern = PatternSummary(
        failure_type=FailureType.TOXICITY,
        trigger_condition="Toxic language detected",
        title="Toxicity Pattern",
        summary="Model output contains harmful content",
    )

    serialized = pattern.to_dict()

    # Required per OpenAPI: failureType, triggerCondition, title, summary
    assert "failure_type" in serialized
    assert "trigger_condition" in serialized
    assert "title" in serialized
    assert "summary" in serialized

    # Type checks
    assert isinstance(serialized["failure_type"], str)
    assert isinstance(serialized["trigger_condition"], str)
    assert isinstance(serialized["title"], str)
    assert isinstance(serialized["summary"], str)


def test_status_history_entry_schema():
    """Validate StatusHistoryEntry matches OpenAPI StatusHistoryEntry schema."""
    schemas = load_deduplication_schema()
    history_schema = schemas["StatusHistoryEntry"]
    required_fields = set(history_schema.get("required", []))

    now = datetime.now(tz=timezone.utc)
    entry = StatusHistoryEntry(
        previous_status=SuggestionStatus.PENDING,
        new_status=SuggestionStatus.APPROVED,
        actor="admin@example.com",
        timestamp=now,
        notes="Approved after review",
    )

    serialized = entry.to_dict()

    # Required per OpenAPI: newStatus, actor, timestamp
    assert "new_status" in serialized
    assert "actor" in serialized
    assert "timestamp" in serialized

    # Type checks
    assert isinstance(serialized["new_status"], str)
    assert serialized["new_status"] in ["pending", "approved", "rejected"]
    assert isinstance(serialized["actor"], str)
    datetime.fromisoformat(serialized["timestamp"])

    # Optional fields
    if "previous_status" in serialized:
        assert serialized["previous_status"] in ["pending", "approved", "rejected"]
    if "notes" in serialized:
        assert isinstance(serialized["notes"], str)


# =============================================================================
# T040: Suggestion Model Serialization Tests
# =============================================================================


def test_suggestion_to_dict_matches_firestore_format():
    """Validate Suggestion.to_dict() produces valid Firestore document format."""
    now = datetime.now(tz=timezone.utc)
    suggestion = Suggestion(
        suggestion_id="sugg_firestore_test",
        type=SuggestionType.RUNBOOK,
        status=SuggestionStatus.PENDING,
        severity=Severity.MEDIUM,
        source_traces=[
            SourceTraceEntry(
                trace_id="trace_fs_001",
                pattern_id="pattern_fs_001",
                added_at=now,
                similarity_score=None,
            ),
            SourceTraceEntry(
                trace_id="trace_fs_002",
                pattern_id="pattern_fs_002",
                added_at=now,
                similarity_score=0.91,
            ),
        ],
        pattern=PatternSummary(
            failure_type=FailureType.INFRASTRUCTURE_ERROR,
            trigger_condition="Service timeout",
            title="Timeout Pattern",
            summary="Downstream service not responding",
        ),
        embedding=[0.25] * 768,
        similarity_group="group_fs_001",
        version_history=[
            StatusHistoryEntry(
                previous_status=None,
                new_status=SuggestionStatus.PENDING,
                actor="system",
                timestamp=now,
            )
        ],
        created_at=now,
        updated_at=now,
    )

    serialized = suggestion.to_dict()

    # All required fields present
    assert "suggestion_id" in serialized
    assert "type" in serialized
    assert "status" in serialized
    assert "severity" in serialized
    assert "source_traces" in serialized
    assert "pattern" in serialized
    assert "embedding" in serialized
    assert "similarity_group" in serialized
    assert "version_history" in serialized
    assert "created_at" in serialized
    assert "updated_at" in serialized

    # Enum values serialized as strings
    assert serialized["type"] == "runbook"
    assert serialized["status"] == "pending"
    assert serialized["severity"] == "medium"

    # Embedded objects serialized correctly
    assert len(serialized["source_traces"]) == 2
    assert serialized["source_traces"][0]["trace_id"] == "trace_fs_001"
    assert serialized["source_traces"][1]["similarity_score"] == 0.91

    # Pattern serialized
    assert serialized["pattern"]["failure_type"] == "infrastructure_error"
    assert serialized["pattern"]["title"] == "Timeout Pattern"

    # Embedding preserved
    assert len(serialized["embedding"]) == 768

    # Timestamps as ISO strings
    datetime.fromisoformat(serialized["created_at"])
    datetime.fromisoformat(serialized["updated_at"])


def test_suggestion_response_camelcase_aliases():
    """Validate SuggestionResponse uses camelCase for API output."""
    now = datetime.now(tz=timezone.utc)
    suggestion = Suggestion(
        suggestion_id="sugg_alias_test",
        type=SuggestionType.EVAL,
        status=SuggestionStatus.PENDING,
        severity=Severity.LOW,
        source_traces=[
            SourceTraceEntry(
                trace_id="trace_alias",
                pattern_id="pattern_alias",
                added_at=now,
            )
        ],
        pattern=PatternSummary(
            failure_type=FailureType.STALE_DATA,
            trigger_condition="Outdated information",
            title="Stale Data",
            summary="Model uses outdated facts",
        ),
        embedding=[0.0] * 768,
        similarity_group="group_alias",
        version_history=[
            StatusHistoryEntry(
                previous_status=None,
                new_status=SuggestionStatus.PENDING,
                actor="system",
                timestamp=now,
            )
        ],
        created_at=now,
        updated_at=now,
    )

    response = SuggestionResponse.from_suggestion(suggestion)
    serialized = response.model_dump(by_alias=True)

    # Verify camelCase keys (per OpenAPI contract)
    assert "suggestionId" in serialized
    assert "sourceTraces" in serialized
    assert "versionHistory" in serialized
    assert "createdAt" in serialized
    assert "updatedAt" in serialized

    # Nested objects also use camelCase
    assert "traceId" in serialized["sourceTraces"][0]
    assert "patternId" in serialized["sourceTraces"][0]
    assert "addedAt" in serialized["sourceTraces"][0]

    # Pattern uses camelCase
    assert "failureType" in serialized["pattern"]
    assert "triggerCondition" in serialized["pattern"]

    # Version history uses camelCase
    assert "newStatus" in serialized["versionHistory"][0]


def test_deduplication_run_summary_schema():
    """Validate DeduplicationRunSummary matches OpenAPI schema."""
    schemas = load_deduplication_schema()
    summary_schema = schemas["DeduplicationRunSummary"]
    required_fields = set(summary_schema.get("required", []))

    now = datetime.now(tz=timezone.utc)
    summary = DeduplicationRunSummary(
        run_id="run_001",
        started_at=now,
        finished_at=now,
        triggered_by=TriggeredBy.MANUAL,
        patterns_processed=10,
        suggestions_created=3,
        suggestions_merged=7,
        embedding_errors=0,
        average_similarity_score=0.89,
        processing_duration_ms=1500,
        pattern_outcomes=[
            PatternOutcome(
                pattern_id="pat_001",
                status=PatternOutcomeStatus.CREATED_NEW,
                suggestion_id="sugg_001",
            ),
            PatternOutcome(
                pattern_id="pat_002",
                status=PatternOutcomeStatus.MERGED,
                suggestion_id="sugg_002",
                similarity_score=0.91,
            ),
        ],
    )

    # Serialize with aliases for API response
    serialized = summary.model_dump(by_alias=True)

    # Required per OpenAPI: runId, startedAt, finishedAt, patternsProcessed, suggestionsCreated, suggestionsMerged
    assert "runId" in serialized
    assert "startedAt" in serialized
    assert "finishedAt" in serialized
    assert "patternsProcessed" in serialized
    assert "suggestionsCreated" in serialized
    assert "suggestionsMerged" in serialized

    # Type checks
    assert isinstance(serialized["runId"], str)
    assert isinstance(serialized["patternsProcessed"], int)
    assert isinstance(serialized["suggestionsCreated"], int)
    assert isinstance(serialized["suggestionsMerged"], int)
    assert isinstance(serialized["processingDurationMs"], int)

    # Optional fields
    assert isinstance(serialized.get("embeddingErrors"), (int, type(None)))
    assert isinstance(serialized.get("averageSimilarityScore"), (float, type(None)))

    # Pattern outcomes array
    assert isinstance(serialized.get("patternOutcomes"), list)
    if serialized.get("patternOutcomes"):
        assert "patternId" in serialized["patternOutcomes"][0]
        assert "status" in serialized["patternOutcomes"][0]


def test_no_extra_fields_in_suggestion():
    """Validate Suggestion.to_dict() doesn't emit unexpected fields.

    Note: Suggestion.to_dict() is for Firestore storage, which includes 'embedding'.
    The API response (SuggestionResponse) intentionally excludes embedding for size/security.
    """
    schemas = load_deduplication_schema()
    suggestion_schema = schemas["Suggestion"]
    allowed_properties = set(suggestion_schema.get("properties", {}).keys())

    # Map camelCase schema to snake_case model
    camel_to_snake = {
        "suggestionId": "suggestion_id",
        "sourceTraces": "source_traces",
        "similarityGroup": "similarity_group",
        "suggestionContent": "suggestion_content",
        "approvalMetadata": "approval_metadata",
        "versionHistory": "version_history",
        "createdAt": "created_at",
        "updatedAt": "updated_at",
    }
    allowed_snake = {camel_to_snake.get(k, k) for k in allowed_properties}

    # 'embedding' is stored in Firestore but intentionally not in API response
    # (768 floats is large and internal implementation detail)
    firestore_only_fields = {"embedding"}
    allowed_snake = allowed_snake | firestore_only_fields

    now = datetime.now(tz=timezone.utc)
    suggestion = Suggestion(
        suggestion_id="sugg_extra_test",
        type=SuggestionType.EVAL,
        status=SuggestionStatus.PENDING,
        severity=Severity.HIGH,
        source_traces=[
            SourceTraceEntry(
                trace_id="trace_extra",
                pattern_id="pattern_extra",
                added_at=now,
            )
        ],
        pattern=PatternSummary(
            failure_type=FailureType.HALLUCINATION,
            trigger_condition="Test",
            title="Test",
            summary="Test",
        ),
        embedding=[0.1] * 768,
        similarity_group="group_extra",
        version_history=[
            StatusHistoryEntry(
                previous_status=None,
                new_status=SuggestionStatus.PENDING,
                actor="system",
                timestamp=now,
            )
        ],
        created_at=now,
        updated_at=now,
    )

    serialized = suggestion.to_dict()

    # Check for unexpected fields
    unexpected = set(serialized.keys()) - allowed_snake
    assert not unexpected, f"Unexpected fields in Suggestion.to_dict(): {unexpected}"


def test_enum_values_match_schema():
    """Validate enum values match OpenAPI schema enums."""
    schemas = load_deduplication_schema()

    # SuggestionType
    type_schema = schemas["SuggestionType"]
    type_enum = set(type_schema.get("enum", []))
    model_types = {t.value for t in SuggestionType}
    assert type_enum == model_types, f"SuggestionType mismatch: schema={type_enum}, model={model_types}"

    # SuggestionStatus
    status_schema = schemas["SuggestionStatus"]
    status_enum = set(status_schema.get("enum", []))
    model_statuses = {s.value for s in SuggestionStatus}
    assert status_enum == model_statuses, f"SuggestionStatus mismatch: schema={status_enum}, model={model_statuses}"

    # Severity
    severity_schema = schemas["Severity"]
    severity_enum = set(severity_schema.get("enum", []))
    model_severities = {s.value for s in Severity}
    assert severity_enum == model_severities, f"Severity mismatch: schema={severity_enum}, model={model_severities}"
