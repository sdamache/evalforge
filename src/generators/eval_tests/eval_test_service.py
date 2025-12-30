"""Orchestration service for eval test draft generation."""

from __future__ import annotations

import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from src.common.config import EvalTestGeneratorSettings
from src.common.logging import get_logger
from src.common.pii import redact_and_truncate
from src.generators.eval_tests.firestore_repository import FirestoreRepository
from src.generators.eval_tests.gemini_client import (
    GeminiAPIError,
    GeminiClient,
    GeminiClientError,
    GeminiParseError,
    GeminiRateLimitError,
)
from src.generators.eval_tests.models import (
    EditSource,
    EvalDraftStatus,
    EvalTestDraft,
    EvalTestDraftAssertions,
    EvalTestDraftGeneratedFields,
    EvalTestDraftGeneratorMeta,
    EvalTestDraftInput,
    EvalTestDraftSource,
    EvalTestError,
    EvalTestErrorType,
    EvalTestOutcome,
    EvalTestOutcomeStatus,
    EvalTestRunSummary,
    TriggeredBy,
)
from src.generators.eval_tests.prompt_templates import build_eval_test_generation_prompt

logger = get_logger(__name__)


@dataclass(frozen=True)
class GenerateResult:
    status: EvalTestOutcomeStatus
    eval_test: Optional[EvalTestDraft] = None
    error_reason: Optional[str] = None
    error_record: Optional[EvalTestError] = None
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


def _sanitize_list(items: List[str], *, max_length: int = 200) -> List[str]:
    sanitized: List[str] = []
    for item in items:
        processed = _sanitize_text(item, max_length=max_length)
        if processed:
            sanitized.append(processed)
    return sanitized


def _extract_lineage(suggestion: Dict[str, Any]) -> Tuple[List[str], List[str]]:
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


def _select_canonical_pattern(patterns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not patterns:
        return None

    def key(p: Dict[str, Any]) -> Tuple[float, datetime]:
        confidence_raw = p.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        extracted_at = _parse_iso(p.get("extracted_at")) or datetime.min.replace(tzinfo=timezone.utc)
        return (confidence, extracted_at)

    return max(patterns, key=key)


class EvalTestService:
    """Generate eval test drafts for eval-type suggestions."""

    def __init__(
        self,
        *,
        settings: EvalTestGeneratorSettings,
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
    ) -> EvalTestRunSummary:
        run_id = f"run_{_now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        started_at = _now()

        run_budget = (
            self.settings.run_cost_budget_usd
            if self.settings.run_cost_budget_usd is not None
            else batch_size * self.settings.cost_budget_usd_per_suggestion
        )
        remaining_budget = run_budget

        suggestions = self.repository.get_suggestions(batch_size=batch_size, suggestion_ids=suggestion_ids)
        picked_up_count = len(suggestions)

        outcomes: List[EvalTestOutcome] = []
        generated_count = 0
        skipped_count = 0
        error_count = 0

        max_workers = min(4, max(1, picked_up_count))
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            logger.info(
                "eval_test_run_started",
                extra={
                    "event": "eval_test_run_started",
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
                future = executor.submit(
                    self._generate_for_suggestion,
                    suggestion=suggestion,
                    run_id=run_id,
                    triggered_by=triggered_by,
                    dry_run=True,  # persistence happens outside
                    force_overwrite=False,
                    skip_if_already_has_draft=suggestion_ids is None,
                    remaining_budget=remaining_budget,
                )
                try:
                    # Note: future.result(timeout=...) will raise FuturesTimeoutError but does NOT
                    # cancel the underlying Gemini API call. Timed-out work may continue in the
                    # background and still consume quota/cost. This is a known Python threading
                    # limitation - ThreadPoolExecutor cannot interrupt running threads.
                    result: GenerateResult = future.result(timeout=self.settings.per_suggestion_timeout_sec)
                except FuturesTimeoutError:
                    result = GenerateResult(
                        status=EvalTestOutcomeStatus.ERROR,
                        error_reason="timeout",
                        error_record=EvalTestError(
                            run_id=run_id,
                            suggestion_id=suggestion_id,
                            error_type=EvalTestErrorType.TIMEOUT,
                            error_message=f"Generation exceeded {self.settings.per_suggestion_timeout_sec}s timeout.",
                            recorded_at=_now(),
                        ),
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    result = GenerateResult(
                        status=EvalTestOutcomeStatus.ERROR,
                        error_reason="unknown",
                        error_record=EvalTestError(
                            run_id=run_id,
                            suggestion_id=suggestion_id,
                            error_type=EvalTestErrorType.UNKNOWN,
                            error_message=str(exc),
                            recorded_at=_now(),
                        ),
                    )

                remaining_budget = max(0.0, remaining_budget - result.budget_charged_usd)

                if result.status == EvalTestOutcomeStatus.GENERATED and result.eval_test is not None:
                    generated_count += 1
                    if not dry_run:
                        self.repository.write_eval_test_draft(
                            suggestion_id=suggestion_id,
                            eval_test=result.eval_test.model_dump(mode="json"),
                        )
                elif result.status == EvalTestOutcomeStatus.SKIPPED:
                    skipped_count += 1
                else:
                    error_count += 1

                if result.error_record is not None and not dry_run:
                    self.repository.save_error(result.error_record)

                outcomes.append(
                    EvalTestOutcome(
                        suggestionId=suggestion_id,
                        status=result.status,
                        errorReason=result.error_reason,
                    )
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        finished_at = _now()
        processing_duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        summary = EvalTestRunSummary(
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
            "eval_test_run_completed",
            extra={
                "event": "eval_test_run_completed",
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
        """Generate eval test draft for a single suggestion with timeout enforcement.

        Uses the same per_suggestion_timeout_sec as run_batch() for consistency.
        """
        run_id = f"run_{_now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        suggestion = self.repository.get_suggestion(suggestion_id)
        if suggestion is None:
            logger.info(
                "eval_test_generate_not_found",
                extra={"event": "eval_test_generate_not_found", "run_id": run_id, "suggestion_id": suggestion_id},
            )
            return GenerateResult(status=EvalTestOutcomeStatus.ERROR, error_reason="not_found")

        # Use ThreadPoolExecutor with timeout for consistency with run_batch()
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
            )
            try:
                result = future.result(timeout=self.settings.per_suggestion_timeout_sec)
            except FuturesTimeoutError:
                result = GenerateResult(
                    status=EvalTestOutcomeStatus.ERROR,
                    error_reason="timeout",
                    error_record=EvalTestError(
                        run_id=run_id,
                        suggestion_id=suggestion_id,
                        error_type=EvalTestErrorType.TIMEOUT,
                        error_message=f"Generation exceeded {self.settings.per_suggestion_timeout_sec}s timeout.",
                        recorded_at=_now(),
                    ),
                )
        finally:
            # Note: shutdown(wait=False) releases the thread but does NOT cancel the
            # underlying Gemini API call. Timed-out work may continue in the background
            # and still consume quota/cost. This is a known Python threading limitation.
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
    ) -> GenerateResult:
        suggestion_id = suggestion.get("suggestion_id", "")
        existing_eval_test = ((suggestion.get("suggestion_content") or {}).get("eval_test")) or None

        if existing_eval_test is not None and not force_overwrite:
            existing_edit_source = existing_eval_test.get("edit_source")
            if existing_edit_source == EditSource.HUMAN.value:
                logger.info(
                    "eval_test_skipped",
                    extra={
                        "event": "eval_test_skipped",
                        "run_id": run_id,
                        "suggestion_id": suggestion_id,
                        "reason": "overwrite_blocked",
                        "triggered_by": triggered_by.value,
                    },
                )
                return GenerateResult(status=EvalTestOutcomeStatus.SKIPPED, error_reason="overwrite_blocked")
            if skip_if_already_has_draft:
                logger.info(
                    "eval_test_skipped",
                    extra={
                        "event": "eval_test_skipped",
                        "run_id": run_id,
                        "suggestion_id": suggestion_id,
                        "reason": "already_has_draft",
                        "triggered_by": triggered_by.value,
                    },
                )
                return GenerateResult(status=EvalTestOutcomeStatus.SKIPPED, error_reason="already_has_draft")

        trace_ids, pattern_ids = _extract_lineage(suggestion)
        patterns = self.repository.get_failure_patterns(pattern_ids)
        canonical = _select_canonical_pattern(patterns)

        if canonical is None:
            draft = self._template_needs_human_input(
                suggestion=suggestion,
                run_id=run_id,
                trace_ids=trace_ids,
                pattern_ids=pattern_ids,
                canonical_trace_id=trace_ids[0] if trace_ids else "unknown",
                canonical_pattern_id=pattern_ids[0] if pattern_ids else "unknown",
                reason="missing_failure_patterns",
            )
            logger.info(
                "eval_test_template_fallback",
                extra={
                    "event": "eval_test_template_fallback",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "reason": "missing_failure_patterns",
                    "canonical_trace_id": trace_ids[0] if trace_ids else None,
                    "canonical_pattern_id": pattern_ids[0] if pattern_ids else None,
                    "prompt_hash": draft.generator_meta.prompt_hash,
                    "triggered_by": triggered_by.value,
                },
            )
            return self._persist_or_return(suggestion_id=suggestion_id, draft=draft, dry_run=dry_run)

        canonical_trace_id = canonical.get("source_trace_id") or canonical.get("trace_id") or "unknown"
        canonical_pattern_id = canonical.get("pattern_id") or "unknown"
        repro = canonical.get("reproduction_context") or {}
        if not (repro.get("input_pattern") or "").strip():
            draft = self._template_needs_human_input(
                suggestion=suggestion,
                run_id=run_id,
                trace_ids=trace_ids,
                pattern_ids=pattern_ids,
                canonical_trace_id=canonical_trace_id,
                canonical_pattern_id=canonical_pattern_id,
                reason="insufficient_reproduction_context",
            )
            logger.info(
                "eval_test_template_fallback",
                extra={
                    "event": "eval_test_template_fallback",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "reason": "insufficient_reproduction_context",
                    "canonical_trace_id": canonical_trace_id,
                    "canonical_pattern_id": canonical_pattern_id,
                    "prompt_hash": draft.generator_meta.prompt_hash,
                    "triggered_by": triggered_by.value,
                },
            )
            return self._persist_or_return(suggestion_id=suggestion_id, draft=draft, dry_run=dry_run)

        if remaining_budget < self.settings.cost_budget_usd_per_suggestion:
            draft = self._template_needs_human_input(
                suggestion=suggestion,
                run_id=run_id,
                trace_ids=trace_ids,
                pattern_ids=pattern_ids,
                canonical_trace_id=canonical_trace_id,
                canonical_pattern_id=canonical_pattern_id,
                reason="run_budget_exceeded",
            )
            logger.info(
                "eval_test_template_fallback",
                extra={
                    "event": "eval_test_template_fallback",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "reason": "run_budget_exceeded",
                    "canonical_trace_id": canonical_trace_id,
                    "canonical_pattern_id": canonical_pattern_id,
                    "prompt_hash": draft.generator_meta.prompt_hash,
                    "triggered_by": triggered_by.value,
                },
            )
            return self._persist_or_return(suggestion_id=suggestion_id, draft=draft, dry_run=dry_run)

        sanitized_suggestion, sanitized_pattern = self._sanitize_inputs(suggestion=suggestion, pattern=canonical)
        prompt = build_eval_test_generation_prompt(
            suggestion=sanitized_suggestion,
            canonical_pattern=sanitized_pattern,
            trace_ids=trace_ids,
            pattern_ids=pattern_ids,
        )

        try:
            response = self.gemini_client.generate_eval_test_draft(prompt)
            generated_fields = EvalTestDraftGeneratedFields.model_validate(response.parsed_json)
        except GeminiParseError as exc:
            error = EvalTestError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=EvalTestErrorType.INVALID_JSON,
                error_message=str(exc),
                recorded_at=_now(),
            )
            logger.info(
                "eval_test_generation_error",
                extra={
                    "event": "eval_test_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "canonical_trace_id": canonical_trace_id,
                    "canonical_pattern_id": canonical_pattern_id,
                    "error_type": error.error_type.value,
                    "triggered_by": triggered_by.value,
                },
            )
            return GenerateResult(status=EvalTestOutcomeStatus.ERROR, error_reason="invalid_json", error_record=error)
        except GeminiRateLimitError as exc:
            error = EvalTestError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=EvalTestErrorType.VERTEX_ERROR,
                error_message=str(exc),
                recorded_at=_now(),
            )
            logger.info(
                "eval_test_generation_error",
                extra={
                    "event": "eval_test_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "canonical_trace_id": canonical_trace_id,
                    "canonical_pattern_id": canonical_pattern_id,
                    "error_type": "rate_limit",
                    "triggered_by": triggered_by.value,
                },
            )
            return GenerateResult(status=EvalTestOutcomeStatus.ERROR, error_reason="rate_limit", error_record=error)
        except GeminiAPIError as exc:
            error = EvalTestError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=EvalTestErrorType.VERTEX_ERROR,
                error_message=str(exc),
                recorded_at=_now(),
            )
            logger.info(
                "eval_test_generation_error",
                extra={
                    "event": "eval_test_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "canonical_trace_id": canonical_trace_id,
                    "canonical_pattern_id": canonical_pattern_id,
                    "error_type": error.error_type.value,
                    "triggered_by": triggered_by.value,
                },
            )
            return GenerateResult(status=EvalTestOutcomeStatus.ERROR, error_reason="vertex_error", error_record=error)
        except GeminiClientError as exc:
            error = EvalTestError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=EvalTestErrorType.VERTEX_ERROR,
                error_message=str(exc),
                recorded_at=_now(),
            )
            logger.info(
                "eval_test_generation_error",
                extra={
                    "event": "eval_test_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "canonical_trace_id": canonical_trace_id,
                    "canonical_pattern_id": canonical_pattern_id,
                    "error_type": error.error_type.value,
                    "triggered_by": triggered_by.value,
                },
            )
            return GenerateResult(status=EvalTestOutcomeStatus.ERROR, error_reason="vertex_error", error_record=error)
        except Exception as exc:
            error = EvalTestError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=EvalTestErrorType.SCHEMA_VALIDATION,
                error_message=str(exc),
                recorded_at=_now(),
                model_response_sha256=response.response_sha256 if "response" in locals() else None,
                model_response_excerpt=_sanitize_text(response.raw_text if "response" in locals() else None),
            )
            logger.info(
                "eval_test_generation_error",
                extra={
                    "event": "eval_test_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "canonical_trace_id": canonical_trace_id,
                    "canonical_pattern_id": canonical_pattern_id,
                    "error_type": error.error_type.value,
                    "triggered_by": triggered_by.value,
                },
            )
            return GenerateResult(
                status=EvalTestOutcomeStatus.ERROR, error_reason="schema_validation", error_record=error
            )

        now = _now()
        existing_generated_at = _parse_iso(existing_eval_test.get("generated_at") if existing_eval_test else None)

        draft = EvalTestDraft(
            eval_test_id=f"eval_{suggestion_id}",
            title=_sanitize_text(generated_fields.title, max_length=200) or "Untitled eval test",
            rationale=_sanitize_text(generated_fields.rationale, max_length=800) or "",
            source=EvalTestDraftSource(
                suggestion_id=suggestion_id,
                canonical_trace_id=str(canonical_trace_id),
                canonical_pattern_id=str(canonical_pattern_id),
                trace_ids=[str(tid) for tid in trace_ids],
                pattern_ids=[str(pid) for pid in pattern_ids],
            ),
            input=EvalTestDraftInput(
                prompt=_sanitize_text(generated_fields.input.prompt, max_length=800) or "",
                required_state=_sanitize_text(generated_fields.input.required_state, max_length=800),
                tools_involved=_sanitize_list([str(t) for t in generated_fields.input.tools_involved], max_length=100),
            ),
            assertions=EvalTestDraftAssertions(
                required=_sanitize_list([str(r) for r in generated_fields.assertions.required], max_length=300),
                forbidden=_sanitize_list([str(r) for r in generated_fields.assertions.forbidden], max_length=300),
                golden_output=_sanitize_text(generated_fields.assertions.golden_output, max_length=800),
                notes=_sanitize_text(generated_fields.assertions.notes, max_length=800),
            ),
            status=generated_fields.status,
            edit_source=EditSource.GENERATED,
            generated_at=existing_generated_at or now,
            updated_at=now,
            generator_meta=EvalTestDraftGeneratorMeta(
                model=self.settings.gemini.model,
                temperature=self.settings.gemini.temperature,
                prompt_hash=response.prompt_hash,
                response_sha256=response.response_sha256,
                run_id=run_id,
            ),
        )

        logger.info(
            "eval_test_generated",
            extra={
                "event": "eval_test_generated",
                "run_id": run_id,
                "suggestion_id": suggestion_id,
                "canonical_trace_id": canonical_trace_id,
                "canonical_pattern_id": canonical_pattern_id,
                "prompt_hash": response.prompt_hash,
                "response_sha256": response.response_sha256,
                "triggered_by": triggered_by.value,
            },
        )

        return self._persist_or_return(suggestion_id=suggestion_id, draft=draft, dry_run=dry_run)

    def _persist_or_return(self, *, suggestion_id: str, draft: EvalTestDraft, dry_run: bool) -> GenerateResult:
        if not dry_run:
            self.repository.write_eval_test_draft(
                suggestion_id=suggestion_id,
                eval_test=draft.model_dump(mode="json"),
            )
        budget_charged = 0.0
        if draft.generator_meta.model == self.settings.gemini.model:
            budget_charged = self.settings.cost_budget_usd_per_suggestion
        return GenerateResult(status=EvalTestOutcomeStatus.GENERATED, eval_test=draft, budget_charged_usd=budget_charged)

    def _sanitize_inputs(
        self, *, suggestion: Dict[str, Any], pattern: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        pattern_summary = suggestion.get("pattern") or {}
        sanitized_suggestion = dict(suggestion)
        sanitized_suggestion["pattern"] = {
            "failure_type": _sanitize_text(pattern_summary.get("failure_type"), max_length=50),
            "trigger_condition": _sanitize_text(pattern_summary.get("trigger_condition"), max_length=500),
            "title": _sanitize_text(pattern_summary.get("title"), max_length=200),
            "summary": _sanitize_text(pattern_summary.get("summary"), max_length=800),
        }

        repro = pattern.get("reproduction_context") or {}
        sanitized_pattern = dict(pattern)
        sanitized_pattern["title"] = _sanitize_text(pattern.get("title"), max_length=200)
        sanitized_pattern["trigger_condition"] = _sanitize_text(pattern.get("trigger_condition"), max_length=500)
        sanitized_pattern["summary"] = _sanitize_text(pattern.get("summary"), max_length=800)
        sanitized_pattern["root_cause_hypothesis"] = _sanitize_text(pattern.get("root_cause_hypothesis"), max_length=800)
        sanitized_pattern["evidence"] = {
            "signals": _sanitize_list([str(s) for s in (pattern.get("evidence") or {}).get("signals", [])]),
        }
        sanitized_pattern["reproduction_context"] = {
            "input_pattern": _sanitize_text(repro.get("input_pattern"), max_length=800),
            "required_state": _sanitize_text(repro.get("required_state"), max_length=800),
            "tools_involved": _sanitize_list([str(t) for t in repro.get("tools_involved", [])], max_length=100),
        }
        return sanitized_suggestion, sanitized_pattern

    def _template_needs_human_input(
        self,
        *,
        suggestion: Dict[str, Any],
        run_id: str,
        trace_ids: List[str],
        pattern_ids: List[str],
        canonical_trace_id: str,
        canonical_pattern_id: str,
        reason: str,
    ) -> EvalTestDraft:
        suggestion_id = suggestion.get("suggestion_id", "")
        pattern_summary = suggestion.get("pattern") or {}
        title_hint = pattern_summary.get("title") or pattern_summary.get("trigger_condition") or "Eval test draft"

        now = _now()
        payload = {
            "reason": reason,
            "suggestion_id": suggestion_id,
            "canonical_trace_id": canonical_trace_id,
            "canonical_pattern_id": canonical_pattern_id,
        }
        prompt_hash = f"sha256:{hashlib.sha256(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()}"
        response_sha = f"sha256:{hashlib.sha256(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()}"

        return EvalTestDraft(
            eval_test_id=f"eval_{suggestion_id}",
            title=_sanitize_text(f"Needs human input: {title_hint}", max_length=200) or "Needs human input",
            rationale=_sanitize_text(
                f"Draft requires human input ({reason}). Provide minimal, sanitized reproduction input and expected "
                "behavior based on the suggestion and failure pattern.",
                max_length=800,
            )
            or "",
            source=EvalTestDraftSource(
                suggestion_id=suggestion_id,
                canonical_trace_id=str(canonical_trace_id),
                canonical_pattern_id=str(canonical_pattern_id),
                trace_ids=[str(tid) for tid in trace_ids],
                pattern_ids=[str(pid) for pid in pattern_ids],
            ),
            input=EvalTestDraftInput(
                prompt=_sanitize_text(
                    "TODO: Add a sanitized reproduction prompt/input that reliably triggers the failure.",
                    max_length=800,
                )
                or "",
                required_state=_sanitize_text(
                    "TODO: Add minimal preconditions/state needed to reproduce (optional).",
                    max_length=800,
                ),
                tools_involved=[],
            ),
            assertions=EvalTestDraftAssertions(
                required=[
                    "Must describe the intended correct behavior in reviewer-friendly terms.",
                    "Must include at least one required rubric assertion.",
                ],
                forbidden=[
                    "Must not include raw PII or user identifiers.",
                    "Must not reproduce the known failure behavior.",
                ],
                notes=_sanitize_text(
                    f"Generation used template fallback ({reason}). Fill in input + assertions, then rerun generation "
                    "if desired.",
                    max_length=800,
                ),
            ),
            status=EvalDraftStatus.NEEDS_HUMAN_INPUT,
            edit_source=EditSource.GENERATED,
            generated_at=now,
            updated_at=now,
            generator_meta=EvalTestDraftGeneratorMeta(
                model=f"template_{reason}",
                temperature=0.0,
                prompt_hash=prompt_hash,
                response_sha256=response_sha,
                run_id=run_id,
            ),
        )
