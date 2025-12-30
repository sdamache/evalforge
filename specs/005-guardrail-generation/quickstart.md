# Quickstart: Guardrail Suggestion Engine

**Feature**: 005-guardrail-generation
**Date**: 2025-12-30

## Prerequisites

1. Python 3.11+
2. GCP credentials with Firestore + Vertex AI access
3. Evalforge project set up (see main README)
4. Existing guardrail-type suggestions in Firestore

## Setup

```bash
# Activate virtual environment
source evalforge_venv/bin/activate

# Install dependencies (if not already)
pip install -e ".[dev]"

# Set environment variables
export GOOGLE_CLOUD_PROJECT=konveyn2ai
export FIRESTORE_COLLECTION_PREFIX=evalforge_
export VERTEX_AI_LOCATION=us-central1
export GEMINI_MODEL=gemini-2.5-flash

# Or use .env file
cp .env.example .env
# Edit .env with your credentials
```

## Running the Service

### Local Development

```bash
# Start the guardrail generator service
python -m src.generators.guardrails.main

# Service runs on http://localhost:8080
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check with backlog count |
| `/guardrails/run-once` | POST | Batch generation |
| `/guardrails/generate/{id}` | POST | Single suggestion generation |
| `/guardrails/{id}` | GET | Retrieve guardrail draft |

## Usage Examples

### Health Check

```bash
curl http://localhost:8080/health
```

Response:
```json
{
  "status": "ok",
  "version": "1.0.0",
  "backlog": {
    "pendingGuardrailSuggestions": 15
  }
}
```

### Batch Generation

```bash
# Generate guardrails for up to 20 pending suggestions
curl -X POST http://localhost:8080/guardrails/run-once \
  -H "Content-Type: application/json" \
  -d '{"batchSize": 20, "triggeredBy": "manual"}'
```

Response:
```json
{
  "runId": "run_20251230_120000_abc123",
  "startedAt": "2025-12-30T12:00:00Z",
  "finishedAt": "2025-12-30T12:00:45Z",
  "triggeredBy": "manual",
  "batchSize": 20,
  "pickedUpCount": 15,
  "generatedCount": 14,
  "skippedCount": 0,
  "errorCount": 1,
  "processingDurationMs": 45000
}
```

### Single Suggestion Generation

```bash
# Generate guardrail for specific suggestion
curl -X POST http://localhost:8080/guardrails/generate/sugg_abc123

# Force regeneration (overwrite human edits)
curl -X POST http://localhost:8080/guardrails/generate/sugg_abc123 \
  -H "Content-Type: application/json" \
  -d '{"forceOverwrite": true}'
```

### Retrieve Guardrail Draft

```bash
# JSON format (default)
curl http://localhost:8080/guardrails/sugg_abc123

# YAML format for Datadog AI Guard
curl "http://localhost:8080/guardrails/sugg_abc123?format=yaml"
```

Response (JSON):
```json
{
  "suggestion_id": "sugg_abc123",
  "suggestion_status": "pending",
  "guardrail": {
    "guardrail_id": "guard_sugg_abc123",
    "rule_name": "block_runaway_api_calls",
    "guardrail_type": "rate_limit",
    "failure_type": "runaway_loop",
    "configuration": {
      "max_calls": 10,
      "window_seconds": 60,
      "scope": "session",
      "action": "block_and_alert"
    },
    "description": "Prevents excessive API calls per session",
    "justification": "Production incident showed agent making 500+ calls in 30 seconds...",
    "estimated_prevention_rate": 0.95,
    "source": {
      "suggestion_id": "sugg_abc123",
      "canonical_trace_id": "trace_xyz789",
      "canonical_pattern_id": "pattern_xyz789",
      "trace_ids": ["trace_xyz789", "trace_def456"],
      "pattern_ids": ["pattern_xyz789", "pattern_def456"]
    },
    "status": "draft",
    "edit_source": "generated",
    "generated_at": "2025-12-30T12:00:00Z",
    "updated_at": "2025-12-30T12:00:00Z"
  }
}
```

## Testing

```bash
# Run live integration tests (requires credentials)
RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_guardrail_generator_live.py -v
```

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `GUARDRAIL_BATCH_SIZE` | 20 | Max suggestions per batch |
| `GUARDRAIL_PER_SUGGESTION_TIMEOUT_SEC` | 30 | Timeout per suggestion |
| `GUARDRAIL_COST_BUDGET_USD_PER_SUGGESTION` | 0.10 | Budget per suggestion |
| `GEMINI_MODEL` | gemini-2.5-flash | LLM model |
| `GEMINI_TEMPERATURE` | 0.2 | Generation temperature |

## Failure Type Mapping

| Failure Type | Generated Guardrail Type |
|--------------|-------------------------|
| hallucination | validation_rule |
| toxicity | content_filter |
| runaway_loop | rate_limit |
| pii_leak | redaction_rule |
| wrong_tool | scope_limit |
| stale_data | freshness_check |
| prompt_injection | input_sanitization |

## Common Issues

### "Overwrite blocked"
A human has edited this guardrail draft. Use `forceOverwrite: true` to regenerate.

### "needs_human_input" status
The generator couldn't create a complete guardrail due to insufficient context. Review and fill in placeholders manually.

### Timeout errors
Increase `GUARDRAIL_PER_SUGGESTION_TIMEOUT_SEC` or check Gemini API status.
