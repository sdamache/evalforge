# Quickstart: Runbook Draft Generator

**Feature**: 006-runbook-generation
**Date**: 2025-12-30

## Prerequisites

1. **Python 3.11+** installed
2. **Google Cloud credentials** configured (`gcloud auth application-default login`)
3. **Firestore** with existing `evalforge_suggestions` collection (from Issue #3)
4. **Vertex AI** enabled in GCP project (`konveyn2ai`)

## Environment Setup

```bash
# Navigate to the project
cd /Users/nikhild/Documents/job_related/projects/Exploratory/evalforge/.worktrees/006-runbook-generation

# Activate virtual environment
source evalforge_venv/bin/activate

# Install dependencies (if not already)
pip install -e ".[dev]"

# Copy and configure environment
cp .env.example .env
# Edit .env with your credentials
```

### Required Environment Variables

```bash
# GCP / Vertex AI
GOOGLE_CLOUD_PROJECT=konveyn2ai
VERTEX_AI_LOCATION=us-central1

# Gemini Configuration
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TEMPERATURE=0.3
GEMINI_MAX_OUTPUT_TOKENS=4096

# Firestore
FIRESTORE_COLLECTION_PREFIX=evalforge_
FIRESTORE_DATABASE_ID=(default)

# Generator Settings
RUNBOOK_BATCH_SIZE=20
RUNBOOK_PER_SUGGESTION_TIMEOUT_SEC=30
RUNBOOK_COST_BUDGET_USD_PER_SUGGESTION=0.10
```

## Running the Service

### Local Development

```bash
# Start the runbook generator service
python -m src.generators.runbooks.main

# Service runs on http://localhost:8082 by default
```

### Health Check

```bash
curl http://localhost:8082/health | jq
```

Expected response:
```json
{
  "status": "ok",
  "version": "1.0.0",
  "backlog": {
    "pendingRunbookSuggestions": 5
  },
  "config": {
    "model": "gemini-2.5-flash",
    "batchSize": 20,
    "perSuggestionTimeoutSec": 30
  }
}
```

## API Usage

### Trigger Batch Generation

```bash
# Generate runbooks for up to 5 pending suggestions
curl -X POST http://localhost:8082/runbooks/run-once \
  -H "Content-Type: application/json" \
  -d '{"batchSize": 5, "triggeredBy": "manual"}'
```

### Generate Single Runbook

```bash
# Generate runbook for a specific suggestion
curl -X POST http://localhost:8082/runbooks/generate/sugg_abc123 \
  -H "Content-Type: application/json" \
  -d '{"triggeredBy": "manual"}'
```

### Retrieve Runbook

```bash
# Get the generated runbook for a suggestion
curl http://localhost:8082/runbooks/sugg_abc123 | jq
```

### Force Overwrite Human-Edited Runbook

```bash
# Regenerate even if human-edited
curl -X POST http://localhost:8082/runbooks/generate/sugg_abc123 \
  -H "Content-Type: application/json" \
  -d '{"forceOverwrite": true, "triggeredBy": "manual"}'
```

### Dry Run (No Persistence)

```bash
# Generate but don't save (for testing)
curl -X POST http://localhost:8082/runbooks/run-once \
  -H "Content-Type: application/json" \
  -d '{"batchSize": 2, "dryRun": true}'
```

## Testing

### Run Live Integration Tests

```bash
# Requires real Gemini and Firestore access
RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_runbook_generator_live.py -v
```

### Sample Test Suggestion

Before testing, ensure you have a runbook-type suggestion in Firestore:

```python
# Create test suggestion via Python
from google.cloud import firestore
from datetime import datetime, timezone

db = firestore.Client()
db.collection("evalforge_suggestions").document("sugg_test_runbook").set({
    "suggestion_id": "sugg_test_runbook",
    "type": "runbook",
    "status": "pending",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "source_traces": ["dd_trace_test"],
    "pattern": {
        "failure_type": "stale_data",
        "trigger_condition": "Product recommendation without inventory check",
        "severity": "medium",
        "title": "Stale Product Recommendations",
        "reproduction_context": {
            "input_pattern": "User asks for product recommendations",
            "required_state": "Catalog contains discontinued items",
            "tools_involved": ["product_search", "inventory_api"]
        }
    },
    "suggestion_content": {}
})
```

## Generated Runbook Example

After successful generation, the runbook will be embedded at `suggestion_content.runbook_snippet`:

```markdown
# Stale Data - Operational Runbook

**Source Incident**: `dd_trace_test`
**Severity**: medium
**Generated**: 2025-12-30T12:00:00Z

---

## Summary
LLM agent recommends products that are discontinued or out of stock due to stale inventory data.

## Symptoms
- Product unavailable errors in customer feedback
- Inventory mismatch alerts in monitoring dashboard
- Quality score drops below 0.5 for recommendation queries

## Diagnosis Steps
1. **Check recent traces**: `datadog trace search "service:llm-agent @failure_type:stale_data"`
2. **Verify inventory sync**: `curl -s inventory-api/sync-status | jq '.last_sync_at'`
3. **Review cache age**: Check Redis TTL for product catalog keys

## Immediate Mitigation
1. Force inventory cache refresh: `curl -X POST inventory-api/refresh`
2. Apply temporary guardrail to block stale recommendations

## Root Cause Fix
1. Reduce cache TTL from 1 hour to 15 minutes
2. Implement real-time inventory sync via webhook
3. Add inventory freshness check before recommendations

## Escalation
- **When to escalate**: If sync delay exceeds 1 hour or customer complaints > 10
- **Who to contact**: #team-inventory in Slack, @oncall-platform in PagerDuty
- **Escalation threshold**: Customer impact > 100 users

---

*Auto-generated by EvalForge from production failure patterns.*
```

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `GeminiRateLimitError` | Too many API calls | Reduce batch size, wait for quota reset |
| `FirestoreError: Suggestion not found` | Invalid suggestion ID | Verify suggestion exists in Firestore |
| `409 Conflict` | Human-edited runbook exists | Use `forceOverwrite: true` if intentional |
| `Template fallback triggered` | Missing reproduction context | Check source failure pattern has complete context |

### Logs

```bash
# View structured logs
python -m src.generators.runbooks.main 2>&1 | jq
```

### Debug Mode

```bash
# Enable debug logging
LOG_LEVEL=DEBUG python -m src.generators.runbooks.main
```
