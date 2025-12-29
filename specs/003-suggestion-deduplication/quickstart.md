# Quickstart: Suggestion Deduplication Service

**Branch**: `003-suggestion-deduplication` | **Date**: 2025-12-28

## Prerequisites

- Python 3.11+
- Google Cloud SDK (`gcloud`)
- Firestore emulator or GCP project with Firestore enabled
- Vertex AI API enabled in GCP project
- Service account with Vertex AI and Firestore permissions

## Environment Setup

### 1. Clone and Install

```bash
# Clone and checkout branch
git checkout 003-suggestion-deduplication

# Create virtual environment
python -m venv evalforge_venv
source evalforge_venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"
```

### 2. Configure Environment

```bash
# Copy example env file
cp .env.example .env

# Edit .env with your credentials
# Required variables for deduplication:
cat >> .env << 'EOF'

# Deduplication Service Config
SIMILARITY_THRESHOLD=0.85
EMBEDDING_MODEL=text-embedding-004
DEDUP_BATCH_SIZE=20

# Vertex AI (for embeddings)
VERTEX_AI_PROJECT=konveyn2ai
VERTEX_AI_LOCATION=us-central1
EOF
```

### 3. Authenticate with GCP

```bash
# For local development
gcloud auth application-default login

# Set project
gcloud config set project konveyn2ai
```

## Running the Service

### Option 1: Direct Python

```bash
# Start the deduplication service
PYTHONPATH=src python -m src.deduplication.main

# Service runs on http://localhost:8003
```

### Option 2: With Docker Compose

```bash
# Start all services including Firestore emulator
docker-compose up deduplication
```

## Testing

### Run Live Integration Tests

```bash
# Requires real Vertex AI and Firestore access
RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_deduplication_live.py -v
```

### Run Contract Tests

```bash
# Schema validation only (no external services needed)
PYTHONPATH=src python -m pytest tests/contract/test_deduplication_contracts.py -v
```

## API Usage

### Health Check

```bash
curl http://localhost:8003/health
```

Response:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "embedding_service": "available"
}
```

### Run Deduplication Batch

```bash
# Process up to 20 unprocessed patterns
curl -X POST http://localhost:8003/dedup/run-once \
  -H "Content-Type: application/json" \
  -d '{"batchSize": 20, "triggeredBy": "manual"}'
```

Response:
```json
{
  "runId": "run_abc123",
  "startedAt": "2025-01-05T12:00:00Z",
  "finishedAt": "2025-01-05T12:00:05Z",
  "patternsProcessed": 15,
  "suggestionsCreated": 3,
  "suggestionsMerged": 12,
  "averageSimilarityScore": 0.91,
  "processingDurationMs": 5000
}
```

### List Suggestions (with filters)

```bash
# List pending suggestions
curl "http://localhost:8003/suggestions?status=pending&limit=10"

# Filter by type and severity
curl "http://localhost:8003/suggestions?type=eval&severity=high&limit=20"

# Paginate through results using cursor
curl "http://localhost:8003/suggestions?status=pending&cursor=<cursor_from_previous_response>"
```

Response:
```json
{
  "suggestions": [...],
  "total": 42,
  "nextCursor": "eyJzdWdnZXN0aW9uX2lkIjogInN1Z2dfYWJjMTIzIn0="
}
```

### Get Suggestion Details (with Lineage)

```bash
curl http://localhost:8003/suggestions/sugg_abc123
```

Response includes full lineage:
```json
{
  "suggestionId": "sugg_abc123",
  "type": "eval",
  "status": "pending",
  "severity": "high",
  "sourceTraces": [
    {"traceId": "trace_001", "patternId": "pat_001", "addedAt": "2025-01-05T10:00:00Z"},
    {"traceId": "trace_002", "patternId": "pat_002", "addedAt": "2025-01-05T10:05:00Z", "similarityScore": 0.91}
  ],
  "versionHistory": [
    {"newStatus": "pending", "actor": "system", "timestamp": "2025-01-05T10:00:00Z"}
  ]
}
```

### Approve or Reject a Suggestion

```bash
# Approve a suggestion
curl -X PATCH http://localhost:8003/suggestions/sugg_abc123/status \
  -H "Content-Type: application/json" \
  -d '{"status": "approved", "actor": "reviewer@example.com", "notes": "Valid eval test case"}'

# Reject a suggestion
curl -X PATCH http://localhost:8003/suggestions/sugg_abc123/status \
  -H "Content-Type: application/json" \
  -d '{"status": "rejected", "actor": "reviewer@example.com", "notes": "Duplicate of existing guardrail"}'
```

Response:
```json
{
  "suggestionId": "sugg_abc123",
  "previousStatus": "pending",
  "newStatus": "approved",
  "actor": "reviewer@example.com",
  "timestamp": "2025-01-05T14:30:00Z",
  "notes": "Valid eval test case"
}
```

## Development Workflow

### 1. Seed Test Data

If you need failure patterns to test with:

```bash
# Generate sample traces (from existing script)
python scripts/generate_llm_trace_samples.py --count 10

# Run extraction to create failure patterns
curl -X POST http://localhost:8002/extraction/run-once \
  -H "Content-Type: application/json" \
  -d '{"batchSize": 10}'
```

### 2. Run Deduplication

```bash
# Process the patterns
curl -X POST http://localhost:8003/dedup/run-once
```

### 3. Verify Results

```bash
# Check suggestions were created
curl "http://localhost:8003/suggestions?status=pending"

# Verify deduplication worked (should see fewer suggestions than patterns)
```

## Troubleshooting

### Embedding Service Errors

If you see `429 Rate Limit` errors:
- The service automatically retries with exponential backoff
- Check Vertex AI quota in GCP Console
- Reduce `DEDUP_BATCH_SIZE` if needed

### Firestore Permission Errors

```bash
# Ensure service account has required roles
gcloud projects add-iam-policy-binding konveyn2ai \
  --member="serviceAccount:YOUR_SA@konveyn2ai.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
```

### No Patterns to Process

If deduplication returns 0 patterns processed:
- Check `evalforge_failure_patterns` collection has documents
- Verify patterns have `processed=false` flag
- Run extraction service first if needed

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                  Deduplication Service                   │
│                   (localhost:8003)                       │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  1. Poll Firestore for patterns (processed=false)       │
│                         ↓                                │
│  2. Generate embeddings via Vertex AI                   │
│                         ↓                                │
│  3. Compare with existing suggestions (cosine >0.85)    │
│                         ↓                                │
│  4a. MERGE: Add trace to existing suggestion            │
│  4b. CREATE: New suggestion with pending status         │
│                         ↓                                │
│  5. Mark pattern as processed=true                      │
│                         ↓                                │
│  6. Log metrics and return summary                      │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## Complete Test Commands

Run all tests for the deduplication service:

```bash
# 1. Contract tests (no external services needed)
PYTHONPATH=src python -m pytest tests/contract/test_deduplication_contracts.py -v

# 2. Integration tests (requires GCP credentials)
RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_deduplication_live.py -v

# 3. All deduplication tests
RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/contract/test_deduplication_contracts.py tests/integration/test_deduplication_live.py -v
```

### Verification Checklist

After running tests, verify:

- [ ] **Contract Tests Pass**: All 10 schema validation tests pass
- [ ] **Deduplication Works**: Similar patterns merge into same suggestion
- [ ] **Lineage Visible**: source_traces shows all contributing traces
- [ ] **Audit Trail**: version_history records all status changes
- [ ] **Filters Work**: Query by status, type, severity returns correct results
- [ ] **Pagination Works**: Large result sets paginate correctly

## Cloud Run Deployment

### Prerequisites

Before deploying, ensure:
1. GCP project has billing enabled
2. You're authenticated: `gcloud auth login`
3. Bootstrap script has run: `GCP_PROJECT_ID=konveyn2ai ./scripts/bootstrap_gcp.sh`
4. Firestore indexes are deployed: `npx firebase-tools deploy --only firestore:indexes`

### Deploy to Cloud Run Staging

```bash
# Set your project ID
export GCP_PROJECT_ID="konveyn2ai"

# Deploy with default settings (includes Cloud Scheduler)
./scripts/deploy_deduplication.sh

# Deploy without Cloud Scheduler (manual triggers only)
SKIP_SCHEDULER=1 ./scripts/deploy_deduplication.sh

# Deploy with custom settings
GCP_PROJECT_ID=konveyn2ai \
  SIMILARITY_THRESHOLD=0.90 \
  DEDUP_BATCH_SIZE=50 \
  DEDUP_SCHEDULE="*/30 * * * *" \
  ./scripts/deploy_deduplication.sh
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GCP_PROJECT_ID` | (required) | Target GCP project |
| `GCP_REGION` | `us-central1` | Deployment region |
| `SERVICE_NAME` | `evalforge-deduplication` | Cloud Run service name |
| `SIMILARITY_THRESHOLD` | `0.85` | Cosine similarity threshold |
| `DEDUP_BATCH_SIZE` | `20` | Patterns per deduplication run |
| `DEDUP_SCHEDULE` | `*/5 * * * *` | Cron schedule (every 5 min) |
| `SKIP_SCHEDULER` | `0` | Set to `1` to skip scheduler setup |

### Verify Deployment

```bash
# Health check (requires auth token)
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://evalforge-deduplication-HASH-uc.a.run.app/health

# Manual trigger
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"batchSize": 10, "triggeredBy": "manual"}' \
  https://evalforge-deduplication-HASH-uc.a.run.app/dedup/run-once

# View logs
gcloud run services logs read evalforge-deduplication \
  --region=us-central1 \
  --project=konveyn2ai \
  --limit=50
```

### What the Deployment Script Does

1. **Creates Service Account**: `evalforge-deduplication-sa` with minimal permissions
2. **Grants IAM Roles**:
   - `roles/datastore.user` - Firestore read/write
   - `roles/aiplatform.user` - Vertex AI embeddings
3. **Builds Docker Image**: Via Cloud Build using `Dockerfile.deduplication`
4. **Deploys to Cloud Run**: With environment variables and resource limits
5. **Creates Cloud Scheduler Job**: Triggers `/dedup/run-once` on schedule

## Next Steps

The deduplication service is **fully implemented**:

1. **Deploy Firestore indexes**: `npx firebase-tools deploy --only firestore:indexes`
2. **Deploy to Cloud Run**: `./scripts/deploy_deduplication.sh`
3. **Issue #4**: Implement eval test generation from approved suggestions
4. **Issue #5**: Implement guardrail rule generation from approved suggestions
5. **Issue #6**: Implement runbook snippet generation from approved suggestions
