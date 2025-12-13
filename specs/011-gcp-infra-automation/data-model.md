# Data Model: GCP Infrastructure Automation

**Feature**: 011-gcp-infra-automation
**Date**: 2025-12-12

## Overview

This feature does not involve traditional application data models (entities, relationships). Instead, it defines configuration schemas for infrastructure resources. This document captures the "data model" as environment variables, IAM configurations, and secret schemas.

## Environment Variables

### Bootstrap Configuration

| Variable | Type | Required | Default | Validation |
|----------|------|----------|---------|------------|
| `GCP_PROJECT_ID` | string | Yes | - | Must match `^[a-z][a-z0-9-]{4,28}[a-z0-9]$` |
| `GCP_REGION` | string | No | `us-central1` | Must be valid GCP region |

### Deployment Configuration

| Variable | Type | Required | Default | Validation |
|----------|------|----------|---------|------------|
| `GCP_PROJECT_ID` | string | Yes | - | Same as bootstrap |
| `GCP_REGION` | string | No | `us-central1` | Must be valid GCP region |
| `SERVICE_NAME` | string | No | `evalforge-ingestion` | Alphanumeric + hyphens, max 63 chars |
| `DATADOG_SITE` | string | No | `us5.datadoghq.com` | Valid Datadog site URL |
| `INGESTION_SCHEDULE` | string | No | `*/5 * * * *` | Valid cron expression |

### Runtime Configuration (Cloud Run)

| Variable | Type | Source | Description |
|----------|------|--------|-------------|
| `GOOGLE_CLOUD_PROJECT` | string | Injected by deploy.sh | GCP project ID |
| `DATADOG_SITE` | string | Injected by deploy.sh | Datadog datacenter |
| `FIRESTORE_COLLECTION_PREFIX` | string | Injected by deploy.sh | Collection prefix (`evalforge_`) |
| `TRACE_LOOKBACK_HOURS` | integer | Injected by deploy.sh | Datadog query window (24) |
| `QUALITY_THRESHOLD` | float | Injected by deploy.sh | Quality score filter (0.5) |
| `INGESTION_LATENCY_MINUTES` | integer | Injected by deploy.sh | Scheduler cadence (5) |
| `PORT` | integer | Cloud Run | Port to bind (default 8080) |

### Secrets (from Secret Manager)

| Variable | Secret Name | Description |
|----------|-------------|-------------|
| `DATADOG_API_KEY` | `datadog-api-key` | Datadog API authentication |
| `DATADOG_APP_KEY` | `datadog-app-key` | Datadog application key |

## GCP Resource Schema

### Service Account

```yaml
name: evalforge-ingestion-sa
project: ${GCP_PROJECT_ID}
display_name: "EvalForge Ingestion Service Account"
email: evalforge-ingestion-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com
```

### IAM Bindings

```yaml
bindings:
  - member: serviceAccount:evalforge-ingestion-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com
    roles:
      - roles/datastore.user         # Firestore read/write
      - roles/secretmanager.secretAccessor  # Secret read
      - roles/logging.logWriter      # Cloud Logging write (auto-granted to Cloud Run)
```

### Secret Manager Secrets

```yaml
secrets:
  - name: datadog-api-key
    replication: automatic
    initial_value: "REPLACE_WITH_ACTUAL_API_KEY"
    access:
      - evalforge-ingestion-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com

  - name: datadog-app-key
    replication: automatic
    initial_value: "REPLACE_WITH_ACTUAL_APP_KEY"
    access:
      - evalforge-ingestion-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com
```

### Cloud Run Service

```yaml
service:
  name: ${SERVICE_NAME}
  region: ${GCP_REGION}
  image: gcr.io/${GCP_PROJECT_ID}/evalforge-ingestion:latest
  service_account: evalforge-ingestion-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com

  resources:
    limits:
      memory: 512Mi
      cpu: "1"

  scaling:
    min_instances: 0
    max_instances: 10

  environment:
    - GOOGLE_CLOUD_PROJECT=${GCP_PROJECT_ID}
    - DATADOG_SITE=${DATADOG_SITE}
    - FIRESTORE_COLLECTION_PREFIX=evalforge_
    - TRACE_LOOKBACK_HOURS=24
    - QUALITY_THRESHOLD=0.5
    - INGESTION_LATENCY_MINUTES=5

  secrets:
    - DATADOG_API_KEY=datadog-api-key:latest
    - DATADOG_APP_KEY=datadog-app-key:latest

  ingress: internal-and-cloud-load-balancing  # Not publicly accessible
  authentication: required  # OIDC required
```

### Cloud Scheduler Job

```yaml
job:
  name: evalforge-ingestion-trigger
  location: ${GCP_REGION}
  schedule: ${INGESTION_SCHEDULE}  # Default: */5 * * * *
  timezone: UTC

  http_target:
    uri: https://${SERVICE_URL}/ingestion/run-once
    http_method: POST

  oidc_token:
    service_account_email: evalforge-ingestion-sa@${GCP_PROJECT_ID}.iam.gserviceaccount.com
    audience: https://${SERVICE_URL}

  retry_config:
    retry_count: 3
    min_backoff_duration: 5s
    max_backoff_duration: 60s
```

### Firestore Database

```yaml
database:
  name: (default)
  type: FIRESTORE_NATIVE
  location: ${GCP_REGION}

collections:  # Created by bootstrap_firestore.py
  - evalforge_traces
  - evalforge_suggestions
  - evalforge_patterns
```

### GCP APIs

```yaml
apis:
  - run.googleapis.com              # Cloud Run
  - firestore.googleapis.com        # Firestore
  - secretmanager.googleapis.com    # Secret Manager
  - cloudscheduler.googleapis.com   # Cloud Scheduler
  - cloudbuild.googleapis.com       # Cloud Build
  - artifactregistry.googleapis.com # Artifact Registry (optional)
```

## State Transitions

### Bootstrap Script State Machine

```
[START]
    │
    ▼
[Check GCP_PROJECT_ID] ──(missing)──▶ [ERROR: Set GCP_PROJECT_ID]
    │
    │(present)
    ▼
[Enable APIs] ──(each API)──▶ [Skip if enabled] or [Enable]
    │
    ▼
[Check Firestore DB] ──(exists)──▶ [Skip creation]
    │
    │(not exists)
    ▼
[Create Firestore DB]
    │
    ▼
[Check Service Account] ──(exists)──▶ [Skip creation]
    │
    │(not exists)
    ▼
[Create Service Account]
    │
    ▼
[Grant IAM Roles] ──(for each role)──▶ [Skip if bound] or [Bind]
    │
    ▼
[Create Secrets] ──(for each secret)──▶ [Skip if exists] or [Create with placeholder]
    │
    ▼
[Grant Secret Access]
    │
    ▼
[Run bootstrap_firestore.py]
    │
    ▼
[SUCCESS: Bootstrap complete]
```

### Deploy Script State Machine

```
[START]
    │
    ▼
[Check GCP_PROJECT_ID] ──(missing)──▶ [ERROR: Set GCP_PROJECT_ID]
    │
    │(present)
    ▼
[Build Docker Image via Cloud Build]
    │
    │(success)
    ▼
[Deploy to Cloud Run] ──(creates or updates)
    │
    │(success)
    ▼
[Get Service URL]
    │
    ▼
[Check Scheduler Job] ──(exists)──▶ [Delete existing job]
    │
    ▼
[Create Scheduler Job with OIDC]
    │
    │(success)
    ▼
[SUCCESS: Deployment complete, output URL]
```

## Validation Rules

### GCP_PROJECT_ID

- Must be 6-30 characters
- Must start with a lowercase letter
- Can contain lowercase letters, digits, and hyphens
- Cannot end with a hyphen
- Regex: `^[a-z][a-z0-9-]{4,28}[a-z0-9]$`

### SERVICE_NAME

- Must be 1-63 characters
- Must start with a letter
- Can contain lowercase letters, digits, and hyphens
- Cannot end with a hyphen
- Regex: `^[a-z][a-z0-9-]{0,61}[a-z0-9]?$`

### INGESTION_SCHEDULE

- Must be valid cron expression
- 5 fields: minute hour day-of-month month day-of-week
- Example: `*/5 * * * *` (every 5 minutes)

### GCP_REGION

- Must be valid GCP region
- Common values: `us-central1`, `us-east1`, `europe-west1`, `asia-east1`
- Validated by gcloud at runtime
