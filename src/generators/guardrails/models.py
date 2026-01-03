"""Pydantic models for guardrail generator.

These models align with:
- specs/005-guardrail-generation/data-model.md
- specs/005-guardrail-generation/contracts/guardrail-generator-openapi.yaml
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .guardrail_types import GuardrailType


class TriggeredBy(str, Enum):
    """How the generation run was initiated."""

    SCHEDULED = "scheduled"
    MANUAL = "manual"


class SuggestionStatus(str, Enum):
    """Suggestion approval workflow status (Issue #3)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class GuardrailDraftStatus(str, Enum):
    """Guardrail draft readiness status."""

    DRAFT = "draft"
    NEEDS_HUMAN_INPUT = "needs_human_input"


class EditSource(str, Enum):
    """Source of the current draft content."""

    GENERATED = "generated"
    HUMAN = "human"


# --- Request/Response Models ---


class GuardrailRunRequest(BaseModel):
    """Request body for POST /guardrails/run-once."""

    batch_size: Optional[int] = Field(None, alias="batchSize", ge=1, le=200)
    dry_run: Optional[bool] = Field(None, alias="dryRun")
    suggestion_ids: Optional[List[str]] = Field(None, alias="suggestionIds")
    triggered_by: Optional[TriggeredBy] = Field(None, alias="triggeredBy")

    model_config = {"populate_by_name": True}


class GuardrailGenerateRequest(BaseModel):
    """Request body for POST /guardrails/generate/{suggestionId}."""

    dry_run: Optional[bool] = Field(None, alias="dryRun")
    force_overwrite: Optional[bool] = Field(None, alias="forceOverwrite")
    triggered_by: Optional[TriggeredBy] = Field(None, alias="triggeredBy")

    model_config = {"populate_by_name": True}


class GuardrailOutcomeStatus(str, Enum):
    """Per-suggestion outcome status in a batch run."""

    GENERATED = "generated"
    SKIPPED = "skipped"
    ERROR = "error"


class GuardrailOutcome(BaseModel):
    """Per-suggestion result within a run."""

    suggestion_id: str = Field(..., alias="suggestionId")
    status: GuardrailOutcomeStatus
    error_reason: Optional[str] = Field(None, alias="errorReason")
    guardrail_type: Optional[str] = Field(None, alias="guardrailType")

    model_config = {"populate_by_name": True}


class GuardrailRunSummary(BaseModel):
    """Summary of a batch generation run."""

    run_id: str = Field(..., alias="runId")
    started_at: datetime = Field(..., alias="startedAt")
    finished_at: datetime = Field(..., alias="finishedAt")
    triggered_by: TriggeredBy = Field(..., alias="triggeredBy")
    batch_size: int = Field(..., alias="batchSize")
    picked_up_count: int = Field(..., alias="pickedUpCount")
    generated_count: int = Field(..., alias="generatedCount")
    skipped_count: int = Field(..., alias="skippedCount")
    error_count: int = Field(..., alias="errorCount")
    processing_duration_ms: int = Field(..., alias="processingDurationMs")
    suggestion_outcomes: Optional[List[GuardrailOutcome]] = Field(
        None, alias="suggestionOutcomes"
    )

    model_config = {"populate_by_name": True}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Firestore-compatible dict."""
        result: Dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "triggered_by": self.triggered_by.value,
            "batch_size": self.batch_size,
            "picked_up_count": self.picked_up_count,
            "generated_count": self.generated_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "processing_duration_ms": self.processing_duration_ms,
        }
        if self.suggestion_outcomes is not None:
            result["suggestion_outcomes"] = [
                {
                    "suggestion_id": o.suggestion_id,
                    "status": o.status.value,
                    "error_reason": o.error_reason,
                    "guardrail_type": o.guardrail_type,
                }
                for o in self.suggestion_outcomes
            ]
        return result


class GuardrailGenerateResponse(BaseModel):
    """Response for POST /guardrails/generate/{suggestionId}."""

    suggestion_id: str = Field(..., alias="suggestionId")
    status: str
    guardrail: Optional[Dict[str, Any]] = None

    model_config = {"populate_by_name": True}


# --- Draft Models ---


class GuardrailDraftSource(BaseModel):
    """Tracks where this guardrail came from (lineage)."""

    suggestion_id: str
    canonical_trace_id: str
    canonical_pattern_id: str
    trace_ids: List[str]
    pattern_ids: List[str]


class GuardrailDraftGeneratorMeta(BaseModel):
    """Tracks how this guardrail was generated (auditability)."""

    model: str
    temperature: float
    prompt_hash: str
    response_sha256: str
    run_id: str
    failure_type_mapping_version: str


class GuardrailDraft(BaseModel):
    """Structured guardrail rule draft generated from failure pattern."""

    # Identification
    guardrail_id: str
    rule_name: str

    # Classification
    guardrail_type: GuardrailType
    failure_type: str

    # Configuration (guardrail-type-specific)
    configuration: Dict[str, Any]

    # Justification & Context
    description: str
    justification: str
    estimated_prevention_rate: float = Field(ge=0.0, le=1.0)

    # Lineage
    source: GuardrailDraftSource

    # Metadata
    status: GuardrailDraftStatus
    edit_source: EditSource
    generated_at: datetime
    updated_at: datetime
    generator_meta: GuardrailDraftGeneratorMeta

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Firestore-compatible dict."""
        return {
            "guardrail_id": self.guardrail_id,
            "rule_name": self.rule_name,
            "guardrail_type": self.guardrail_type.value,
            "failure_type": self.failure_type,
            "configuration": self.configuration,
            "description": self.description,
            "justification": self.justification,
            "estimated_prevention_rate": self.estimated_prevention_rate,
            "source": {
                "suggestion_id": self.source.suggestion_id,
                "canonical_trace_id": self.source.canonical_trace_id,
                "canonical_pattern_id": self.source.canonical_pattern_id,
                "trace_ids": self.source.trace_ids,
                "pattern_ids": self.source.pattern_ids,
            },
            "status": self.status.value,
            "edit_source": self.edit_source.value,
            "generated_at": self.generated_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "generator_meta": {
                "model": self.generator_meta.model,
                "temperature": self.generator_meta.temperature,
                "prompt_hash": self.generator_meta.prompt_hash,
                "response_sha256": self.generator_meta.response_sha256,
                "run_id": self.generator_meta.run_id,
                "failure_type_mapping_version": self.generator_meta.failure_type_mapping_version,
            },
        }


class ApprovalMetadata(BaseModel):
    """Approval workflow metadata from Issue #8."""

    actor: str
    action: str
    timestamp: datetime
    notes: Optional[str] = None


class GuardrailArtifactResponse(BaseModel):
    """Response for GET /guardrails/{suggestionId}."""

    suggestion_id: str
    suggestion_status: SuggestionStatus
    approval_metadata: Optional[ApprovalMetadata] = None
    guardrail: Optional[GuardrailDraft] = None


# --- Error Models ---


class GuardrailErrorType(str, Enum):
    """Types of guardrail generation errors."""

    INVALID_JSON = "invalid_json"
    SCHEMA_VALIDATION = "schema_validation"
    VERTEX_ERROR = "vertex_error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class GuardrailError(BaseModel):
    """Per-suggestion error record for diagnostic storage."""

    model_config = {"protected_namespaces": ()}

    run_id: str
    suggestion_id: str
    error_type: GuardrailErrorType
    error_message: str
    recorded_at: datetime
    model_response_sha256: Optional[str] = None
    model_response_excerpt: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Firestore-compatible dict."""
        result: Dict[str, Any] = {
            "run_id": self.run_id,
            "suggestion_id": self.suggestion_id,
            "error_type": self.error_type.value,
            "error_message": self.error_message,
            "recorded_at": self.recorded_at.isoformat(),
        }
        if self.model_response_sha256:
            result["model_response_sha256"] = self.model_response_sha256
        if self.model_response_excerpt:
            result["model_response_excerpt"] = self.model_response_excerpt
        return result


# --- Gemini Response Schema ---


class GuardrailDraftGeneratedFields(BaseModel):
    """Subset returned from Gemini (validated before composing GuardrailDraft)."""

    rule_name: str
    description: str
    justification: str
    configuration: Dict[str, Any]
    estimated_prevention_rate: float
    status: GuardrailDraftStatus


# Configuration schema definitions per guardrail type
# These match the EXAMPLE_CONFIGURATIONS in prompt_templates.py
CONFIGURATION_SCHEMAS: Dict[GuardrailType, Dict[str, Any]] = {
    GuardrailType.VALIDATION_RULE: {
        "type": "object",
        "properties": {
            "check_type": {"type": "string", "description": "When to check (pre_response, post_response)"},
            "condition": {"type": "string", "description": "What to verify"},
            "validation_source": {"type": "string", "description": "Source of truth for validation"},
        },
        "required": ["check_type", "condition"],
    },
    GuardrailType.RATE_LIMIT: {
        "type": "object",
        "properties": {
            "max_calls": {"type": "integer", "description": "Maximum API calls allowed"},
            "window_seconds": {"type": "integer", "description": "Time window in seconds"},
            "scope": {"type": "string", "description": "Scope of rate limit (session, user, global)"},
            "action": {"type": "string", "description": "Action on limit (block, warn, block_and_alert)"},
        },
        "required": ["max_calls", "window_seconds", "action"],
    },
    GuardrailType.CONTENT_FILTER: {
        "type": "object",
        "properties": {
            "filter_type": {"type": "string", "description": "Filter scope (input, output, both)"},
            "threshold": {"type": "number", "description": "Detection threshold 0.0-1.0"},
            "categories": {"type": "array", "items": {"type": "string"}, "description": "Content categories to filter"},
            "action": {"type": "string", "description": "Action on match (block, warn, redact)"},
        },
        "required": ["filter_type", "threshold", "categories", "action"],
    },
    GuardrailType.REDACTION_RULE: {
        "type": "object",
        "properties": {
            "patterns": {"type": "array", "items": {"type": "string"}, "description": "PII patterns to redact (email, phone, ssn, etc.)"},
            "custom_regex": {"type": "string", "description": "Optional custom regex pattern"},
            "scope": {"type": "string", "description": "Where to apply (input, output, both)"},
            "action": {"type": "string", "description": "Action (redact, block, warn)"},
        },
        "required": ["patterns", "scope", "action"],
    },
    GuardrailType.SCOPE_LIMIT: {
        "type": "object",
        "properties": {
            "allowed_tools": {"type": "array", "items": {"type": "string"}, "description": "Tools explicitly allowed"},
            "blocked_tools": {"type": "array", "items": {"type": "string"}, "description": "Tools explicitly blocked"},
            "context_rules": {"type": "string", "description": "When to apply restrictions"},
            "action": {"type": "string", "description": "Action on violation (block, warn)"},
        },
        "required": ["action"],
    },
    GuardrailType.FRESHNESS_CHECK: {
        "type": "object",
        "properties": {
            "max_age_hours": {"type": "integer", "description": "Maximum data age in hours"},
            "data_sources": {"type": "array", "items": {"type": "string"}, "description": "Sources to check for freshness"},
            "action": {"type": "string", "description": "Action on stale data (warn, block, refresh)"},
        },
        "required": ["max_age_hours", "action"],
    },
    GuardrailType.INPUT_SANITIZATION: {
        "type": "object",
        "properties": {
            "patterns": {"type": "array", "items": {"type": "string"}, "description": "Injection patterns to detect"},
            "custom_patterns": {"type": "array", "items": {"type": "string"}, "description": "Optional custom detection patterns"},
            "action": {"type": "string", "description": "Action on detection (block, sanitize, warn)"},
        },
        "required": ["patterns", "action"],
    },
}


def get_configuration_schema_for_type(guardrail_type: GuardrailType) -> Dict[str, Any]:
    """Get the configuration schema for a specific guardrail type.

    Args:
        guardrail_type: The guardrail type to get schema for

    Returns:
        JSON schema for the configuration object
    """
    return CONFIGURATION_SCHEMAS.get(
        guardrail_type,
        # Fallback for unknown types - validation_rule schema as default
        CONFIGURATION_SCHEMAS[GuardrailType.VALIDATION_RULE],
    )


def get_guardrail_draft_response_schema(guardrail_type: Optional[GuardrailType] = None) -> Dict[str, Any]:
    """Return JSON schema for Gemini response_schema enforcing GuardrailDraft shape.

    Args:
        guardrail_type: Optional guardrail type for type-specific configuration schema.
                       If None, uses a generic object schema (backwards compatible).

    Returns:
        JSON schema dict for Gemini response_schema parameter
    """
    # Get type-specific configuration schema or generic fallback
    if guardrail_type:
        config_schema = get_configuration_schema_for_type(guardrail_type)
    else:
        # Backwards compatible: generic object schema
        config_schema = {
            "type": "object",
            "description": "Guardrail-type-specific configuration with concrete values",
        }

    return {
        "type": "object",
        "properties": {
            "rule_name": {"type": "string"},
            "description": {"type": "string"},
            "justification": {"type": "string"},
            "configuration": config_schema,
            "estimated_prevention_rate": {"type": "number"},
            "status": {
                "type": "string",
                "enum": [e.value for e in GuardrailDraftStatus],
            },
        },
        "required": [
            "rule_name",
            "description",
            "justification",
            "configuration",
            "estimated_prevention_rate",
            "status",
        ],
    }
