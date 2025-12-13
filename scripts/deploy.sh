#!/usr/bin/env bash
# =============================================================================
# Deploy EvalForge Ingestion Service to Cloud Run
# =============================================================================
# Purpose: Build Docker image via Cloud Build and deploy to Cloud Run with
#          automatic scheduling via Cloud Scheduler. This script is idempotent
#          - safe to run multiple times to update the deployment.
#
# What this script does:
#   1. Builds Docker image using Cloud Build (not local Docker)
#   2. Deploys image to Cloud Run with secrets and environment variables
#   3. Creates/updates Cloud Scheduler job for periodic ingestion triggers
#
# Prerequisites:
#   - Run bootstrap_gcp.sh first (creates service account, secrets, APIs)
#   - Update Datadog secrets with actual credentials
#   - Dockerfile exists at repository root
#
# Usage:
#   GCP_PROJECT_ID=your-project-id ./scripts/deploy.sh
#   GCP_PROJECT_ID=your-project DATADOG_SITE=datadoghq.eu ./scripts/deploy.sh
#
# Environment variables:
#   GCP_PROJECT_ID     (required) - Target GCP project
#   GCP_REGION         (optional) - Deployment region (default: us-central1)
#   SERVICE_NAME       (optional) - Cloud Run service name (default: evalforge-ingestion)
#   DATADOG_SITE       (optional) - Datadog site (default: us5.datadoghq.com)
#   INGESTION_SCHEDULE (optional) - Cron schedule (default: */5 * * * *)
#
# Exit codes:
#   0 - Success
#   1 - Missing requirements, build failure, or deployment error
# =============================================================================

set -euo pipefail  # Exit on error, undefined vars, and pipe failures

#=============================================================================
# Logging Helper Functions
# All logs go to stderr to keep stdout clean for machine-readable output
# (e.g., service URL can be captured: SERVICE_URL=$(./deploy.sh 2>/dev/null))
#=============================================================================

log_info() {
  # Standard informational messages with ISO timestamp to stderr
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] $*" >&2
}

log_error() {
  # Error messages to stderr with ERROR prefix for filtering
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" >&2
}

log_success() {
  # Success messages to stderr for visual confirmation
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [SUCCESS] $*" >&2
}

#=============================================================================
# Environment Variable Validation and Defaults
# Fail fast on missing required vars, provide sensible defaults for optional.
#=============================================================================

# Required: GCP Project ID - determines where to deploy
if [[ -z "${GCP_PROJECT_ID:-}" ]]; then
  log_error "GCP_PROJECT_ID environment variable is required"
  log_error "Usage: GCP_PROJECT_ID=your-project-id ./scripts/deploy.sh"
  exit 1
fi

# Optional: Configurable deployment parameters with sensible defaults
GCP_REGION="${GCP_REGION:-us-central1}"          # Cloud Run region
SERVICE_NAME="${SERVICE_NAME:-evalforge-ingestion}" # Cloud Run service name
DATADOG_SITE="${DATADOG_SITE:-us5.datadoghq.com}"   # Datadog datacenter
INGESTION_SCHEDULE="${INGESTION_SCHEDULE:-*/5 * * * *}" # Every 5 minutes

# Derived values: computed from user inputs
SERVICE_ACCOUNT_NAME="evalforge-ingestion-sa"  # Must match bootstrap_gcp.sh
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
IMAGE_NAME="gcr.io/${GCP_PROJECT_ID}/${SERVICE_NAME}:latest" # GCR image path

log_info "Starting deployment for project: ${GCP_PROJECT_ID}"
log_info "Region: ${GCP_REGION}"
log_info "Service Name: ${SERVICE_NAME}"
log_info "Image: ${IMAGE_NAME}"

#=============================================================================
# Build Docker Image via Cloud Build
# Uses Cloud Build instead of local Docker for several benefits:
# - No local Docker installation required
# - Faster builds (GCP machines are optimized for this)
# - Built images automatically pushed to GCR
# - Consistent build environment across machines
#=============================================================================

build_image() {
  log_info "Building Docker image via Cloud Build..."

  # Submit build to Cloud Build - uploads context and builds remotely
  # The '.' at end specifies repository root as build context
  # --quiet suppresses verbose output but still shows progress
  gcloud builds submit \
    --tag="${IMAGE_NAME}" \
    --project="${GCP_PROJECT_ID}" \
    --quiet \
    . || {
      log_error "Failed to build image with Cloud Build"
      log_error "Ensure Dockerfile exists and Cloud Build API is enabled"
      exit 1
    }

  log_info "Image built successfully: ${IMAGE_NAME}"
}

#=============================================================================
# Deploy to Cloud Run
# Cloud Run deployment is idempotent - running deploy on existing service
# updates it in place (rolling update with zero downtime).
#=============================================================================

deploy_cloud_run() {
  log_info "Deploying to Cloud Run service: ${SERVICE_NAME}..."

  # Deploy service with all required configuration
  # Key configuration decisions explained:
  gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE_NAME}" \
    --region="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --service-account="${SERVICE_ACCOUNT_EMAIL}" \
    --set-secrets="DATADOG_API_KEY=datadog-api-key:latest,DATADOG_APP_KEY=datadog-app-key:latest" \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${GCP_PROJECT_ID},DATADOG_SITE=${DATADOG_SITE},FIRESTORE_COLLECTION_PREFIX=evalforge_,TRACE_LOOKBACK_HOURS=24,QUALITY_THRESHOLD=0.5,INGESTION_LATENCY_MINUTES=5" \
    --memory=512Mi \
    --cpu=1 \
    --min-instances=0 \
    --max-instances=10 \
    --ingress=internal-and-cloud-load-balancing \
    --no-allow-unauthenticated \
    --labels="managed-by=evalforge" \
    --quiet || {
      log_error "Failed to deploy to Cloud Run"
      log_error "Ensure service account and secrets exist (run bootstrap_gcp.sh first)"
      exit 1
    }
  # Configuration notes:
  # - --set-secrets: Mounts secrets as env vars at runtime (never in image)
  # - --min-instances=0: Scale to zero when idle (cost savings)
  # - --max-instances=10: Prevent runaway scaling
  # - --ingress=internal-and-cloud-load-balancing: Only Cloud Scheduler can call
  # - --no-allow-unauthenticated: Requires OIDC token (Cloud Scheduler provides)
  # - --labels: Enable filtering with gcloud run services list --filter="labels.managed-by=evalforge"

  log_info "Cloud Run service deployed successfully"
}

#=============================================================================
# Get Service URL
# Retrieves the HTTPS URL assigned to the Cloud Run service.
# This URL is needed for configuring Cloud Scheduler's target endpoint.
#=============================================================================

get_service_url() {
  log_info "Retrieving Cloud Run service URL..."

  # Get the service URL from Cloud Run service metadata
  # The URL is auto-generated by GCP in format: https://{service}-{hash}-{region}.a.run.app
  SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
    --region="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --format="value(status.url)" 2>/dev/null)

  if [[ -z "${SERVICE_URL}" ]]; then
    log_error "Failed to retrieve service URL"
    log_error "Service may not be deployed yet"
    exit 1
  fi

  log_info "Service URL: ${SERVICE_URL}"
  # Output to stdout so caller can capture: url=$(get_service_url)
  echo "${SERVICE_URL}"
}

#=============================================================================
# Grant Cloud Run Invoker Role (Required for Cloud Scheduler)
# Cloud Scheduler uses OIDC tokens to authenticate, but the service account
# still needs permission to invoke the Cloud Run service. Without this role,
# scheduled calls will return 403 Forbidden.
#=============================================================================

grant_run_invoker() {
  log_info "Granting Cloud Run invoker role to service account..."

  # Grant roles/run.invoker on the specific Cloud Run service
  # This is idempotent - adding existing binding is a no-op
  gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --region="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/run.invoker" \
    --quiet &>/dev/null || {
      log_error "Failed to grant Cloud Run invoker role"
      log_error "Ensure Cloud Run service exists and you have IAM permissions"
      exit 1
    }

  log_info "Cloud Run invoker role granted to ${SERVICE_ACCOUNT_NAME}"
}

#=============================================================================
# Create or Update Cloud Scheduler Job (Idempotent with Best Practices)
# Cloud Scheduler triggers the ingestion service on a cron schedule.
# Uses OIDC authentication so only GCP-authenticated requests are accepted.
#
# Idempotency strategy:
#   1. Try update first (most common case on redeploy)
#   2. If update fails, pause → delete → recreate
#   3. New jobs are created directly
#=============================================================================

create_or_update_scheduler_job() {
  local service_url="$1"
  local job_name="${SERVICE_NAME}-trigger"  # Naming convention: {service}-trigger

  log_info "Setting up Cloud Scheduler job: ${job_name}..."

  # Check if job already exists
  if gcloud scheduler jobs describe "${job_name}" \
    --location="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --quiet &>/dev/null; then

    log_info "Scheduler job already exists, attempting update..."

    # Try to update the existing job (preferred approach - no downtime)
    # Note: Cloud Scheduler doesn't support labels via gcloud CLI (only via API/Terraform)
    if gcloud scheduler jobs update http "${job_name}" \
      --location="${GCP_REGION}" \
      --project="${GCP_PROJECT_ID}" \
      --schedule="${INGESTION_SCHEDULE}" \
      --uri="${service_url}/ingestion/run-once" \
      --http-method=POST \
      --oidc-service-account-email="${SERVICE_ACCOUNT_EMAIL}" \
      --oidc-token-audience="${service_url}" \
      --time-zone="UTC" \
      --attempt-deadline=600s \
      --quiet 2>/dev/null; then
      log_info "Scheduler job updated successfully: ${job_name}"
      return 0
    else
      # Update failed (can happen if job type changed) - recreate
      log_info "Update failed, recreating job..."

      # Pause first to prevent in-flight executions during deletion
      gcloud scheduler jobs pause "${job_name}" \
        --location="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --quiet &>/dev/null || true  # Ignore pause errors

      # Delete the existing job
      gcloud scheduler jobs delete "${job_name}" \
        --location="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --quiet || {
          log_error "Failed to delete existing scheduler job"
          exit 1
        }
    fi
  fi

  # Create new scheduler job with OIDC authentication
  # OIDC ensures only authenticated GCP services can trigger the endpoint
  # Note: Cloud Scheduler doesn't support labels via gcloud CLI (only via API/Terraform)
  log_info "Creating Cloud Scheduler job with schedule: ${INGESTION_SCHEDULE}..."
  gcloud scheduler jobs create http "${job_name}" \
    --location="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --schedule="${INGESTION_SCHEDULE}" \
    --uri="${service_url}/ingestion/run-once" \
    --http-method=POST \
    --oidc-service-account-email="${SERVICE_ACCOUNT_EMAIL}" \
    --oidc-token-audience="${service_url}" \
    --time-zone="UTC" \
    --attempt-deadline=600s \
    --quiet || {
      log_error "Failed to create scheduler job"
      log_error "Ensure Cloud Scheduler API is enabled and service account exists"
      exit 1
    }
  # Notes:
  # - --oidc-service-account-email: SA to impersonate for OIDC token
  # - --oidc-token-audience: Must match service URL for Cloud Run auth
  # - --attempt-deadline=600s: 10 min max execution time

  log_info "Cloud Scheduler job created successfully: ${job_name}"
}

#=============================================================================
# Main Execution Flow
# Orchestrates the deployment steps in order. Each step depends on the previous:
#   1. Build image (required for deploy)
#   2. Deploy to Cloud Run (required for URL and IAM)
#   3. Get service URL (required for scheduler)
#   4. Grant invoker role (required for scheduler to call service)
#   5. Configure scheduler (uses service URL)
#=============================================================================

main() {
  # Step 1: Build Docker image via Cloud Build
  build_image

  # Step 2: Deploy image to Cloud Run (creates/updates service)
  deploy_cloud_run

  # Step 3: Get the service URL from deployed service
  SERVICE_URL=$(get_service_url)

  # Step 4: Grant invoker role so Cloud Scheduler can call the service
  grant_run_invoker

  # Step 5: Create/update Cloud Scheduler job pointing to service URL
  create_or_update_scheduler_job "${SERVICE_URL}"

  # Success message with next steps for verification
  log_success "Deployment complete!"
  echo ""
  echo "==================================================================="
  echo "  DEPLOYMENT SUMMARY"
  echo "==================================================================="
  echo "Service URL:     ${SERVICE_URL}"
  echo "Service Name:    ${SERVICE_NAME}"
  echo "Region:          ${GCP_REGION}"
  echo "Scheduler Job:   ${SERVICE_NAME}-trigger"
  echo "Schedule:        ${INGESTION_SCHEDULE} (UTC)"
  echo ""
  echo "==================================================================="
  echo "  NEXT STEPS"
  echo "==================================================================="
  echo ""
  echo "1. Verify deployment:"
  echo "   gcloud scheduler jobs run ${SERVICE_NAME}-trigger \\"
  echo "     --location=${GCP_REGION} \\"
  echo "     --project=${GCP_PROJECT_ID}"
  echo ""
  echo "2. View Cloud Run logs:"
  echo "   gcloud run services logs read ${SERVICE_NAME} \\"
  echo "     --region=${GCP_REGION} \\"
  echo "     --project=${GCP_PROJECT_ID} \\"
  echo "     --limit=50"
  echo ""
  echo "3. Check scheduler jobs:"
  echo "   gcloud scheduler jobs list \\"
  echo "     --location=${GCP_REGION} \\"
  echo "     --project=${GCP_PROJECT_ID}"
  echo ""
  echo "==================================================================="
}

# Execute main function
main
