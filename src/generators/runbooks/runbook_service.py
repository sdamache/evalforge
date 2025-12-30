"""Orchestration service for runbook draft generation."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from src.common.config import RunbookGeneratorSettings
from src.common.logging import get_logger
from src.common.pii import redact_and_truncate
from src.generators.runbooks.firestore_repository import FirestoreRepository
from src.generators.runbooks.gemini_client import (
    GeminiAPIError,
    GeminiClient,
    GeminiClientError,
    GeminiParseError,
    GeminiRateLimitError,
)
from src.generators.runbooks.models import (
    EditSource,
    RunbookDraft,
    RunbookDraftGeneratedFields,
    RunbookDraftGeneratorMeta,
    RunbookDraftSource,
    RunbookDraftStatus,
    RunbookError,
    RunbookErrorType,
    RunbookOutcome,
    RunbookOutcomeStatus,
    RunbookRunSummary,
    TriggeredBy,
)
from src.generators.runbooks.prompt_templates import build_runbook_generation_prompt

logger = get_logger(__name__)


@dataclass(frozen=True)
class GenerateResult:
    status: RunbookOutcomeStatus
    runbook: Optional[RunbookDraft] = None
    error_reason: Optional[str] = None
    error_record: Optional[RunbookError] = None
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
    """Extract trace_ids and pattern_ids from source_traces.

    Handles both dict entries (standard format) and string entries (legacy/test data).
    """
    trace_ids: List[str] = []
    pattern_ids: List[str] = []
    for st in suggestion.get("source_traces", []) or []:
        # Handle legacy string format (just trace_id as string)
        if isinstance(st, str):
            trace_ids.append(st)
            continue
        # Standard dict format
        if isinstance(st, dict):
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


class RunbookService:
    """Generate runbook drafts for runbook-type suggestions."""

    def __init__(
        self,
        *,
        settings: RunbookGeneratorSettings,
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
    ) -> RunbookRunSummary:
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

        outcomes: List[RunbookOutcome] = []
        generated_count = 0
        skipped_count = 0
        error_count = 0

        max_workers = min(4, max(1, picked_up_count))
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            logger.info(
                "runbook_run_started",
                extra={
                    "event": "runbook_run_started",
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
                    result: GenerateResult = future.result(timeout=self.settings.per_suggestion_timeout_sec)
                except FuturesTimeoutError:
                    result = GenerateResult(
                        status=RunbookOutcomeStatus.ERROR,
                        error_reason="timeout",
                        error_record=RunbookError(
                            run_id=run_id,
                            suggestion_id=suggestion_id,
                            error_type=RunbookErrorType.TIMEOUT,
                            error_message=f"Generation exceeded {self.settings.per_suggestion_timeout_sec}s timeout.",
                            recorded_at=_now(),
                        ),
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    result = GenerateResult(
                        status=RunbookOutcomeStatus.ERROR,
                        error_reason="unknown",
                        error_record=RunbookError(
                            run_id=run_id,
                            suggestion_id=suggestion_id,
                            error_type=RunbookErrorType.UNKNOWN,
                            error_message=str(exc),
                            recorded_at=_now(),
                        ),
                    )

                remaining_budget = max(0.0, remaining_budget - result.budget_charged_usd)

                if result.status == RunbookOutcomeStatus.GENERATED and result.runbook is not None:
                    generated_count += 1
                    if not dry_run:
                        self.repository.write_runbook_draft(
                            suggestion_id=suggestion_id,
                            runbook=result.runbook.model_dump(mode="json"),
                        )
                elif result.status == RunbookOutcomeStatus.SKIPPED:
                    skipped_count += 1
                else:
                    error_count += 1

                if result.error_record is not None and not dry_run:
                    self.repository.save_error(result.error_record)

                outcomes.append(
                    RunbookOutcome(
                        suggestionId=suggestion_id,
                        status=result.status,
                        errorReason=result.error_reason,
                    )
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        finished_at = _now()
        processing_duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        summary = RunbookRunSummary(
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
            "runbook_run_completed",
            extra={
                "event": "runbook_run_completed",
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
        """Generate runbook draft for a single suggestion with timeout enforcement."""
        run_id = f"run_{_now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        suggestion = self.repository.get_suggestion(suggestion_id)
        if suggestion is None:
            logger.info(
                "runbook_generate_not_found",
                extra={"event": "runbook_generate_not_found", "run_id": run_id, "suggestion_id": suggestion_id},
            )
            return GenerateResult(status=RunbookOutcomeStatus.ERROR, error_reason="not_found")

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            # Always generate with dry_run=True internally to prevent the thread
            # from writing to Firestore if it completes after timeout.
            # Persistence is handled below only for successful, non-timed-out results.
            future = executor.submit(
                self._generate_for_suggestion,
                suggestion=suggestion,
                run_id=run_id,
                triggered_by=triggered_by,
                dry_run=True,  # Always dry_run internally; persist below if successful
                force_overwrite=force_overwrite,
                skip_if_already_has_draft=False,
                remaining_budget=self.settings.cost_budget_usd_per_suggestion,
            )
            try:
                result = future.result(timeout=self.settings.per_suggestion_timeout_sec)
            except FuturesTimeoutError:
                result = GenerateResult(
                    status=RunbookOutcomeStatus.ERROR,
                    error_reason="timeout",
                    error_record=RunbookError(
                        run_id=run_id,
                        suggestion_id=suggestion_id,
                        error_type=RunbookErrorType.TIMEOUT,
                        error_message=f"Generation exceeded {self.settings.per_suggestion_timeout_sec}s timeout.",
                        recorded_at=_now(),
                    ),
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        # Persist only after successful completion (not on timeout) and when not dry_run
        if result.status == RunbookOutcomeStatus.GENERATED and result.runbook is not None and not dry_run:
            self.repository.write_runbook_draft(
                suggestion_id=suggestion_id,
                runbook=result.runbook.model_dump(mode="json"),
            )

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
        existing_runbook = ((suggestion.get("suggestion_content") or {}).get("runbook_snippet")) or None

        if existing_runbook is not None and not force_overwrite:
            existing_edit_source = existing_runbook.get("edit_source")
            if existing_edit_source == EditSource.HUMAN.value:
                logger.info(
                    "runbook_skipped",
                    extra={
                        "event": "runbook_skipped",
                        "run_id": run_id,
                        "suggestion_id": suggestion_id,
                        "reason": "overwrite_blocked",
                        "triggered_by": triggered_by.value,
                    },
                )
                return GenerateResult(status=RunbookOutcomeStatus.SKIPPED, error_reason="overwrite_blocked")
            if skip_if_already_has_draft:
                logger.info(
                    "runbook_skipped",
                    extra={
                        "event": "runbook_skipped",
                        "run_id": run_id,
                        "suggestion_id": suggestion_id,
                        "reason": "already_has_draft",
                        "triggered_by": triggered_by.value,
                    },
                )
                return GenerateResult(status=RunbookOutcomeStatus.SKIPPED, error_reason="already_has_draft")

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
                "runbook_template_fallback",
                extra={
                    "event": "runbook_template_fallback",
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
                "runbook_template_fallback",
                extra={
                    "event": "runbook_template_fallback",
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
                "runbook_template_fallback",
                extra={
                    "event": "runbook_template_fallback",
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
        prompt = build_runbook_generation_prompt(
            suggestion=sanitized_suggestion,
            canonical_pattern=sanitized_pattern,
            trace_ids=trace_ids,
            pattern_ids=pattern_ids,
            canonical_trace_id=canonical_trace_id,
        )

        try:
            response = self.gemini_client.generate_runbook_draft(prompt)
            generated_fields = RunbookDraftGeneratedFields.model_validate(response.parsed_json)
        except GeminiParseError as exc:
            error = RunbookError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=RunbookErrorType.INVALID_JSON,
                error_message=str(exc),
                recorded_at=_now(),
            )
            logger.info(
                "runbook_generation_error",
                extra={
                    "event": "runbook_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "canonical_trace_id": canonical_trace_id,
                    "canonical_pattern_id": canonical_pattern_id,
                    "error_type": error.error_type.value,
                    "triggered_by": triggered_by.value,
                },
            )
            return GenerateResult(status=RunbookOutcomeStatus.ERROR, error_reason="invalid_json", error_record=error)
        except GeminiRateLimitError as exc:
            error = RunbookError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=RunbookErrorType.VERTEX_ERROR,
                error_message=str(exc),
                recorded_at=_now(),
            )
            logger.info(
                "runbook_generation_error",
                extra={
                    "event": "runbook_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "canonical_trace_id": canonical_trace_id,
                    "canonical_pattern_id": canonical_pattern_id,
                    "error_type": "rate_limit",
                    "triggered_by": triggered_by.value,
                },
            )
            return GenerateResult(status=RunbookOutcomeStatus.ERROR, error_reason="rate_limit", error_record=error)
        except GeminiAPIError as exc:
            error = RunbookError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=RunbookErrorType.VERTEX_ERROR,
                error_message=str(exc),
                recorded_at=_now(),
            )
            logger.info(
                "runbook_generation_error",
                extra={
                    "event": "runbook_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "canonical_trace_id": canonical_trace_id,
                    "canonical_pattern_id": canonical_pattern_id,
                    "error_type": error.error_type.value,
                    "triggered_by": triggered_by.value,
                },
            )
            return GenerateResult(status=RunbookOutcomeStatus.ERROR, error_reason="vertex_error", error_record=error)
        except GeminiClientError as exc:
            error = RunbookError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=RunbookErrorType.VERTEX_ERROR,
                error_message=str(exc),
                recorded_at=_now(),
            )
            logger.info(
                "runbook_generation_error",
                extra={
                    "event": "runbook_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "canonical_trace_id": canonical_trace_id,
                    "canonical_pattern_id": canonical_pattern_id,
                    "error_type": error.error_type.value,
                    "triggered_by": triggered_by.value,
                },
            )
            return GenerateResult(status=RunbookOutcomeStatus.ERROR, error_reason="vertex_error", error_record=error)
        except Exception as exc:
            error = RunbookError(
                run_id=run_id,
                suggestion_id=suggestion_id,
                error_type=RunbookErrorType.SCHEMA_VALIDATION,
                error_message=str(exc),
                recorded_at=_now(),
                model_response_sha256=response.response_sha256 if "response" in locals() else None,
                model_response_excerpt=_sanitize_text(response.raw_text if "response" in locals() else None),
            )
            logger.info(
                "runbook_generation_error",
                extra={
                    "event": "runbook_generation_error",
                    "run_id": run_id,
                    "suggestion_id": suggestion_id,
                    "canonical_trace_id": canonical_trace_id,
                    "canonical_pattern_id": canonical_pattern_id,
                    "error_type": error.error_type.value,
                    "triggered_by": triggered_by.value,
                },
            )
            return GenerateResult(
                status=RunbookOutcomeStatus.ERROR, error_reason="schema_validation", error_record=error
            )

        now = _now()
        existing_generated_at = _parse_iso(existing_runbook.get("generated_at") if existing_runbook else None)

        draft = RunbookDraft(
            runbook_id=f"runbook_{suggestion_id}",
            title=_sanitize_text(generated_fields.title, max_length=200) or "Untitled runbook",
            rationale=_sanitize_text(generated_fields.rationale, max_length=800) or "",
            markdown_content=generated_fields.markdown_content,  # Keep full content
            symptoms=_sanitize_list([str(s) for s in generated_fields.symptoms], max_length=300),
            diagnosis_commands=_sanitize_list([str(c) for c in generated_fields.diagnosis_commands], max_length=500),
            mitigation_steps=_sanitize_list([str(s) for s in generated_fields.mitigation_steps], max_length=500),
            escalation_criteria=_sanitize_text(generated_fields.escalation_criteria, max_length=500) or "",
            source=RunbookDraftSource(
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
            generator_meta=RunbookDraftGeneratorMeta(
                model=self.settings.gemini.model,
                temperature=self.settings.gemini.temperature,
                prompt_hash=response.prompt_hash,
                response_sha256=response.response_sha256,
                run_id=run_id,
            ),
        )

        logger.info(
            "runbook_generated",
            extra={
                "event": "runbook_generated",
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

    def _persist_or_return(self, *, suggestion_id: str, draft: RunbookDraft, dry_run: bool) -> GenerateResult:
        if not dry_run:
            self.repository.write_runbook_draft(
                suggestion_id=suggestion_id,
                runbook=draft.model_dump(mode="json"),
            )
        budget_charged = 0.0
        if draft.generator_meta.model == self.settings.gemini.model:
            budget_charged = self.settings.cost_budget_usd_per_suggestion
        return GenerateResult(status=RunbookOutcomeStatus.GENERATED, runbook=draft, budget_charged_usd=budget_charged)

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
            "severity": _sanitize_text(pattern_summary.get("severity"), max_length=20),
        }

        repro = pattern.get("reproduction_context") or {}
        sanitized_pattern = dict(pattern)
        sanitized_pattern["title"] = _sanitize_text(pattern.get("title"), max_length=200)
        sanitized_pattern["trigger_condition"] = _sanitize_text(pattern.get("trigger_condition"), max_length=500)
        sanitized_pattern["summary"] = _sanitize_text(pattern.get("summary"), max_length=800)
        sanitized_pattern["root_cause_hypothesis"] = _sanitize_text(pattern.get("root_cause_hypothesis"), max_length=800)
        sanitized_pattern["severity"] = _sanitize_text(pattern.get("severity"), max_length=20)
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
    ) -> RunbookDraft:
        suggestion_id = suggestion.get("suggestion_id", "")
        pattern_summary = suggestion.get("pattern") or {}
        failure_type = pattern_summary.get("failure_type") or "unknown"
        title_hint = pattern_summary.get("title") or failure_type

        now = _now()
        payload = {
            "reason": reason,
            "suggestion_id": suggestion_id,
            "canonical_trace_id": canonical_trace_id,
            "canonical_pattern_id": canonical_pattern_id,
        }
        prompt_hash = f"sha256:{hashlib.sha256(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()}"
        response_sha = f"sha256:{hashlib.sha256(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()}"

        # Generate a minimal template markdown
        template_markdown = f"""# {title_hint} - Operational Runbook

**Source Incident**: `{canonical_trace_id}`
**Severity**: TODO
**Generated**: {now.isoformat()}

---

## Summary
TODO: Add brief description of the failure mode.

## Symptoms
- TODO: Add observable indicators

## Diagnosis Steps
1. TODO: Add specific diagnostic commands
2. TODO: Add dashboard/log checks

## Immediate Mitigation
1. TODO: Add actions to reduce customer impact

## Root Cause Fix
1. TODO: Add long-term prevention steps

## Escalation
- **When to escalate**: TODO
- **Who to contact**: TODO
- **Escalation threshold**: TODO

---

*Template generated by EvalForge - requires human input ({reason}).*
"""

        return RunbookDraft(
            runbook_id=f"runbook_{suggestion_id}",
            title=_sanitize_text(f"Needs human input: {title_hint}", max_length=200) or "Needs human input",
            rationale=_sanitize_text(
                f"Runbook draft requires human input ({reason}). Source trace: {canonical_trace_id}. "
                "Please fill in the TODO sections with specific diagnostic commands and mitigation steps.",
                max_length=800,
            )
            or "",
            markdown_content=template_markdown,
            symptoms=["TODO: Add observable indicators that this failure is occurring"],
            diagnosis_commands=[
                "TODO: Add specific diagnostic command 1",
                "TODO: Add specific diagnostic command 2",
            ],
            mitigation_steps=["TODO: Add immediate mitigation steps"],
            escalation_criteria="TODO: Define escalation criteria",
            source=RunbookDraftSource(
                suggestion_id=suggestion_id,
                canonical_trace_id=str(canonical_trace_id),
                canonical_pattern_id=str(canonical_pattern_id),
                trace_ids=[str(tid) for tid in trace_ids],
                pattern_ids=[str(pid) for pid in pattern_ids],
            ),
            status=RunbookDraftStatus.NEEDS_HUMAN_INPUT,
            edit_source=EditSource.GENERATED,
            generated_at=now,
            updated_at=now,
            generator_meta=RunbookDraftGeneratorMeta(
                model=f"template_{reason}",
                temperature=0.0,
                prompt_hash=prompt_hash,
                response_sha256=response_sha,
                run_id=run_id,
            ),
        )
