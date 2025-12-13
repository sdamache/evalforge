#!/usr/bin/env bash
# Deploy EvalForge Ingestion Service to Cloud Run
# Purpose: Build Docker image and deploy to Cloud Run with Cloud Scheduler
# Usage: GCP_PROJECT_ID=your-project ./scripts/deploy.sh

set -euo pipefail

#=============================================================================
# Logging Helper Functions
#=============================================================================

log_info() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] $*"
}

log_error() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" >&2
}

log_success() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [SUCCESS] $*"
}

#=============================================================================
# Environment Variable Validation and Defaults
#=============================================================================

# Required: GCP Project ID
if [[ -z "${GCP_PROJECT_ID:-}" ]]; then
  log_error "GCP_PROJECT_ID environment variable is required"
  log_error "Usage: GCP_PROJECT_ID=your-project-id ./scripts/deploy.sh"
  exit 1
fi

# Optional: Configurable defaults
GCP_REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-evalforge-ingestion}"
DATADOG_SITE="${DATADOG_SITE:-us5.datadoghq.com}"
INGESTION_SCHEDULE="${INGESTION_SCHEDULE:-*/5 * * * *}"

# Derived values
SERVICE_ACCOUNT_NAME="evalforge-ingestion-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
IMAGE_NAME="gcr.io/${GCP_PROJECT_ID}/${SERVICE_NAME}:latest"

log_info "Starting deployment for project: ${GCP_PROJECT_ID}"
log_info "Region: ${GCP_REGION}"
log_info "Service Name: ${SERVICE_NAME}"
log_info "Image: ${IMAGE_NAME}"

#=============================================================================
# Build Docker Image via Cloud Build
#=============================================================================

build_image() {
  log_info "Building Docker image via Cloud Build..."

  # Submit build to Cloud Build (builds from repository root using Dockerfile)
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
#=============================================================================

deploy_cloud_run() {
  log_info "Deploying to Cloud Run service: ${SERVICE_NAME}..."

  # Deploy service with all required configuration
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

  log_info "Cloud Run service deployed successfully"
}

#=============================================================================
# Get Service URL
#=============================================================================

get_service_url() {
  log_info "Retrieving Cloud Run service URL..."

  # Get the service URL
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
  echo "${SERVICE_URL}"
}

#=============================================================================
# Create Cloud Scheduler Job (Idempotent)
#=============================================================================

create_scheduler_job() {
  local service_url="$1"
  local job_name="${SERVICE_NAME}-trigger"

  log_info "Setting up Cloud Scheduler job: ${job_name}..."

  # Check if job already exists and delete if it does (for idempotency)
  if gcloud scheduler jobs describe "${job_name}" \
    --location="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --quiet &>/dev/null; then
    log_info "Scheduler job already exists, deleting for update..."
    gcloud scheduler jobs delete "${job_name}" \
      --location="${GCP_REGION}" \
      --project="${GCP_PROJECT_ID}" \
      --quiet || {
        log_error "Failed to delete existing scheduler job"
        exit 1
      }
  fi

  # Create new scheduler job with OIDC authentication
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
    --labels="managed-by=evalforge" \
    --quiet || {
      log_error "Failed to create scheduler job"
      log_error "Ensure Cloud Scheduler API is enabled and service account exists"
      exit 1
    }

  log_info "Cloud Scheduler job created: ${job_name}"
}

#=============================================================================
# Main Execution Flow
#=============================================================================

main() {
  # Step 1: Build Docker image
  build_image

  # Step 2: Deploy to Cloud Run
  deploy_cloud_run

  # Step 3: Get service URL
  SERVICE_URL=$(get_service_url)

  # Step 4: Create/update Cloud Scheduler job
  create_scheduler_job "${SERVICE_URL}"

  # Success message with next steps
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
