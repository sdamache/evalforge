# Research: GCP Infrastructure Automation

**Feature**: 011-gcp-infra-automation
**Date**: 2025-12-12
**Status**: Complete (no NEEDS CLARIFICATION items)

## Overview

This research document captures decisions and best practices for implementing GCP infrastructure automation scripts. Since the user provided comprehensive technical context in the plan input, no additional research was required.

## Decisions

### D1: Shell Scripts vs Terraform

**Decision**: Use Bash shell scripts with `gcloud` CLI for hackathon phase

**Rationale**:
- Team already knows bash - no learning curve
- Fastest path to working automation
- Sufficient for single-project hackathon scope
- Can be migrated to Terraform post-hackathon

**Alternatives Considered**:
- Terraform: More declarative, better state management, but requires learning curve
- Pulumi: Python-based IaC, but adds dependency complexity
- Cloud Deployment Manager: GCP-native, but YAML syntax is verbose

### D2: Build Strategy - Local vs Cloud Build

**Decision**: Use Cloud Build (remote build) instead of local Docker builds

**Rationale**:
- Removes local Docker dependency for deployment
- Consistent build environment across developers
- Integrated with GCR for image storage
- Builds complete in <3 minutes typically

**Alternatives Considered**:
- Local Docker build + push: Faster for small images, but requires Docker installed
- Kaniko: Good for CI/CD, but overkill for manual scripts

### D3: Secret Injection - Build-time vs Runtime

**Decision**: Mount secrets at runtime via Secret Manager

**Rationale**:
- Secrets never baked into image (security)
- Can rotate secrets without redeploying
- Cloud Run native integration with `--set-secrets` flag
- Audit logging built into Secret Manager

**Alternatives Considered**:
- Environment variables at build time: Exposes secrets in image layers
- Sidecar secret agent: Complex for hackathon scope

### D4: Cloud Scheduler Authentication

**Decision**: Use OIDC authentication with service account

**Rationale**:
- Cloud Run requires authentication (not publicly accessible)
- OIDC tokens are automatically validated by Cloud Run
- Service account provides identity for authorization
- No manual token management required

**Alternatives Considered**:
- API key in header: Less secure, requires secret management
- Public endpoint: Violates constitution security requirements

### D5: Firestore Database Creation

**Decision**: Check existence before creating, skip if exists

**Rationale**:
- `gcloud firestore databases create` fails if database exists
- Checking first enables idempotent behavior
- Use `gcloud firestore databases describe` to check existence

**Alternatives Considered**:
- Try create, suppress error: Less clear intent, harder to debug
- Always fail if exists: Not idempotent, blocks re-runs

### D6: IAM Role Binding Approach

**Decision**: Use project-level IAM bindings with specific roles

**Rationale**:
- `roles/datastore.user` grants Firestore read/write without admin
- `roles/secretmanager.secretAccessor` grants secret read without admin
- Project-level sufficient for single-service hackathon
- No resource-level IAM complexity

**Alternatives Considered**:
- Resource-level IAM: More granular, but complex for hackathon
- Custom IAM role: Unnecessary, predefined roles sufficient

## Best Practices Applied

### BP1: Idempotent Script Design

- Check resource existence before creation
- Use `|| true` to suppress "already exists" errors where appropriate
- Log "already exists" vs "created" for transparency
- `gcloud run deploy` is inherently idempotent (updates existing)

### BP2: Error Handling in Bash

- Use `set -euo pipefail` at script start
- Validate required environment variables first
- Provide actionable error messages with fix instructions
- Exit with non-zero code on failure

### BP3: Structured Logging

- Emit timestamped status messages
- Use consistent format: `[TIMESTAMP] [STATUS] Message`
- Include operation name and result
- Enable debugging by increasing verbosity

### BP4: Secret Security

- Never log secret values
- Never echo secrets to stdout
- Use placeholder values in bootstrap
- Instruct user to update via GCP console or gcloud

## GCP API Reference

### APIs to Enable

| API | Service Name | Purpose |
|-----|--------------|---------|
| Cloud Run | `run.googleapis.com` | Container hosting |
| Firestore | `firestore.googleapis.com` | Database |
| Secret Manager | `secretmanager.googleapis.com` | Credentials |
| Cloud Scheduler | `cloudscheduler.googleapis.com` | Cron jobs |
| Cloud Build | `cloudbuild.googleapis.com` | Docker builds |
| Artifact Registry | `artifactregistry.googleapis.com` | Image storage (alternative to GCR) |

### Key gcloud Commands

```bash
# Enable API
gcloud services enable run.googleapis.com --project=$PROJECT_ID

# Create service account
gcloud iam service-accounts create evalforge-ingestion-sa \
  --display-name="EvalForge Ingestion Service Account" \
  --project=$PROJECT_ID

# Grant IAM role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:evalforge-ingestion-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

# Create secret
gcloud secrets create datadog-api-key \
  --replication-policy="automatic" \
  --project=$PROJECT_ID
echo -n "PLACEHOLDER" | gcloud secrets versions add datadog-api-key --data-file=-

# Deploy Cloud Run
gcloud run deploy evalforge-ingestion \
  --image=gcr.io/$PROJECT_ID/evalforge-ingestion:latest \
  --service-account=evalforge-ingestion-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --set-secrets=DATADOG_API_KEY=datadog-api-key:latest \
  --region=$REGION \
  --project=$PROJECT_ID

# Create Cloud Scheduler
gcloud scheduler jobs create http evalforge-ingestion-trigger \
  --schedule="*/5 * * * *" \
  --uri="https://$SERVICE_URL/ingestion/run-once" \
  --http-method=POST \
  --oidc-service-account-email=evalforge-ingestion-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --location=$REGION \
  --project=$PROJECT_ID
```

## Conclusion

All technical decisions are resolved. No NEEDS CLARIFICATION items remain. Ready to proceed to Phase 1 (data-model.md, quickstart.md).
