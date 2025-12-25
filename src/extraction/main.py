"""Extraction service FastAPI app with /health and /extraction/run-once endpoints.

This is the main entry point for the Cloud Run extraction service.
It reads unprocessed traces from Firestore, calls Gemini to extract patterns,
validates outputs, and persists results.

Includes:
- T015: FastAPI skeleton + /health
- T020: POST /extraction/run-once orchestration
- T023: Structured per-trace and per-run logs
- T027: Schema validation before writes (from Phase 4)
- T033: Per-trace time budget enforcement (from Phase 5)
"""

import asyncio
import hashlib
import logging
import time
import uuid
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from src.common.config import load_extraction_settings
from src.common.logging import get_logger
from src.common.pii import redact_and_truncate
from src.extraction.firestore_repository import (
    FirestoreRepository,
    FirestoreRepositoryError,
    create_firestore_repository,
)
from src.extraction.gemini_client import (
    GeminiClient,
    GeminiClientError,
    GeminiParseError,
    GeminiTimeoutError,
    create_gemini_client,
)
from src.extraction.models import (
    Evidence,
    ExtractionError,
    ExtractionErrorType,
    ExtractionRunRequest,
    ExtractionRunSummary,
    FailurePattern,
    FailureType,
    ReproductionContext,
    Severity,
    TraceOutcome,
    TraceOutcomeStatus,
    TriggeredBy,
)
from src.extraction.prompt_templates import build_extraction_prompt, compute_prompt_hash
from src.extraction.trace_utils import (
    prepare_trace_for_extraction,
    validate_trace_has_required_fields,
)

app = FastAPI(title="Evalforge Failure Pattern Extraction")
logger = get_logger(__name__)

# In-memory health state
LAST_RUN_STATE: Dict[str, Any] = {
    "last_run_id": None,
    "last_run_at": None,
    "last_stored_count": 0,
    "last_error_count": 0,
    "last_error": None,
}


def _generate_run_id() -> str:
    """Generate a unique run ID."""
    return f"run_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _generate_pattern_id(source_trace_id: str) -> str:
    """Generate a stable pattern ID from the source trace ID."""
    return f"pattern_{source_trace_id}"


def _parse_gemini_output(
    parsed_json: Dict[str, Any],
    source_trace_id: str,
) -> FailurePattern:
    """Parse and validate Gemini output into a FailurePattern.

    Args:
        parsed_json: The parsed JSON from Gemini response.
        source_trace_id: The source trace ID for reference.

    Returns:
        Validated FailurePattern instance.

    Raises:
        ValidationError: If the output doesn't match the schema.
    """
    # Redact excerpt if present (max 500 chars for evidence excerpts)
    evidence_data = parsed_json.get("evidence", {})
    raw_excerpt = evidence_data.get("excerpt")
    redacted_excerpt = redact_and_truncate(raw_excerpt, max_length=500) if raw_excerpt else None

    # Build the FailurePattern
    pattern = FailurePattern(
        pattern_id=_generate_pattern_id(source_trace_id),
        source_trace_id=source_trace_id,
        title=parsed_json["title"],
        failure_type=FailureType(parsed_json["failure_type"]),
        trigger_condition=parsed_json["trigger_condition"],
        summary=parsed_json["summary"],
        root_cause_hypothesis=parsed_json["root_cause_hypothesis"],
        evidence=Evidence(
            signals=evidence_data.get("signals", []),
            excerpt=redacted_excerpt,
        ),
        recommended_actions=parsed_json.get("recommended_actions", []),
        reproduction_context=ReproductionContext(
            input_pattern=parsed_json.get("reproduction_context", {}).get("input_pattern", ""),
            required_state=parsed_json.get("reproduction_context", {}).get("required_state"),
            tools_involved=parsed_json.get("reproduction_context", {}).get("tools_involved", []),
        ),
        severity=Severity(parsed_json["severity"]),
        confidence=parsed_json["confidence"],
        confidence_rationale=parsed_json["confidence_rationale"],
        extracted_at=datetime.now(tz=timezone.utc),
    )

    return pattern


def _process_single_trace(
    trace_data: Dict[str, Any],
    gemini_client: GeminiClient,
    repository: FirestoreRepository,
    run_id: str,
    timeout_sec: float,
    dry_run: bool = False,
) -> TraceOutcome:
    """Process a single trace with timeout enforcement.

    Args:
        trace_data: The trace document from Firestore.
        gemini_client: The Gemini client instance.
        repository: The Firestore repository.
        run_id: Current run ID for logging.
        timeout_sec: Per-trace time budget in seconds.
        dry_run: If True, skip writes.

    Returns:
        TraceOutcome indicating the result.
    """
    trace_id = trace_data.get("trace_id", "unknown")
    start_time = time.perf_counter()

    # Log trace pickup
    logger.info(
        "trace_picked_up",
        extra={
            "event": "trace_picked_up",
            "run_id": run_id,
            "source_trace_id": trace_id,
        },
    )

    try:
        # Validate trace has required fields
        is_valid, error_msg = validate_trace_has_required_fields(trace_data)
        if not is_valid:
            logger.warning(
                "trace_invalid",
                extra={
                    "event": "trace_invalid",
                    "run_id": run_id,
                    "source_trace_id": trace_id,
                    "reason": error_msg,
                },
            )
            return TraceOutcome(
                source_trace_id=trace_id,
                status=TraceOutcomeStatus.SKIPPED,
                error_reason=error_msg,
            )

        # Prepare trace for extraction (includes truncation if needed)
        prepared_payload, prep_metadata = prepare_trace_for_extraction(trace_data)

        if prep_metadata["was_truncated"]:
            logger.info(
                "trace_truncated",
                extra={
                    "event": "trace_truncated",
                    "run_id": run_id,
                    "source_trace_id": trace_id,
                    "original_size": prep_metadata["original_size_bytes"],
                    "final_size": prep_metadata["final_size_bytes"],
                },
            )

        # Build extraction prompt
        prompt = build_extraction_prompt(prepared_payload)
        prompt_hash = compute_prompt_hash(prompt)

        # Log model call
        model_info = gemini_client.get_model_info()
        logger.info(
            "gemini_call_started",
            extra={
                "event": "gemini_call_started",
                "run_id": run_id,
                "source_trace_id": trace_id,
                "prompt_hash": prompt_hash,
                "model": model_info["model"],
                "temperature": model_info["temperature"],
            },
        )

        # Check time budget before making call
        elapsed = time.perf_counter() - start_time
        if elapsed >= timeout_sec:
            raise TimeoutError("Time budget exceeded before Gemini call")

        # Make Gemini call
        response = gemini_client.extract_pattern(prompt)

        # Check time budget after call
        elapsed = time.perf_counter() - start_time
        if elapsed >= timeout_sec:
            raise TimeoutError("Time budget exceeded after Gemini call")

        # Parse and validate the response (T027: schema validation)
        try:
            pattern = _parse_gemini_output(response.parsed_json, trace_id)
        except (ValidationError, KeyError, ValueError) as e:
            # Schema validation failed
            logger.warning(
                "schema_validation_failed",
                extra={
                    "event": "schema_validation_failed",
                    "run_id": run_id,
                    "source_trace_id": trace_id,
                    "error": str(e),
                },
            )

            # Store error record
            if not dry_run:
                error_record = ExtractionError(
                    run_id=run_id,
                    source_trace_id=trace_id,
                    error_type=ExtractionErrorType.SCHEMA_VALIDATION,
                    error_message=str(e),
                    model_response_sha256=hashlib.sha256(
                        response.raw_text.encode()
                    ).hexdigest(),
                    model_response_excerpt=redact_and_truncate(response.raw_text, max_length=200) if response.raw_text else None,
                    recorded_at=datetime.now(tz=timezone.utc),
                )
                repository.save_extraction_error(error_record)

            return TraceOutcome(
                source_trace_id=trace_id,
                status=TraceOutcomeStatus.VALIDATION_FAILED,
                error_reason=str(e),
            )

        # Write pattern and mark trace processed
        if not dry_run:
            repository.upsert_failure_pattern(pattern)
            repository.mark_trace_processed(trace_id)

        # Calculate duration
        duration_sec = time.perf_counter() - start_time

        # Log success
        logger.info(
            "pattern_extracted",
            extra={
                "event": "pattern_extracted",
                "run_id": run_id,
                "source_trace_id": trace_id,
                "pattern_id": pattern.pattern_id,
                "failure_type": pattern.failure_type.value,
                "confidence": pattern.confidence,
                "duration_sec": round(duration_sec, 3),
                "dry_run": dry_run,
            },
        )

        return TraceOutcome(
            source_trace_id=trace_id,
            status=TraceOutcomeStatus.STORED,
            pattern_id=pattern.pattern_id,
        )

    except GeminiTimeoutError as e:
        # Gemini API call exceeded request timeout (from ThreadPoolExecutor)
        duration_sec = time.perf_counter() - start_time
        logger.warning(
            "gemini_timeout",
            extra={
                "event": "gemini_timeout",
                "run_id": run_id,
                "source_trace_id": trace_id,
                "duration_sec": round(duration_sec, 3),
                "timeout_sec": timeout_sec,
            },
        )

        if not dry_run:
            error_record = ExtractionError(
                run_id=run_id,
                source_trace_id=trace_id,
                error_type=ExtractionErrorType.TIMEOUT,
                error_message=str(e),
                recorded_at=datetime.now(tz=timezone.utc),
            )
            repository.save_extraction_error(error_record)

        return TraceOutcome(
            source_trace_id=trace_id,
            status=TraceOutcomeStatus.TIMED_OUT,
            error_reason=f"Gemini request exceeded timeout",
        )

    except TimeoutError as e:
        duration_sec = time.perf_counter() - start_time
        logger.warning(
            "trace_timed_out",
            extra={
                "event": "trace_timed_out",
                "run_id": run_id,
                "source_trace_id": trace_id,
                "duration_sec": round(duration_sec, 3),
                "timeout_sec": timeout_sec,
            },
        )

        if not dry_run:
            error_record = ExtractionError(
                run_id=run_id,
                source_trace_id=trace_id,
                error_type=ExtractionErrorType.TIMEOUT,
                error_message=str(e),
                recorded_at=datetime.now(tz=timezone.utc),
            )
            repository.save_extraction_error(error_record)

        return TraceOutcome(
            source_trace_id=trace_id,
            status=TraceOutcomeStatus.TIMED_OUT,
            error_reason=f"Exceeded {timeout_sec}s budget",
        )

    except GeminiParseError as e:
        duration_sec = time.perf_counter() - start_time
        logger.warning(
            "invalid_json_response",
            extra={
                "event": "invalid_json_response",
                "run_id": run_id,
                "source_trace_id": trace_id,
                "error": str(e),
                "duration_sec": round(duration_sec, 3),
            },
        )

        if not dry_run:
            error_record = ExtractionError(
                run_id=run_id,
                source_trace_id=trace_id,
                error_type=ExtractionErrorType.INVALID_JSON,
                error_message=str(e),
                recorded_at=datetime.now(tz=timezone.utc),
            )
            repository.save_extraction_error(error_record)

        return TraceOutcome(
            source_trace_id=trace_id,
            status=TraceOutcomeStatus.ERROR,
            error_reason=str(e),
        )

    except GeminiClientError as e:
        duration_sec = time.perf_counter() - start_time
        logger.error(
            "gemini_error",
            extra={
                "event": "gemini_error",
                "run_id": run_id,
                "source_trace_id": trace_id,
                "error": str(e),
                "duration_sec": round(duration_sec, 3),
            },
        )

        if not dry_run:
            error_record = ExtractionError(
                run_id=run_id,
                source_trace_id=trace_id,
                error_type=ExtractionErrorType.VERTEX_ERROR,
                error_message=str(e),
                recorded_at=datetime.now(tz=timezone.utc),
            )
            repository.save_extraction_error(error_record)

        return TraceOutcome(
            source_trace_id=trace_id,
            status=TraceOutcomeStatus.ERROR,
            error_reason=str(e),
        )

    except Exception as e:
        duration_sec = time.perf_counter() - start_time
        logger.exception(
            "unexpected_error",
            extra={
                "event": "unexpected_error",
                "run_id": run_id,
                "source_trace_id": trace_id,
                "error": str(e),
                "duration_sec": round(duration_sec, 3),
            },
        )

        if not dry_run:
            error_record = ExtractionError(
                run_id=run_id,
                source_trace_id=trace_id,
                error_type=ExtractionErrorType.UNKNOWN,
                error_message=str(e),
                recorded_at=datetime.now(tz=timezone.utc),
            )
            repository.save_extraction_error(error_record)

        return TraceOutcome(
            source_trace_id=trace_id,
            status=TraceOutcomeStatus.ERROR,
            error_reason=str(e),
        )


def run_extraction(
    batch_size: int,
    triggered_by: TriggeredBy,
    dry_run: bool = False,
    trace_ids: Optional[List[str]] = None,
) -> ExtractionRunSummary:
    """Execute an extraction run.

    Args:
        batch_size: Maximum traces to process.
        triggered_by: How the run was initiated.
        dry_run: If True, skip writes.
        trace_ids: Optional explicit trace IDs to process.

    Returns:
        ExtractionRunSummary with results.
    """
    settings = load_extraction_settings()
    run_id = _generate_run_id()
    started_at = datetime.now(tz=timezone.utc)

    # Log run start
    logger.info(
        "extraction_run_started",
        extra={
            "event": "extraction_run_started",
            "run_id": run_id,
            "batch_size": batch_size,
            "triggered_by": triggered_by.value,
            "dry_run": dry_run,
            "model": settings.gemini.model,
            "temperature": settings.gemini.temperature,
        },
    )

    # Initialize clients
    gemini_client = create_gemini_client(settings.gemini)
    repository = create_firestore_repository(settings.firestore)

    # Fetch unprocessed traces
    traces = repository.get_unprocessed_traces(batch_size, trace_ids)
    picked_up_count = len(traces)

    logger.info(
        "traces_fetched",
        extra={
            "event": "traces_fetched",
            "run_id": run_id,
            "picked_up_count": picked_up_count,
        },
    )

    # Process each trace sequentially (per research.md: reduce rate-limit risk)
    outcomes: List[TraceOutcome] = []
    for trace_data in traces:
        outcome = _process_single_trace(
            trace_data=trace_data,
            gemini_client=gemini_client,
            repository=repository,
            run_id=run_id,
            timeout_sec=settings.per_trace_timeout_sec,
            dry_run=dry_run,
        )
        outcomes.append(outcome)

    # Calculate summary counts
    finished_at = datetime.now(tz=timezone.utc)
    stored_count = sum(1 for o in outcomes if o.status == TraceOutcomeStatus.STORED)
    validation_failed_count = sum(
        1 for o in outcomes if o.status == TraceOutcomeStatus.VALIDATION_FAILED
    )
    error_count = sum(1 for o in outcomes if o.status == TraceOutcomeStatus.ERROR)
    timed_out_count = sum(1 for o in outcomes if o.status == TraceOutcomeStatus.TIMED_OUT)

    # Build summary
    summary = ExtractionRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        triggered_by=triggered_by,
        batch_size=batch_size,
        picked_up_count=picked_up_count,
        stored_count=stored_count,
        validation_failed_count=validation_failed_count,
        error_count=error_count,
        timed_out_count=timed_out_count,
        trace_outcomes=outcomes,
    )

    # Persist run summary
    if not dry_run:
        repository.save_run_summary(summary)

    # Update health state
    LAST_RUN_STATE.update({
        "last_run_id": run_id,
        "last_run_at": finished_at.isoformat(),
        "last_stored_count": stored_count,
        "last_error_count": error_count + validation_failed_count + timed_out_count,
        "last_error": None,
    })

    # Log run completion
    duration_sec = (finished_at - started_at).total_seconds()
    logger.info(
        "extraction_run_completed",
        extra={
            "event": "extraction_run_completed",
            "run_id": run_id,
            "picked_up_count": picked_up_count,
            "stored_count": stored_count,
            "validation_failed_count": validation_failed_count,
            "error_count": error_count,
            "timed_out_count": timed_out_count,
            "duration_sec": round(duration_sec, 3),
        },
    )

    return summary


# ============================================================================
# FastAPI Endpoints
# ============================================================================


@app.get("/health")
def health():
    """Health check endpoint.

    Returns service status, last run info, and backlog size.
    """
    try:
        settings = load_extraction_settings()
        repository = create_firestore_repository(settings.firestore)

        unprocessed_count = repository.get_unprocessed_count()
        last_run = repository.get_last_run_summary()

        return {
            "status": "ok" if LAST_RUN_STATE.get("last_error") is None else "degraded",
            "lastRun": LAST_RUN_STATE,
            "backlog": {
                "unprocessedCount": unprocessed_count,
            },
            "lastPersistentRun": last_run,
            "config": {
                "model": settings.gemini.model,
                "batchSize": settings.batch_size,
                "perTraceTimeoutSec": settings.per_trace_timeout_sec,
            },
        }
    except Exception as e:
        logger.exception("health_check_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="unhealthy") from e


@app.post("/extraction/run-once", status_code=202)
def run_once(body: ExtractionRunRequest = None):
    """Trigger a single extraction run.

    Reads unprocessed failure traces from Firestore, extracts a structured
    failure pattern per trace, validates the output, persists it to the
    failure patterns collection, and marks source traces as processed.
    """
    try:
        settings = load_extraction_settings()

        # Resolve parameters
        batch_size = body.batch_size if body and body.batch_size else settings.batch_size
        triggered_by = body.triggered_by if body and body.triggered_by else TriggeredBy.MANUAL
        dry_run = body.dry_run if body and body.dry_run else False
        trace_ids = body.trace_ids if body else None

        # Run extraction
        summary = run_extraction(
            batch_size=batch_size,
            triggered_by=triggered_by,
            dry_run=dry_run,
            trace_ids=trace_ids,
        )

        # Return summary in camelCase for API consistency
        return {
            "runId": summary.run_id,
            "startedAt": summary.started_at.isoformat(),
            "finishedAt": summary.finished_at.isoformat(),
            "triggeredBy": summary.triggered_by.value,
            "batchSize": summary.batch_size,
            "pickedUpCount": summary.picked_up_count,
            "storedCount": summary.stored_count,
            "validationFailedCount": summary.validation_failed_count,
            "errorCount": summary.error_count,
            "timedOutCount": summary.timed_out_count,
            "traceOutcomes": [
                {
                    "sourceTraceId": o.source_trace_id,
                    "status": o.status.value,
                    "patternId": o.pattern_id,
                    "errorReason": o.error_reason,
                }
                for o in (summary.trace_outcomes or [])
            ],
        }

    except FirestoreRepositoryError as e:
        logger.error("firestore_error", extra={"error": str(e)})
        LAST_RUN_STATE["last_error"] = str(e)
        raise HTTPException(status_code=500, detail=f"Firestore error: {e}") from e
    except GeminiClientError as e:
        logger.error("gemini_client_error", extra={"error": str(e)})
        LAST_RUN_STATE["last_error"] = str(e)
        raise HTTPException(status_code=500, detail=f"Gemini error: {e}") from e
    except Exception as e:
        logger.exception("run_once_failed", extra={"error": str(e)})
        LAST_RUN_STATE["last_error"] = str(e)
        raise HTTPException(status_code=500, detail=str(e)) from e
