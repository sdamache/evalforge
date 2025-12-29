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

### List Pending Suggestions

```bash
curl "http://localhost:8003/suggestions?status=pending&limit=10"
```

### Get Suggestion Details

```bash
curl http://localhost:8003/suggestions/sugg_abc123
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

## Next Steps

After deduplication is working:
1. Run `/speckit.tasks` to generate implementation tasks
2. Implement the service following tasks.md
3. Test with live integration tests
4. Deploy to Cloud Run
