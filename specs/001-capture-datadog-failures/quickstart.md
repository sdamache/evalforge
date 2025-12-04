# Quickstart: Automatic Capture of Datadog Failures

This guide explains how to run the Datadog ingestion service that captures LLM failures into Firestore for downstream evals, guardrails, and runbooks.

## Prerequisites

- Python 3.11
- Access to Datadog with LLM Observability enabled
- Google Cloud project with:
  - Cloud Run
  - Firestore
  - Secret Manager
  - Cloud Scheduler

## Environment Configuration

1. Create the following secrets in Google Secret Manager:
   - `datadog-api-key`
   - `datadog-app-key`

2. Set environment variables for the ingestion service:

```bash
DATADOG_API_KEY=projects/PROJECT_ID/secrets/datadog-api-key/versions/latest
DATADOG_APP_KEY=projects/PROJECT_ID/secrets/datadog-app-key/versions/latest
DATADOG_SITE=datadoghq.com
TRACE_LOOKBACK_HOURS=24
QUALITY_THRESHOLD=0.5
FIRESTORE_COLLECTION_PREFIX=evalforge_
```

## Local Development Flow

1. Install dependencies and set up your virtualenv as described in the repository README.
2. Run the ingestion service locally (for example):

```bash
python -m src.ingestion.main
```

3. Trigger a one-off ingestion run using the configured scheduler or a manual HTTP call to the `/ingestion/run-once` endpoint.

## Deployment Outline

1. Build and deploy the ingestion service to Cloud Run.
2. Configure Cloud Scheduler to call the Cloud Run URL every 15 minutes:

```text
Cron: */15 * * * *
```

3. Verify failures are written to the Firestore collection `evalforge_raw_traces` with PII stripped and `user_hash` populated.
