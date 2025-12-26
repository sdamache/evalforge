# Quickstart: Failure Pattern Extraction

This guide explains how to run the batch extraction service that converts captured failure traces into structured failure patterns.

## Prerequisites

- Python 3.11
- Google Cloud project with:
  - Cloud Run
  - Firestore
  - Secret Manager
  - Cloud Scheduler
  - Vertex AI API enabled (for Gemini access)
- Ingestion service is already capturing failures into Firestore collection `evalforge_raw_traces`.

> **SDK Note**: This service uses the **`google-genai` SDK** for Gemini access. The legacy `vertexai.generative_models` module is deprecated (June 2025) and will be removed June 2026.

## Environment Configuration

Set environment variables for the extraction service:

```bash
# Firestore
FIRESTORE_COLLECTION_PREFIX=evalforge_
FIRESTORE_DATABASE_ID=(default)

# Gemini (via google-genai SDK)
GOOGLE_CLOUD_PROJECT=your-gcp-project      # Used by google-genai for auth
VERTEX_AI_LOCATION=us-central1
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TEMPERATURE=0.2
GEMINI_MAX_OUTPUT_TOKENS=4096              # Default cap; tune down if latency/cost requires

# Batch processing
BATCH_SIZE=50
```

## Local Development Flow

1. Create/activate the shared venv and install deps:

```bash
python -m venv evalforge_venv
source evalforge_venv/bin/activate
pip install -e ".[dev]"
```

2. Run the extraction service locally (FastAPI):

```bash
evalforge_venv/bin/uvicorn src.extraction.main:app --reload --port 8002
```

3. Trigger an extraction run:

```bash
curl -X POST "http://localhost:8002/extraction/run-once" \
  -H "Content-Type: application/json" \
  -d '{"batchSize":50,"triggeredBy":"manual"}'
```

4. Verify outputs:

- Firestore input collection: `evalforge_raw_traces` (documents transition from `processed=false` to `processed=true` after successful extraction)
- Firestore output collection: `evalforge_failure_patterns` (one document per `source_trace_id`)

## Deployment Outline

1. Build and deploy the extraction service to Cloud Run.
2. Configure Cloud Scheduler to call the Cloud Run URL every 30 minutes:

```text
Cron: */30 * * * *
```

3. Confirm the service account has:

- Permission to read/update Firestore `evalforge_raw_traces`
- Permission to write Firestore `evalforge_failure_patterns`
- Permission to call Vertex AI Gemini in `VERTEX_AI_LOCATION`

## Validation & Quality Checks

### Local Run Validation (T040)

After triggering an extraction run locally, validate that the system is working correctly:

1. **Start the extraction service**:
```bash
source evalforge_venv/bin/activate
python -m src.extraction.main
# Service starts on http://localhost:8002
```

2. **Trigger a manual extraction run**:
```bash
curl -X POST "http://localhost:8002/extraction/run-once" \
  -H "Content-Type: application/json" \
  -d '{"batchSize":50,"triggeredBy":"manual"}'

# Or use the helper script
./scripts/run_extraction_once.sh
```

3. **Expected response**:
```json
{
  "status": "success",
  "run_id": "run_abc123",
  "processed": 5,
  "failed": 0,
  "skipped": 0
}
```

4. **Verify Firestore writes**:
   - Check `evalforge_raw_traces` collection: documents should transition from `processed=false` to `processed=true`
   - Check `evalforge_failure_patterns` collection: one new document per successfully processed trace
   - Verify document structure matches `FailurePattern` model (pattern_id, source_trace_id, title, failure_type, etc.)

5. **Check service logs** for errors or warnings:
```bash
# Look for log lines with run_id, processing outcomes, and timing
grep "run_id" <service-logs>
```

### Confidence Calibration (T045)

Spot-check extraction quality to ensure confidence scores are well-calibrated:

1. **Sample 20 extracted patterns** from `evalforge_failure_patterns`:
```bash
# Query Firestore for recent extractions
gcloud firestore documents list evalforge_failure_patterns \
  --project=$GOOGLE_CLOUD_PROJECT \
  --limit=20 \
  --format=json
```

2. **For each pattern, verify**:
   - Does the `failure_type` match the actual failure in the source trace?
   - Is the `confidence` score (0.0-1.0) appropriate for the quality of analysis?
   - Are `recommended_actions` actionable and relevant?
   - Does `root_cause_hypothesis` align with the evidence?

3. **Calibration guidelines**:
   - **High confidence (0.8-1.0)**: Clear, unambiguous failure with strong evidence
   - **Medium confidence (0.5-0.7)**: Reasonable hypothesis with supporting evidence but some uncertainty
   - **Low confidence (0.0-0.4)**: Speculative or insufficient evidence

4. **Flag miscalibrations**:
   - If confidence scores consistently don't match actual extraction quality, adjust `GEMINI_TEMPERATURE` or update extraction prompt
   - Document patterns where Gemini produces low-quality extractions for iterative prompt improvement

### PII Audit Checklist (T046)

Verify that no raw sensitive user data is persisted in extracted patterns:

1. **Sample 20 extracted patterns** from `evalforge_failure_patterns`

2. **For each pattern, check**:
   - ✅ `evidence.excerpt` contains only redacted or anonymized snippets
   - ✅ No email addresses, phone numbers, or personal identifiers in any field
   - ✅ User IDs (if present) are hashed/anonymized
   - ✅ Prompts and responses in `evidence` are truncated/sanitized
   - ✅ No API keys, tokens, or credentials appear in extracted content

3. **Expected redaction format**:
```json
{
  "evidence": {
    "excerpt": "User requested password reset for [REDACTED_EMAIL]",
    "user_id": "hash_a1b2c3d4",
    "prompt_snippet": "I forgot my password for...[truncated]"
  }
}
```

4. **Compliance verification**:
   - All patterns MUST pass PII audit before production deployment
   - If any PII leakage is found, review `pii_sanitizer.py` and update sanitization rules
   - Re-run extraction on affected traces after fixing sanitization

## Operational NFRs (constitution-aligned)

- **Latency**: Per-trace processing must complete within 10 seconds (spec AC4 + constitution). Traces that exceed the budget are marked timed out and recorded as errors; the batch continues.
- **Reliability**: Gemini calls retry up to 3 times with exponential backoff; failures never halt the batch.
- **Observability**: Logs include `run_id`, `source_trace_id`, per-trace outcome, and timing.
- **Privacy/PII**: Stored `evidence.excerpt` is redacted and limited to short excerpts; no raw sensitive user data is persisted.
- **Structured Output**: Uses `response_mime_type: "application/json"` with `response_schema` to guarantee valid JSON from Gemini.
