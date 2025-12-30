# Quickstart: Approval Workflow API

**Branch**: `008-approval-workflow-api` | **Date**: 2025-12-29

## Prerequisites

1. Python 3.11+ installed
2. EvalForge virtual environment activated
3. Firestore access configured (emulator or production)
4. Environment variables set (see below)

## Environment Variables

Add to your `.env` file:

```bash
# Required for approval API
APPROVAL_API_KEY=your-secret-api-key-here

# Optional: Slack webhook for notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# Existing Firestore config (should already be set)
GOOGLE_CLOUD_PROJECT=konveyn2ai
FIRESTORE_DATABASE_ID=evalforge
FIRESTORE_COLLECTION_PREFIX=evalforge_
```

## Running the Service

### Local Development

```bash
# Activate virtual environment
source evalforge_venv/bin/activate

# Run the API (includes approval workflow endpoints)
python -m src.api.main

# Service runs on http://localhost:8000
```

### With Docker Compose

```bash
docker-compose up api
```

## API Usage Examples

### Health Check

```bash
curl http://localhost:8000/health
```

### List Pending Suggestions

```bash
curl -H "X-API-Key: your-secret-api-key-here" \
  "http://localhost:8000/suggestions?status=pending&limit=10"
```

### Get Suggestion Details

```bash
curl -H "X-API-Key: your-secret-api-key-here" \
  "http://localhost:8000/suggestions/sugg_xyz789"
```

### Approve a Suggestion

```bash
curl -X POST \
  -H "X-API-Key: your-secret-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{"notes": "Validated with team"}' \
  "http://localhost:8000/suggestions/sugg_xyz789/approve"
```

### Reject a Suggestion

```bash
curl -X POST \
  -H "X-API-Key: your-secret-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{"reason": "False positive - not actually a failure"}' \
  "http://localhost:8000/suggestions/sugg_xyz789/reject"
```

### Export Approved Suggestion

```bash
# DeepEval JSON format (default)
curl -H "X-API-Key: your-secret-api-key-here" \
  "http://localhost:8000/suggestions/sugg_xyz789/export?format=deepeval"

# Pytest Python format
curl -H "X-API-Key: your-secret-api-key-here" \
  "http://localhost:8000/suggestions/sugg_xyz789/export?format=pytest"

# YAML format
curl -H "X-API-Key: your-secret-api-key-here" \
  "http://localhost:8000/suggestions/sugg_xyz789/export?format=yaml"
```

### Test Webhook

```bash
curl -X POST \
  -H "X-API-Key: your-secret-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{"message": "Test notification"}' \
  "http://localhost:8000/webhooks/test"
```

## Running Tests

```bash
# Live integration tests (requires Firestore access)
RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_approval_workflow_live.py -v
```

## Common Issues

### 401 Unauthorized

**Symptom**: API returns `{"detail": "Invalid API key"}`

**Solution**: Ensure `X-API-Key` header matches `APPROVAL_API_KEY` environment variable.

### 404 Not Found

**Symptom**: API returns `{"detail": "Suggestion not found"}`

**Solution**: Verify suggestion ID exists. Check `FIRESTORE_COLLECTION_PREFIX` matches your data.

### 409 Conflict

**Symptom**: Approval/rejection fails with conflict error

**Solution**: Suggestion is not in "pending" state. Check current status with GET endpoint.

### Webhook Not Received

**Symptom**: Approval succeeds but no Slack notification

**Solution**:
1. Check `SLACK_WEBHOOK_URL` is set correctly
2. Check logs for webhook delivery errors
3. Test webhook with `/webhooks/test` endpoint
4. Verify Slack webhook is active and channel exists

### Export Returns 422

**Symptom**: Export fails with "content missing" error

**Solution**: Suggestion content may be incomplete. Verify `suggestion_content` has the appropriate fields for the suggestion type (eval_test, guardrail_rule, or runbook_snippet).

## Architecture Notes

- **Atomic Updates**: Approval/rejection uses Firestore transactions to prevent race conditions
- **Audit Trail**: All status changes are recorded in `version_history` array
- **Fire-and-Forget Webhooks**: Webhook failures don't block approval; failures are logged
- **Export Validation**: All exported files are validated before returning (JSON parsed, Python parsed, YAML loaded)
