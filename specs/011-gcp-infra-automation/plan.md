# Implementation Plan: GCP Infrastructure Automation

**Branch**: `011-gcp-infra-automation` | **Date**: 2025-12-12 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/011-gcp-infra-automation/spec.md`

## Summary

Automate GCP infrastructure provisioning for EvalForge stack to eliminate 3+ hour manual setup. Delivers two shell scripts: `bootstrap_gcp.sh` (API enablement, service accounts, secrets) and `deploy.sh` (Docker build, Cloud Run deployment, Cloud Scheduler). Target: <2 hours implementation, enabling hackathon velocity.

## Technical Context

**Language/Version**: Bash 5.x (shell scripts), Python 3.11 (existing service)
**Primary Dependencies**: `gcloud` CLI, Docker, Cloud Build
**Storage**: Firestore (native mode), Secret Manager
**Testing**: Manual integration tests against live GCP project
**Target Platform**: Google Cloud Platform (Cloud Run, Cloud Scheduler)
**Project Type**: Single project with scripts directory
**Performance Goals**: Bootstrap <10 min, Deploy <5 min
**Constraints**: Idempotent scripts, least-privilege IAM, no secrets in logs
**Scale/Scope**: Single GCP project, hackathon team (2-5 developers)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| **Observability-First Insight Trail** | ✅ PASS | FR-015 requires structured logs with timestamps; scripts will emit operation status for debugging |
| **Human-Governed Fail-Safe Loops** | ✅ PASS | Scripts fail fast on missing prerequisites; explicit confirmation for teardown; no automated destructive actions |
| **Cost-Conscious Experimentation** | ✅ PASS | No LLM usage in infrastructure scripts; Cloud Run scales to zero; Secret Manager has minimal per-access cost |
| **Reliability & Cognitive Ease** | ✅ PASS | Idempotent operations; clear error messages; fail-fast behavior |
| **Demo-Ready Transparency & UX** | ✅ PASS | One-command workflows; hackathon-ready impact; working prototype priority |
| **Platform Constraints** | ✅ PASS | Uses Cloud Run (stateless), Secret Manager (not hardcoded), Firestore |
| **Workflow & Quality Gates** | ⚠️ PARTIAL | Manual testing against live GCP (not mocked); no integration test suite yet |

**Gate Result**: ✅ PASS - All critical principles satisfied. Partial on testing (acceptable for hackathon scope).

## Project Structure

### Documentation (this feature)

```text
specs/011-gcp-infra-automation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (env vars, IAM, secrets schema)
├── quickstart.md        # Phase 1 output (setup instructions)
├── contracts/           # N/A for infrastructure scripts
├── checklists/
│   └── requirements.md  # Spec validation checklist
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
evalforge/
├── scripts/
│   ├── bootstrap_gcp.sh       # NEW - GCP infrastructure setup
│   ├── deploy.sh              # NEW - Deploy to Cloud Run
│   ├── bootstrap_firestore.py # EXISTING - Create Firestore collections
│   └── generate_llm_trace_samples.py  # EXISTING
├── Dockerfile                 # NEW - Cloud Run container
├── .dockerignore              # NEW - Exclude from Docker image
├── .gcloudignore              # NEW - Exclude from Cloud Build context
├── src/                       # EXISTING - Python service code
└── tests/                     # EXISTING - Test suite
```

**Structure Decision**: Single project structure. Infrastructure scripts live in `scripts/` directory alongside existing Python bootstrap scripts. Container configuration at repo root.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Phase 1: Bootstrap (Developer Machine)                          │
│                                                                   │
│  Developer runs: ./scripts/bootstrap_gcp.sh                      │
│         │                                                         │
│         ▼                                                         │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  GCP Project Setup                                          │ │
│  │  1. Enable APIs (Firestore, Run, Secrets, Scheduler, Build) │ │
│  │  2. Create Service Account (evalforge-ingestion-sa)         │ │
│  │  3. Grant IAM Roles (Firestore User, Secret Accessor)       │ │
│  │  4. Create Secrets (datadog-api-key, datadog-app-key)       │ │
│  │  5. Bootstrap Firestore Collections (via Python script)     │ │
│  └─────────────────────────────────────────────────────────────┘ │
│         │                                                         │
│         ▼                                                         │
│  Output: Configured GCP project ready for deployment             │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Phase 2: Deploy (Developer Machine → Cloud Build → Cloud Run)   │
│                                                                   │
│  Developer runs: ./scripts/deploy.sh                             │
│         │                                                         │
│         ▼                                                         │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Cloud Build                                                │ │
│  │  1. Build Docker image from Dockerfile                      │ │
│  │  2. Push to Google Container Registry (GCR)                 │ │
│  └─────────────────────────────────────────────────────────────┘ │
│         │                                                         │
│         ▼                                                         │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Cloud Run Deployment                                       │ │
│  │  1. Deploy image to Cloud Run service                       │ │
│  │  2. Attach service account (evalforge-ingestion-sa)         │ │
│  │  3. Inject environment variables                            │ │
│  │  4. Mount secrets from Secret Manager                       │ │
│  └─────────────────────────────────────────────────────────────┘ │
│         │                                                         │
│         ▼                                                         │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Cloud Scheduler Configuration                              │ │
│  │  1. Create HTTP trigger job (every 5 minutes)               │ │
│  │  2. Point to Cloud Run URL + OIDC auth                      │ │
│  │  3. POST to /ingestion/run-once endpoint                    │ │
│  └─────────────────────────────────────────────────────────────┘ │
│         │                                                         │
│         ▼                                                         │
│  Output: Running Cloud Run service + scheduled ingestion         │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Production Runtime (Steady State)                               │
│                                                                   │
│  Cloud Scheduler (every 5min) ──────────────┐                    │
│         │                                    │                    │
│         │ (OIDC-authenticated POST)          │                    │
│         ▼                                    │                    │
│  Cloud Run (evalforge-ingestion)            │                    │
│         │                                    │                    │
│         ├──▶ Secret Manager (fetch Datadog keys)                 │
│         ├──▶ Datadog API (query LLM failures)                    │
│         └──▶ Firestore (write sanitized traces)                  │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Bootstrap Script (`scripts/bootstrap_gcp.sh`)

**Purpose**: One-command GCP project setup from empty state

**Responsibilities**:
- Enable GCP APIs using `gcloud services enable`
- Create Firestore database (native mode) in specified region
- Create service account with descriptive name
- Grant minimal IAM roles (Firestore User, Secret Accessor)
- Create Secret Manager secrets with placeholder values
- Grant service account access to secrets
- Call existing `bootstrap_firestore.py` to create collections

**Idempotency Strategy**:
- Check resource existence with `gcloud ... describe` before creating
- Use `|| true` to suppress "already exists" errors
- Log "already exists" vs "created" for transparency

**Error Handling**:
- Validate required env vars at start: `GCP_PROJECT_ID`
- Use `set -euo pipefail` for fail-fast on errors
- Provide actionable error messages

### 2. Deployment Script (`scripts/deploy.sh`)

**Purpose**: Build, push, and deploy ingestion service to Cloud Run

**Responsibilities**:
- Build Docker image using Cloud Build (remote build, not local)
- Tag image with `latest` and push to GCR
- Deploy Cloud Run service with environment variables and secrets
- Configure service account attachment
- Set resource limits (512Mi memory, 1 CPU, max 10 instances)
- Create/update Cloud Scheduler job with OIDC authentication
- Output service URL and scheduler status

**Idempotency Strategy**:
- `gcloud run deploy` updates existing service (no duplicate check needed)
- Delete existing scheduler job before creating (no update command available)

### 3. Container Image (`Dockerfile`)

**Purpose**: Package ingestion service for Cloud Run

**Design**:
- Base: `python:3.11-slim` (lightweight, security updates)
- Install dependencies via `pip install -e .` from pyproject.toml
- Use `PORT` environment variable (Cloud Run convention)
- Run FastAPI with uvicorn on 0.0.0.0:$PORT

## Implementation Phases

### Phase 1: Bootstrap Script (~60 min)

| Task | Description | Acceptance |
|------|-------------|------------|
| T1.1 | Create `bootstrap_gcp.sh` skeleton with env var validation | Script fails with clear error if `GCP_PROJECT_ID` missing |
| T1.2 | Add API enablement logic | `gcloud services list --enabled` shows Firestore, Run, Secrets, Scheduler, Build |
| T1.3 | Add service account creation with IAM bindings | SA exists with Firestore User + Secret Accessor roles |
| T1.4 | Add Secret Manager secret creation | Secrets `datadog-api-key` and `datadog-app-key` exist with placeholder values |
| T1.5 | Add Firestore database creation | Database exists in native mode |
| T1.6 | Test idempotency (run twice) | Second run succeeds, logs "already exists" |

### Phase 2: Container & Deployment (~45 min)

| Task | Description | Acceptance |
|------|-------------|------------|
| T2.1 | Create `Dockerfile` for Cloud Run | `docker build` succeeds locally |
| T2.2 | Create `.dockerignore` and `.gcloudignore` | Excludes .git, tests, venv, __pycache__ |
| T2.3 | Create `deploy.sh` with Cloud Build | Image built and pushed to GCR |
| T2.4 | Add Cloud Run deployment | Service accessible via HTTPS URL |
| T2.5 | Add Cloud Scheduler configuration | Job triggers every 5 minutes with OIDC auth |
| T2.6 | Test end-to-end deployment | `gcloud scheduler jobs run` triggers ingestion |

### Phase 3: Manual Testing (~15 min)

| Task | Description | Acceptance |
|------|-------------|------------|
| T3.1 | Fresh project test | Bootstrap + deploy in new project succeeds |
| T3.2 | Idempotency test | Running both scripts twice succeeds |
| T3.3 | Scheduler trigger test | Manual job run shows logs in Cloud Run |

## Environment Variables

### Bootstrap Phase

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GCP_PROJECT_ID` | Yes | - | Target GCP project ID |
| `GCP_REGION` | No | `us-central1` | Region for Firestore/Cloud Run |

### Deployment Phase

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GCP_PROJECT_ID` | Yes | - | Target GCP project |
| `GCP_REGION` | No | `us-central1` | Deployment region |
| `SERVICE_NAME` | No | `evalforge-ingestion` | Cloud Run service name |
| `DATADOG_SITE` | No | `us5.datadoghq.com` | Datadog datacenter |
| `INGESTION_SCHEDULE` | No | `*/5 * * * *` | Cron schedule |

### Runtime (Cloud Run)

| Variable | Source | Description |
|----------|--------|-------------|
| `GOOGLE_CLOUD_PROJECT` | Injected | GCP project ID |
| `DATADOG_SITE` | Injected | Datadog datacenter |
| `FIRESTORE_COLLECTION_PREFIX` | Injected | Collection prefix (`evalforge_`) |
| `DATADOG_API_KEY` | Secret Manager | From `datadog-api-key:latest` |
| `DATADOG_APP_KEY` | Secret Manager | From `datadog-app-key:latest` |

## IAM Configuration

**Service Account**: `evalforge-ingestion-sa@{project}.iam.gserviceaccount.com`

| Role | Purpose |
|------|---------|
| `roles/datastore.user` | Read/write Firestore collections |
| `roles/secretmanager.secretAccessor` | Read secrets (Datadog keys) |

**Rationale**: Minimal permissions for Cloud Run service to operate. No broader access.

## Secret Manager Schema

| Secret Name | Initial Value | Access |
|-------------|---------------|--------|
| `datadog-api-key` | `REPLACE_WITH_ACTUAL_API_KEY` | `evalforge-ingestion-sa` |
| `datadog-app-key` | `REPLACE_WITH_ACTUAL_APP_KEY` | `evalforge-ingestion-sa` |

## Testing Strategy

### Integration Testing (Live GCP)

```bash
# Test 1: Fresh project bootstrap
export GCP_PROJECT_ID="test-evalforge-fresh"
./scripts/bootstrap_gcp.sh
# Verify: APIs enabled, SA created, secrets exist

# Test 2: Idempotent bootstrap
./scripts/bootstrap_gcp.sh  # Run again
# Verify: No errors, logs show "already exists"

# Test 3: Deploy service
./scripts/deploy.sh
# Verify: Cloud Run service running, scheduler job exists

# Test 4: Manual trigger
gcloud scheduler jobs run evalforge-ingestion-trigger --location=us-central1
# Verify: Cloud Run logs show ingestion execution
```

## Deferred Items

| Item | Reason | Future Issue |
|------|--------|--------------|
| Teardown script | Hackathon scope reduction | Post-hackathon |
| Terraform migration | Shell scripts sufficient for hackathon | Future |
| CI/CD pipeline | Manual deployment acceptable for hackathon | Future |
| Multi-environment support | Single project for hackathon | Future |

## Complexity Tracking

> No violations requiring justification. All constitution principles satisfied.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | - | - |

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Firestore database already exists | Check existence first, skip creation |
| Service account name collision | Use consistent naming, check existence |
| Cloud Build quota exceeded | Use standard quotas (sufficient for hackathon) |
| Secret Manager API not enabled | Enable APIs first in bootstrap |
| Cloud Scheduler 403 on Cloud Run | Use matching service account for OIDC |

## Success Criteria Mapping

| Success Criterion | Implementation Task |
|-------------------|---------------------|
| SC-001: Bootstrap <10 min | T1.1-T1.6 |
| SC-002: 1 manual step | Bootstrap uses `GCP_PROJECT_ID` env var only |
| SC-003: 100% success rate | Idempotent scripts, clear errors |
| SC-004: Deploy <5 min | T2.1-T2.6 |
| SC-005: Zero cloud expertise needed | One-command deploy |
| SC-007: Structured logs | All scripts emit timestamped status |
| SC-008: Idempotent | T1.6, T2.6 verify idempotency |
