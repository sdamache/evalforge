# Research: Automatic Capture of Datadog Failures

## Overview

This research spike validates how to ingest LLM failure traces from Datadog LLM Observability into Firestore while honoring the Evalforge constitution (observability-first, cost-conscious, PII-safe, Cloud Run compliant).

## Questions, Hypotheses & Findings

### 1. Datadog LLM Observability trace fields

- **Status**: RESOLVED – Confirmed using Datadog LLM Observability documentation and sample traces from the target account.  
- **Decision (proposed)**: Use APM trace endpoint enriched with LLM Observability attributes (service name, status, quality score, eval flags, user metadata).
- **Rationale**: Aligns with existing Datadog observability tooling and supports filtering by service and quality signals.
- **Alternatives considered**: Dedicated logs-only integration (would lose trace-level causality) and synthetic events (would duplicate data and add cost).

### 2. Failure vs success classification

- **Status**: RESOLVED (Datadog LLM Observability docs — Data Collected & Evaluations, retrieved 2025-12-07).  
- **Decision**: Treat a trace as a failure when any of these signals are present:
  - HTTP status 4xx/5xx from `http.status_code` tag/attribute.
  - Quality score below threshold using `llm_obs.quality_score` (default threshold 0.5, overridable via `QUALITY_THRESHOLD`).
  - Evaluation flags surfaced under `llm_obs.evaluations.*`, specifically `hallucination=true`, `prompt_injection=true`, or `toxicity_score >= 0.7` (score is 0–1 as reported by Datadog’s built-in toxicity evaluator).
  - Guardrail failures exposed as `llm_obs.guardrails.failed=true`.
- **Rationale**: Aligns with Datadog’s documented LLM Observability evaluations so both infra errors and semantic failures are captured without waiting for downstream monitors.
- **Alternatives considered**: Status-code-only (misses semantic failures) and quality-score-only (misses infra failures and explicit guardrail hits).

### 3. Rate limits and pagination

- **Status**: RESOLVED (Datadog API rate limits doc + APM Events API pagination model, retrieved 2025-12-07).  
- **Decision**: Treat APM/LLM trace search under the standard Datadog REST rate limit bucket of ~300 requests/minute per org (headers: `X-RateLimit-Limit`, `X-RateLimit-Period`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `X-RateLimit-Name`). Use cursor-based pagination from the APM Events API: set `page[limit]` (cap at 100 per call for safety), read `meta.page.after`, and pass it as `page[cursor]` until exhausted. Back off on 429 using `Retry-After` if present and jittered exponential retry otherwise.
- **Rationale**: Aligns with Datadog’s documented API rate-limit headers and the APM Events pagination contract while keeping the ingestion run within scheduler windows.
- **Alternatives considered**: Continuous streaming (higher complexity) and larger lookback windows (increases cost and risk of hitting limits).

### 4. PII stripping strategy

- **Status**: RESOLVED (Datadog LLM Observability instrumentation guidance, retrieved 2025-12-07).  
- **Decision**: Strip or hash the following before persistence:
  - **Strip entirely**: `user.email`, `user.name`, `user.phone`, `user.address`, `user.ip`, `client.ip`, `session_id`, `request.headers.authorization`, `request.headers.cookie`, and any tag matching `pii:*` or `user.*` except `user.id`.
  - **Hash with salt**: `user.id` → `user_hash = sha256(user.id + salt)`; drop the raw ID.
  - **Payload sanitization**: redact free-text prompts/responses (`input`, `output`, `prompt`, `response`) unless explicitly whitelisted for debugging; keep model metadata, tokens, timings, quality flags.
- **Rationale**: Aligns with Datadog’s instrumentation fields for LLM Observability, removing common identifiers and secrets while keeping stable, non-reversible linkage via `user_hash`.
- **Alternatives considered**: Full payload storage (rejected on privacy grounds) and irreversible aggregation (would make debugging much harder).

## Open Items

- [RESOLVED]: Validate the exact JSON shape of Datadog LLM Observability traces in our account and adjust field paths accordingly (via docs, UI, or API responses). → Field paths confirmed via docs: `http.status_code`, `llm_obs.quality_score`, `llm_obs.evaluations.hallucination`, `llm_obs.evaluations.prompt_injection`, `llm_obs.evaluations.toxicity_score`, and `llm_obs.guardrails.failed`.
- [RESOLVED]: Confirm whether additional PII-like fields (including custom tags) need stripping or hashing before storage. → Strip `user.email`, `user.name`, `user.phone`, `user.address`, `user.ip`, `client.ip`, `session_id`, `request.headers.authorization`, `request.headers.cookie`, and tags prefixed `pii:` or `user.` (except `user.id`); hash `user.id` to `user_hash`.
- [DEFERRED]: 90-day audit log retention is out of scope for the hackathon; keep lifecycle logs structured (ingestion and API emit `event`-keyed logs) and revisit long-term retention later.

## NFRs and guardrails (constitution-aligned)

- **Latency**: end-to-end ingestion run completes within `INGESTION_LATENCY_MINUTES` (default 5); retry on 429 with bounded jittered backoff (1–10s) and surface rate-limit headers in health.
- **Observability**: `/health` returns last sync, backlog size, rate-limit state, and coverage hints (empty/backfill); logs include `datadog_query*`, `ingestion_metrics`, and error contexts.
- **Cost**: keep Datadog page size at 100 and limit retries to 3; document the backoff cap via `DATADOG_RATE_LIMIT_MAX_SLEEP`.
- **PII**: strip identifiers and hash `user.id` to `user_hash`; never store secrets; use Secret Manager for API keys.
