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

- **Status**: HYPOTHESIS – [NEEDS CLARIFICATION: Validate available quality scores and eval flags in our Datadog account].  
- **Decision (proposed)**: Treat a trace as a failure if any of the following are true: HTTP status is 4xx/5xx, quality score is below `QUALITY_THRESHOLD` (default 0.5), or any eval flag indicates a problem (hallucination=true, toxicity>0.7, prompt_injection=true).
- **Rationale**: Combines infrastructure and content quality signals so the backlog reflects meaningful incidents, not just hard errors.
- **Alternatives considered**: Status-code-only (misses hallucinations) and quality-score-only (misses infrastructure failures).

### 3. Rate limits and pagination

- **Status**: HYPOTHESIS – [NEEDS CLARIFICATION: Confirm rate limits and cursor semantics for our Datadog tier].  
- **Decision (proposed)**: Respect Datadog’s documented limit of 300 requests/minute, using cursor-based pagination and a capped lookback window (`TRACE_LOOKBACK_HOURS`, default 24).
- **Rationale**: Prevents throttling while ensuring we cover the most recent 24 hours each run; Cloud Scheduler triggers every 15 minutes to keep lag low.
- **Alternatives considered**: Continuous streaming (higher complexity) and larger lookback windows (increases cost and risk of hitting limits).

### 4. PII stripping strategy

- **Status**: HYPOTHESIS – [NEEDS CLARIFICATION: Enumerate all PII-like fields present in our traces].  
- **Decision (proposed)**: Before persisting `trace_payload`, remove common user-identifying fields (`user.email`, `user.name`, `user.phone`, `user.address`) and replace `user.id` with `user_hash = sha256(user.id + salt)`; never store raw IDs.
- **Rationale**: Complies with the constitution’s “MUST NOT store raw PII” while preserving a stable key for grouping incidents by user when needed.
- **Alternatives considered**: Full payload storage (rejected on privacy grounds) and irreversible aggregation (would make debugging much harder).

## Open Items

- [NEEDS CLARIFICATION]: Validate the exact JSON shape of Datadog LLM Observability traces in our account and adjust field paths accordingly (via docs, UI, or API responses).
- [NEEDS CLARIFICATION]: Confirm whether additional PII-like fields (including custom tags) need stripping or hashing before storage.
