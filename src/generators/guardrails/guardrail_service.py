"""Orchestration service for guardrail draft generation.

Generates guardrail rule drafts from guardrail-type suggestions using Gemini.
Maps failure types to guardrail types using deterministic mapping, selects
canonical source patterns, and generates actionable configurations.
"""

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from src.common.config import GuardrailGeneratorSettings
from src.common.logging import get_logger
from src.common.pii import redact_and_truncate
from src.generators.guardrails.firestore_repository import FirestoreRepository
from src.generators.guardrails.gemini_client import (
    GeminiAPIError,
    GeminiClient,
    GeminiClientError,
    GeminiParseError,
    GeminiRateLimitError,
)
from src.generators.guardrails.guardrail_types import (
    GUARDRAIL_MAPPING_VERSION,
    GuardrailType,
    get_guardrail_type,
)
from src.generators.guardrails.models import (
    EditSource,
    GuardrailDraft,
    GuardrailDraftGeneratedFields,
    GuardrailDraftGeneratorMeta,
    GuardrailDraftSource,
    GuardrailDraftStatus,
    GuardrailError,
    GuardrailErrorType,
    GuardrailOutcome,
    GuardrailOutcomeStatus,
    GuardrailRunSummary,
    TriggeredBy,
)
from src.generators.guardrails.prompt_templates import (
    EXAMPLE_CONFIGURATIONS,
    build_guardrail_generation_prompt,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class GenerateResult:
    """Result of generating a guardrail draft for a single suggestion."""

    status: GuardrailOutcomeStatus
    guardrail: Optional[GuardrailDraft] = None
    guardrail_type: Optional[str] = None
    error_reason: Optional[str] = None
    error_record: Optional[GuardrailError] = None
    budget_charged_usd: float = 0.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(timestamp: Optional[str]) -> Optional[datetime]:
    if not timestamp:
        return None
    ts = timestamp
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _sanitize_text(text: Optional[str], *, max_length: int = 500) -> Optional[str]:
    return redact_and_truncate(text, max_length=max_length)


def _extract_lineage(suggestion: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Extract trace_ids and pattern_ids from suggestion source_traces."""
    trace_ids: List[str] = []
    pattern_ids: List[str] = []
    for st in suggestion.get("source_traces", []) or []:
        trace_id = st.get("trace_id")
        pattern_id = st.get("pattern_id")
        if trace_id:
            trace_ids.append(trace_id)
        if pattern_id:
            pattern_ids.append(pattern_id)
    return trace_ids, pattern_ids


def _select_canonical_pattern(
    patterns: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Select canonical pattern using highest confidence, tie-breaker: most recent."""
    if not patterns:
        return None

    def key(p: Dict[str, Any]) -> Tuple[float, datetime]:
        confidence_raw = p.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        extracted_at = _parse_iso(p.get("extracted_at")) or datetime.min.replace(
            tzinfo=timezone.utc
        )
        return (confidence, extracted_at)

    return max(patterns, key=key)


# Placeholder patterns that indicate incomplete configuration (T015)
PLACEHOLDER_PATTERNS = [
    "todo",
    "tbd",
    "placeholder",
    "add appropriate",
    "fill in",
    "customize here",
    "[value]",
    "[threshold]",
    "[configure]",
    "appropriate value",
    "suitable threshold",
]


def _contains_placeholder(text: str) -> bool:
    """Check if text contains placeholder patterns indicating incomplete content."""
    if not text:
        return False
    lower_text = text.lower()
    return any(pattern in lower_text for pattern in PLACEHOLDER_PATTERNS)


def _validate_configuration_completeness(
    generated_fields: "GuardrailDraftGeneratedFields",
) -> Tuple[bool, Optional[str]]:
    """Validate that generated fields don't contain placeholder values.

    T015: Reject drafts with placeholder values and set status to needs_human_input.

    Args:
        generated_fields: The Gemini-generated fields to validate

    Returns:
        Tuple of (is_valid, reason_if_invalid)
    """
    # Check justification for placeholders
    if _contains_placeholder(generated_fields.justification):
        return False, "justification contains placeholder text"

    # Check description for placeholders
    if _contains_placeholder(generated_fields.description):
        return False, "description contains placeholder text"

    # Check rule_name for placeholders
    if _contains_placeholder(generated_fields.rule_name):
        return False, "rule_name contains placeholder text"

    # Check configuration values for placeholders
    config = generated_fields.configuration or {}
    for key, value in config.items():
        if isinstance(value, str) and _contains_placeholder(value):
            return False, f"configuration.{key} contains placeholder text"
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and _contains_placeholder(item):
                    return False, f"configuration.{key} contains placeholder text"

    return True, None


class GuardrailService:
    """Generate guardrail drafts for guardrail-type suggestions."""

    def __init__(
        self,
        *,
        settings: GuardrailGeneratorSettings,
        repository: FirestoreRepository,
        gemini_client: GeminiClient,
    ):
        self.settings = settings
        self.repository = repository
        self.gemini_client = gemini_client

    def run_batch(
        self,
        *,
        batch_size: int,
        triggered_by: TriggeredBy,
        dry_run: bool,
        suggestion_ids: Optional[List[str]] = None,
    ) -> GuardrailRunSummary:
        """Run batch generation for pending guardrail-type suggestions.

        Args:
            batch_size: Maximum suggestions to process
            triggered_by: How the run was initiated
            dry_run: If True, don't persist to Firestore
            suggestion_ids: Optional specific suggestions to process

        Returns:
            GuardrailRunSummary with outcomes for each suggestion
        """
        run_id = f"run_{_now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        started_at = _now()

        run_budget = (
            self.settings.run_cost_budget_usd
            if self.settings.run_cost_budget_usd is not None
            else batch_size * self.settings.cost_budget_usd_per_suggestion
        )
        remaining_budget = run_budget

        suggestions = self.repository.get_suggestions(
            batch_size=batch_size, suggestion_ids=suggestion_ids
        )
        picked_up_count = len(suggestions)

        outcomes: List[GuardrailOutcome] = []
        generated_count = 0
        skipped_count = 0
        error_count = 0

        max_workers = min(4, max(1, picked_up_count))
        executor = ThreadPoolExecutor(max_workers=max_workers)
        # Track cancel events for each suggestion to signal cancellation on timeout
        cancel_events: Dict[str, threading.Event] = {}
        try:
            logger.info(
                "guardrail_run_started",
                extra={
                    "event": "guardrail_run_started",
                    "run_id": run_id,
                    "triggered_by": triggered_by.value,
                    "batch_size": batch_size,
                    "picked_up_count": picked_up_count,
                    "dry_run": dry_run,
                    "run_budget_usd": run_budget,
                },
            )
            for suggestion in suggestions:
                suggestion_id = suggestion.get("suggestion_id", "")
                # Create cancel event for this suggestion
                cancel_event = threading.Event()
                cancel_events[suggestion_id] = cancel_event
                future = executor.submit(
                    self._generate_for_suggestion,
                    suggestion=suggestion,
                    run_id=run_id,
                    triggered_by=triggered_by,
                    dry_run=True,  # persistence happens outside
                    force_overwrite=False,
                    skip_if_already_has_draft=suggestion_ids is None,
                    remaining_budget=remaining_budget,
                    cancel_event=cancel_event,
                )
                try:
                    result: GenerateResult = future.result(
                        timeout=self.settings.per_suggestion_timeout_sec
                    )
                except FuturesTimeoutError:
                    # Signal cancellation to stop background Gemini calls
                    cancel_event.set()
                    result = GenerateResult(
                        status=GuardrailOutcomeStatus.ERROR,
                        error_reason="timeout",
                        error_record=GuardrailError(
                            run_id=run_id,
                            suggestion_id=suggestion_id,
                            error_type=GuardrailErrorType.TIMEOUT,
                            error_message=f"Generation exceeded {self.settings.per_suggestion_timeout_sec}s timeout.",
                            recorded_at=_now(),
                        ),
                    )
                except Exception as exc:
                    result = GenerateResult(
                        status=GuardrailOutcomeStatus.ERROR,
                        error_reason="unknown",
                        error_record=GuardrailError(
                            run_id=run_id,
                            suggestion_id=suggestion_id,
                            error_type=GuardrailErrorType.UNKNOWN,
                            error_message=str(exc),
                            recorded_at=_now(),
                        ),
                    )

                remaining_budget = max(0.0, remaining_budget - result.budget_charged_usd)

                if (
                    result.status == GuardrailOutcomeStatus.GENERATED
                    and result.guardrail is not None
                ):
                    generated_count += 1
                    if not dry_run:
                        self.repository.write_guardrail_draft(
                            suggestion_id=suggestion_id,
                            guardrail=result.guardrail.to_dict(),
                        )
                elif result.status == GuardrailOutcomeStatus.SKIPPED:
                    skipped_count += 1
                else:
                    error_count += 1

                if result.error_record is not None and not dry_run:
                    self.repository.save_error(result.error_record)

                outcomes.append(
                    GuardrailOutcome(
                        suggestionId=suggestion_id,
                        status=result.status,
                        errorReason=result.error_reason,
                        guardrailType=result.guardrail_type,
                    )
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        finished_at = _now()
        processing_duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        summary = GuardrailRunSummary(
            runId=run_id,
            startedAt=started_at,
            finishedAt=finished_at,
            triggeredBy=triggered_by,
            batchSize=batch_size,
            pickedUpCount=picked_up_count,
            generatedCount=generated_count,
            skippedCount=skipped_count,
            errorCount=error_count,
            processingDurationMs=processing_duration_ms,
            suggestionOutcomes=outcomes,
        )

        if not dry_run:
            self.repository.save_run_summary(summary)

        logger.info(
            "guardrail_run_completed",
            extra={
                "event": "guardrail_run_completed",
                "run_id": run_id,
                "triggered_by": triggered_by.value,
                "batch_size": batch_size,
                "picked_up_count": picked_up_count,
                "generated_count": generated_count,
                "skipped_count": skipped_count,
                "error_count": error_count,
                "duration_ms": processing_duration_ms,
            },
        )

        return summary

    def generate_one(
        self,
        *,
        suggestion_id: str,
        triggered_by: TriggeredBy,
        dry_run: bool,
        force_overwrite: bool,
    ) -> GenerateResult:
        """Generate guardrail draft for a single suggestion.

        Args:
            suggestion_id: The suggestion to generate for
            triggered_by: How the generation was initiated
            dry_run: If True, don't persist to Firestore
            force_overwrite: If True, overwrite human-edited drafts

        Returns:
            GenerateResult with the outcome
        """
        run_id = f"run_{_now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        suggestion = self.repository.get_suggestion(suggestion_id)
        if suggestion is None:
            logger.info(
                "guardrail_generate_not_found",
                extra={
                    "event": "guardrail_generate_not_found",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                },
            )
            return GenerateResult(
                status=GuardrailOutcomeStatus.ERROR, error_reason="not_found"
            )

        # Use cancellation event to prevent background writes after timeout
        cancel_event = threading.Event()
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(
                self._generate_for_suggestion,
                suggestion=suggestion,
                run_id=run_id,
                triggered_by=triggered_by,
                dry_run=dry_run,
                force_overwrite=force_overwrite,
                skip_if_already_has_draft=False,
                remaining_budget=self.settings.cost_budget_usd_per_suggestion,
                cancel_event=cancel_event,
            )
            try:
                result = future.result(
                    timeout=self.settings.per_suggestion_timeout_sec
                )
            except FuturesTimeoutError:
                # Signal cancellation to prevent background writes
                cancel_event.set()
                logger.info(
                    "guardrail_generation_timeout",
                    extra={
                        "event": "guardrail_generation_timeout",
                        "run_id": run_id,
                        "suggestion_id": suggestion_id,
                        "timeout_sec": self.settings.per_suggestion_timeout_sec,
                    },
                )
                result = GenerateResult(
                    status=GuardrailOutcomeStatus.ERROR,
                    error_reason="timeout",
                    error_record=GuardrailError(
                        run_id=run_id,
                        suggestion_id=suggestion_id,
                        error_type=GuardrailErrorType.TIMEOUT,
                        error_message=f"Generation exceeded {self.settings.per_suggestion_timeout_sec}s timeout.",
                        recorded_at=_now(),
                    ),
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        if result.error_record is not None and not dry_run:
            self.repository.save_error(result.error_record)
        return result

    def _generate_for_suggestion(
        self,
        *,
        suggestion: Dict[str, Any],
        run_id: str,
        triggered_by: TriggeredBy,
        dry_run: bool,
        force_overwrite: bool,
        skip_if_already_has_draft: bool,
        remaining_budget: float,
        cancel_event: Optional[threading.Event] = None,
    ) -> GenerateResult:
        """Generate guardrail draft for a single suggestion.

        Args:
            cancel_event: Optional threading.Event to check for cancellation.
                          If set, aborts before API calls or writes.
        """
        suggestion_id = suggestion.get("suggestion_id", "")

        # Type enforcement: only process guardrail-type suggestions
        suggestion_type = suggestion.get("type", "")
        if suggestion_type != "guardrail":
            logger.info(
                "guardrail_skipped",
                extra={
                    "event": "guardrail_skipped",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "reason": "wrong_suggestion_type",
                    "suggestion_type": suggestion_type,
                    "triggered_by": triggered_by.value,
                },
            )
            return GenerateResult(
                status=GuardrailOutcomeStatus.SKIPPED,
                error_reason="wrong_suggestion_type",
            )
        existing_guardrail = (
            (suggestion.get("suggestion_content") or {}).get("guardrail")
        ) or None

        # Check overwrite protection
        if existing_guardrail is not None and not force_overwrite:
            existing_edit_source = existing_guardrail.get("edit_source")
            if existing_edit_source == EditSource.HUMAN.value:
                logger.info(
                    "guardrail_skipped",
                    extra={
                        "event": "guardrail_skipped",
                        "run_id": run_id,
                        "suggestion_id": suggestion_id,
                        "reason": "overwrite_blocked",
                        "triggered_by": triggered_by.value,
                    },
                )
                return GenerateResult(
                    status=GuardrailOutcomeStatus.SKIPPED,
                    error_reason="overwrite_blocked",
                )
            if skip_if_already_has_draft:
                logger.info(
                    "guardrail_skipped",
                    extra={
                        "event": "guardrail_skipped",
                        "run_id": run_id,
                        "suggestion_id": suggestion_id,
                        "reason": "already_has_draft",
                        "triggered_by": triggered_by.value,
                    },
                )
                return GenerateResult(
                    status=GuardrailOutcomeStatus.SKIPPED,
                    error_reason="already_has_draft",
                )

        # Extract lineage and get patterns
        trace_ids, pattern_ids = _extract_lineage(suggestion)
        patterns = self.repository.get_failure_patterns(pattern_ids)
        canonical = _select_canonical_pattern(patterns)

        # Get failure type and map to guardrail type
        pattern_summary = suggestion.get("pattern", {}) or {}
        failure_type = pattern_summary.get("failure_type", "unknown")
        if canonical:
            failure_type = canonical.get("failure_type", failure_type)
        guardrail_type = get_guardrail_type(failure_type)

        # Template fallback: missing patterns
        if canonical is None:
            draft = self._template_needs_human_input(
                suggestion=suggestion,
                run_id=run_id,
                failure_type=failure_type,
                guardrail_type=guardrail_type,
                trace_ids=trace_ids,
                pattern_ids=pattern_ids,
                canonical_trace_id=trace_ids[0] if trace_ids else "unknown",
                canonical_pattern_id=pattern_ids[0] if pattern_ids else "unknown",
                reason="missing_failure_patterns",
            )
            logger.info(
                "guardrail_template_fallback",
                extra={
                    "event": "guardrail_template_fallback",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "failure_type": failure_type,
                    "guardrail_type": guardrail_type.value,
                    "reason": "missing_failure_patterns",
                    "triggered_by": triggered_by.value,
                },
            )
            return self._persist_or_return(
                suggestion_id=suggestion_id,
                draft=draft,
                guardrail_type=guardrail_type,
                dry_run=dry_run,
            )

        canonical_trace_id = (
            canonical.get("source_trace_id") or canonical.get("trace_id") or "unknown"
        )
        canonical_pattern_id = canonical.get("pattern_id") or "unknown"
        repro = canonical.get("reproduction_context") or {}

        # Template fallback: insufficient context
        if not (repro.get("input_pattern") or "").strip():
            draft = self._template_needs_human_input(
                suggestion=suggestion,
                run_id=run_id,
                failure_type=failure_type,
                guardrail_type=guardrail_type,
                trace_ids=trace_ids,
                pattern_ids=pattern_ids,
                canonical_trace_id=canonical_trace_id,
                canonical_pattern_id=canonical_pattern_id,
                reason="insufficient_reproduction_context",
            )
            logger.info(
                "guardrail_template_fallback",
                extra={
                    "event": "guardrail_template_fallback",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "failure_type": failure_type,
                    "guardrail_type": guardrail_type.value,
                    "reason": "insufficient_reproduction_context",
                    "triggered_by": triggered_by.value,
                },
            )
            return self._persist_or_return(
                suggestion_id=suggestion_id,
                draft=draft,
                guardrail_type=guardrail_type,
                dry_run=dry_run,
            )

        # Template fallback: budget exceeded
        if remaining_budget < self.settings.cost_budget_usd_per_suggestion:
            draft = self._template_needs_human_input(
                suggestion=suggestion,
                run_id=run_id,
                failure_type=failure_type,
                guardrail_type=guardrail_type,
                trace_ids=trace_ids,
                pattern_ids=pattern_ids,
                canonical_trace_id=canonical_trace_id,
                canonical_pattern_id=canonical_pattern_id,
                reason="run_budget_exceeded",
            )
            logger.info(
                "guardrail_template_fallback",
                extra={
                    "event": "guardrail_template_fallback",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "failure_type": failure_type,
                    "guardrail_type": guardrail_type.value,
                    "reason": "run_budget_exceeded",
                    "triggered_by": triggered_by.value,
                },
            )
            return self._persist_or_return(
                suggestion_id=suggestion_id,
                draft=draft,
                guardrail_type=guardrail_type,
                dry_run=dry_run,
            )

        # Check for cancellation before expensive operations
        if cancel_event is not None and cancel_event.is_set():
            logger.info(
                "guardrail_generation_cancelled",
                extra={
                    "event": "guardrail_generation_cancelled",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "stage": "before_gemini_call",
                },
            )
            return GenerateResult(
                status=GuardrailOutcomeStatus.ERROR,
                error_reason="cancelled",
            )

        # Sanitize inputs and build prompt
        sanitized_suggestion, sanitized_pattern = self._sanitize_inputs(
            suggestion=suggestion, pattern=canonical
        )
        prompt = build_guardrail_generation_prompt(
            suggestion=sanitized_suggestion,
            canonical_pattern=sanitized_pattern,
            guardrail_type=guardrail_type,
            trace_ids=trace_ids,
            pattern_ids=pattern_ids,
        )

        # Call Gemini
        try:
            response = self.gemini_client.generate_guardrail_draft(prompt)
            generated_fields = GuardrailDraftGeneratedFields.model_validate(
                response.parsed_json
            )
        except GeminiParseError as exc:
            error = GuardrailError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=GuardrailErrorType.INVALID_JSON,
                error_message=str(exc),
                recorded_at=_now(),
            )
            logger.info(
                "guardrail_generation_error",
                extra={
                    "event": "guardrail_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "failure_type": failure_type,
                    "guardrail_type": guardrail_type.value,
                    "error_type": "invalid_json",
                    "triggered_by": triggered_by.value,
                },
            )
            # Charge budget: API was called and returned (tokens consumed)
            return GenerateResult(
                status=GuardrailOutcomeStatus.ERROR,
                guardrail_type=guardrail_type.value,
                error_reason="invalid_json",
                error_record=error,
                budget_charged_usd=self.settings.cost_budget_usd_per_suggestion,
            )
        except GeminiRateLimitError as exc:
            error = GuardrailError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=GuardrailErrorType.VERTEX_ERROR,
                error_message=str(exc),
                recorded_at=_now(),
            )
            logger.info(
                "guardrail_generation_error",
                extra={
                    "event": "guardrail_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "failure_type": failure_type,
                    "guardrail_type": guardrail_type.value,
                    "error_type": "rate_limit",
                    "triggered_by": triggered_by.value,
                },
            )
            # Don't charge budget: rate limited before processing (no tokens consumed)
            return GenerateResult(
                status=GuardrailOutcomeStatus.ERROR,
                guardrail_type=guardrail_type.value,
                error_reason="rate_limit",
                error_record=error,
                budget_charged_usd=0.0,
            )
        except (GeminiAPIError, GeminiClientError) as exc:
            error = GuardrailError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=GuardrailErrorType.VERTEX_ERROR,
                error_message=str(exc),
                recorded_at=_now(),
            )
            logger.info(
                "guardrail_generation_error",
                extra={
                    "event": "guardrail_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "failure_type": failure_type,
                    "guardrail_type": guardrail_type.value,
                    "error_type": "vertex_error",
                    "triggered_by": triggered_by.value,
                },
            )
            # Charge budget conservatively: API call was attempted
            return GenerateResult(
                status=GuardrailOutcomeStatus.ERROR,
                guardrail_type=guardrail_type.value,
                error_reason="vertex_error",
                error_record=error,
                budget_charged_usd=self.settings.cost_budget_usd_per_suggestion,
            )
        except Exception as exc:
            error = GuardrailError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=GuardrailErrorType.SCHEMA_VALIDATION,
                error_message=str(exc),
                recorded_at=_now(),
                model_response_sha256=(
                    response.response_sha256 if "response" in locals() else None
                ),
                model_response_excerpt=_sanitize_text(
                    response.raw_text if "response" in locals() else None
                ),
            )
            logger.info(
                "guardrail_generation_error",
                extra={
                    "event": "guardrail_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "failure_type": failure_type,
                    "guardrail_type": guardrail_type.value,
                    "error_type": "schema_validation",
                    "triggered_by": triggered_by.value,
                },
            )
            # Charge budget if API was called (response exists)
            budget = (
                self.settings.cost_budget_usd_per_suggestion
                if "response" in locals()
                else 0.0
            )
            return GenerateResult(
                status=GuardrailOutcomeStatus.ERROR,
                guardrail_type=guardrail_type.value,
                error_reason="schema_validation",
                error_record=error,
                budget_charged_usd=budget,
            )

        # T015: Validate configuration completeness (reject placeholder values)
        is_valid, validation_reason = _validate_configuration_completeness(
            generated_fields
        )
        if not is_valid:
            logger.info(
                "guardrail_placeholder_detected",
                extra={
                    "event": "guardrail_placeholder_detected",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "failure_type": failure_type,
                    "guardrail_type": guardrail_type.value,
                    "validation_reason": validation_reason,
                },
            )
            # Override status to needs_human_input
            generated_fields = GuardrailDraftGeneratedFields(
                rule_name=generated_fields.rule_name,
                description=generated_fields.description,
                justification=generated_fields.justification,
                configuration=generated_fields.configuration,
                estimated_prevention_rate=generated_fields.estimated_prevention_rate,
                status=GuardrailDraftStatus.NEEDS_HUMAN_INPUT,
            )

        # Build draft
        now = _now()
        existing_generated_at = _parse_iso(
            existing_guardrail.get("generated_at") if existing_guardrail else None
        )

        draft = GuardrailDraft(
            guardrail_id=f"guard_{suggestion_id}",
            rule_name=_sanitize_text(generated_fields.rule_name, max_length=100)
            or "unnamed_guardrail",
            guardrail_type=guardrail_type,
            failure_type=failure_type,
            configuration=generated_fields.configuration,
            description=_sanitize_text(generated_fields.description, max_length=500)
            or "",
            justification=_sanitize_text(generated_fields.justification, max_length=800)
            or "",
            estimated_prevention_rate=max(
                0.0, min(1.0, generated_fields.estimated_prevention_rate)
            ),
            source=GuardrailDraftSource(
                suggestion_id=suggestion_id,
                canonical_trace_id=str(canonical_trace_id),
                canonical_pattern_id=str(canonical_pattern_id),
                trace_ids=[str(tid) for tid in trace_ids],
                pattern_ids=[str(pid) for pid in pattern_ids],
            ),
            status=generated_fields.status,
            edit_source=EditSource.GENERATED,
            generated_at=existing_generated_at or now,
            updated_at=now,
            generator_meta=GuardrailDraftGeneratorMeta(
                model=self.settings.gemini.model,
                temperature=self.settings.gemini.temperature,
                prompt_hash=response.prompt_hash,
                response_sha256=response.response_sha256,
                run_id=run_id,
                failure_type_mapping_version=GUARDRAIL_MAPPING_VERSION,
            ),
        )

        logger.info(
            "guardrail_generated",
            extra={
                "event": "guardrail_generated",
                "run_id": run_id,
                "suggestion_id": suggestion_id,
                "failure_type": failure_type,
                "guardrail_type": guardrail_type.value,
                "prompt_hash": response.prompt_hash,
                "response_sha256": response.response_sha256,
                "triggered_by": triggered_by.value,
            },
        )

        # Check for cancellation before Firestore write (in case Gemini completed during timeout)
        if cancel_event is not None and cancel_event.is_set():
            logger.info(
                "guardrail_generation_cancelled",
                extra={
                    "event": "guardrail_generation_cancelled",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "stage": "before_firestore_write",
                },
            )
            return GenerateResult(
                status=GuardrailOutcomeStatus.ERROR,
                error_reason="cancelled",
            )

        return self._persist_or_return(
            suggestion_id=suggestion_id,
            draft=draft,
            guardrail_type=guardrail_type,
            dry_run=dry_run,
        )

    def _persist_or_return(
        self,
        *,
        suggestion_id: str,
        draft: GuardrailDraft,
        guardrail_type: GuardrailType,
        dry_run: bool,
    ) -> GenerateResult:
        """Persist draft if not dry_run and return result."""
        if not dry_run:
            self.repository.write_guardrail_draft(
                suggestion_id=suggestion_id,
                guardrail=draft.to_dict(),
            )
        budget_charged = 0.0
        if draft.generator_meta.model == self.settings.gemini.model:
            budget_charged = self.settings.cost_budget_usd_per_suggestion
        return GenerateResult(
            status=GuardrailOutcomeStatus.GENERATED,
            guardrail=draft,
            guardrail_type=guardrail_type.value,
            budget_charged_usd=budget_charged,
        )

    def _sanitize_inputs(
        self, *, suggestion: Dict[str, Any], pattern: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Sanitize suggestion and pattern for prompt building."""
        pattern_summary = suggestion.get("pattern") or {}
        sanitized_suggestion = dict(suggestion)
        sanitized_suggestion["pattern"] = {
            "failure_type": _sanitize_text(
                pattern_summary.get("failure_type"), max_length=50
            ),
            "trigger_condition": _sanitize_text(
                pattern_summary.get("trigger_condition"), max_length=500
            ),
            "severity": _sanitize_text(pattern_summary.get("severity"), max_length=50),
            "summary": _sanitize_text(pattern_summary.get("summary"), max_length=800),
        }

        repro = pattern.get("reproduction_context") or {}
        sanitized_pattern = dict(pattern)
        sanitized_pattern["failure_type"] = _sanitize_text(
            pattern.get("failure_type"), max_length=50
        )
        sanitized_pattern["trigger_condition"] = _sanitize_text(
            pattern.get("trigger_condition"), max_length=500
        )
        sanitized_pattern["severity"] = _sanitize_text(
            pattern.get("severity"), max_length=50
        )
        sanitized_pattern["summary"] = _sanitize_text(
            pattern.get("summary"), max_length=800
        )
        sanitized_pattern["root_cause_hypothesis"] = _sanitize_text(
            pattern.get("root_cause_hypothesis"), max_length=800
        )
        sanitized_pattern["evidence"] = {
            "signals": [
                _sanitize_text(str(s), max_length=200)
                for s in (pattern.get("evidence") or {}).get("signals", [])
            ],
        }
        sanitized_pattern["reproduction_context"] = {
            "input_pattern": _sanitize_text(
                repro.get("input_pattern"), max_length=800
            ),
            "required_state": _sanitize_text(
                repro.get("required_state"), max_length=800
            ),
        }
        return sanitized_suggestion, sanitized_pattern

    def _template_needs_human_input(
        self,
        *,
        suggestion: Dict[str, Any],
        run_id: str,
        failure_type: str,
        guardrail_type: GuardrailType,
        trace_ids: List[str],
        pattern_ids: List[str],
        canonical_trace_id: str,
        canonical_pattern_id: str,
        reason: str,
    ) -> GuardrailDraft:
        """Generate template fallback draft when Gemini unavailable or context insufficient.

        T011: Template fallback method for graceful degradation.
        """
        suggestion_id = suggestion.get("suggestion_id", "")
        pattern_summary = suggestion.get("pattern") or {}
        title_hint = (
            pattern_summary.get("trigger_condition")
            or pattern_summary.get("summary")
            or "guardrail rule"
        )

        now = _now()
        payload = {
            "reason": reason,
            "suggestion_id": suggestion_id,
            "failure_type": failure_type,
            "guardrail_type": guardrail_type.value,
            "canonical_trace_id": canonical_trace_id,
            "canonical_pattern_id": canonical_pattern_id,
        }
        prompt_hash = f"sha256:{hashlib.sha256(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()}"
        response_sha = f"sha256:{hashlib.sha256(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()}"

        # Get example configuration for this guardrail type
        example_config = EXAMPLE_CONFIGURATIONS.get(guardrail_type, {})

        return GuardrailDraft(
            guardrail_id=f"guard_{suggestion_id}",
            rule_name=_sanitize_text(
                f"needs_human_input_{failure_type}", max_length=100
            )
            or "needs_human_input",
            guardrail_type=guardrail_type,
            failure_type=failure_type,
            configuration=example_config,  # Provide placeholder based on type
            description=_sanitize_text(
                f"Guardrail draft requires human input ({reason}). "
                f"Review the failure pattern and complete the configuration for: {title_hint}",
                max_length=500,
            )
            or "",
            justification=_sanitize_text(
                f"Template fallback due to: {reason}. "
                f"Please review the source traces and patterns to understand the failure, "
                f"then provide a specific justification for why this {guardrail_type.value} "
                f"would prevent recurrence.",
                max_length=800,
            )
            or "",
            estimated_prevention_rate=0.5,  # Conservative default
            source=GuardrailDraftSource(
                suggestion_id=suggestion_id,
                canonical_trace_id=str(canonical_trace_id),
                canonical_pattern_id=str(canonical_pattern_id),
                trace_ids=[str(tid) for tid in trace_ids],
                pattern_ids=[str(pid) for pid in pattern_ids],
            ),
            status=GuardrailDraftStatus.NEEDS_HUMAN_INPUT,
            edit_source=EditSource.GENERATED,
            generated_at=now,
            updated_at=now,
            generator_meta=GuardrailDraftGeneratorMeta(
                model=f"template_{reason}",
                temperature=0.0,
                prompt_hash=prompt_hash,
                response_sha256=response_sha,
                run_id=run_id,
                failure_type_mapping_version=GUARDRAIL_MAPPING_VERSION,
            ),
        )
