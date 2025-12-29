#!/usr/bin/env bash
# =============================================================================
# Deploy EvalForge Deduplication Service to Cloud Run
# =============================================================================
# Purpose: Build Docker image via Cloud Build and deploy to Cloud Run with
#          automatic scheduling via Cloud Scheduler. This script is idempotent
#          - safe to run multiple times to update the deployment.
#
# What this script does:
#   1. Creates service account with Vertex AI and Firestore permissions
#   2. Builds Docker image using Cloud Build (Dockerfile.deduplication)
#   3. Deploys image to Cloud Run with environment variables
#   4. Creates/updates Cloud Scheduler job for periodic deduplication (optional)
#
# Prerequisites:
#   - Run bootstrap_gcp.sh first (enables APIs, creates Firestore database)
#   - gcloud CLI authenticated (gcloud auth login)
#   - Vertex AI API enabled in project
#
# Usage:
#   GCP_PROJECT_ID=your-project-id ./scripts/deploy_deduplication.sh
#   GCP_PROJECT_ID=your-project SKIP_SCHEDULER=1 ./scripts/deploy_deduplication.sh
#
# Environment variables:
#   GCP_PROJECT_ID        (required) - Target GCP project
#   GCP_REGION            (optional) - Deployment region (default: us-central1)
#   SERVICE_NAME          (optional) - Cloud Run service name (default: evalforge-deduplication)
#   SIMILARITY_THRESHOLD  (optional) - Deduplication threshold (default: 0.85)
#   DEDUP_BATCH_SIZE      (optional) - Patterns per run (default: 20)
#   DEDUP_SCHEDULE        (optional) - Cron schedule (default: */5 * * * * = every 5 min)
#   SKIP_SCHEDULER        (optional) - Set to 1 to skip Cloud Scheduler setup
#
# Exit codes:
#   0 - Success
#   1 - Missing requirements, build failure, or deployment error
# =============================================================================

set -euo pipefail  # Exit on error, undefined vars, and pipe failures

#=============================================================================
# Logging Helper Functions
#=============================================================================

log_info() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] $*" >&2
}

log_error() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" >&2
}

log_success() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [SUCCESS] $*" >&2
}

#=============================================================================
# Environment Variable Validation and Defaults
#=============================================================================

# Required: GCP Project ID
if [[ -z "${GCP_PROJECT_ID:-}" ]]; then
  log_error "GCP_PROJECT_ID environment variable is required"
  log_error "Usage: GCP_PROJECT_ID=your-project-id ./scripts/deploy_deduplication.sh"
  exit 1
fi

# Optional: Configurable deployment parameters with sensible defaults
GCP_REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-evalforge-deduplication}"
SIMILARITY_THRESHOLD="${SIMILARITY_THRESHOLD:-0.85}"
DEDUP_BATCH_SIZE="${DEDUP_BATCH_SIZE:-20}"
DEDUP_POLL_INTERVAL="${DEDUP_POLL_INTERVAL_SECONDS:-300}"
DEDUP_SCHEDULE="${DEDUP_SCHEDULE:-*/5 * * * *}"  # Every 5 minutes
SKIP_SCHEDULER="${SKIP_SCHEDULER:-0}"

# Derived values
SERVICE_ACCOUNT_NAME="evalforge-deduplication-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
IMAGE_NAME="gcr.io/${GCP_PROJECT_ID}/${SERVICE_NAME}:latest"

log_info "Starting deduplication service deployment"
log_info "Project: ${GCP_PROJECT_ID}"
log_info "Region: ${GCP_REGION}"
log_info "Service Name: ${SERVICE_NAME}"
log_info "Image: ${IMAGE_NAME}"
log_info "Similarity Threshold: ${SIMILARITY_THRESHOLD}"
log_info "Batch Size: ${DEDUP_BATCH_SIZE}"

#=============================================================================
# Create Service Account (Idempotent)
#=============================================================================

create_service_account() {
  log_info "Checking service account: ${SERVICE_ACCOUNT_NAME}..."

  if gcloud iam service-accounts describe "${SERVICE_ACCOUNT_EMAIL}" \
    --project="${GCP_PROJECT_ID}" &>/dev/null; then
    log_info "Service account already exists: ${SERVICE_ACCOUNT_NAME}"
  else
    log_info "Creating service account: ${SERVICE_ACCOUNT_NAME}..."
    gcloud iam service-accounts create "${SERVICE_ACCOUNT_NAME}" \
      --display-name="EvalForge Deduplication Service Account" \
      --description="Managed by evalforge automation - deduplication service" \
      --project="${GCP_PROJECT_ID}"
    log_info "Service account created: ${SERVICE_ACCOUNT_NAME}"
  fi
}

#=============================================================================
# Grant IAM Roles (Idempotent)
#=============================================================================

grant_iam_role() {
  local role="$1"
  log_info "Granting IAM role: ${role}..."

  gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="${role}" \
    --condition=None \
    --quiet &>/dev/null

  log_info "IAM role granted: ${role}"
}

setup_permissions() {
  log_info "Setting up IAM permissions..."

  # Firestore access for reading patterns and writing suggestions
  grant_iam_role "roles/datastore.user"

  # Vertex AI access for text embeddings
  grant_iam_role "roles/aiplatform.user"

  log_info "IAM permissions configured"
}

#=============================================================================
# Build Docker Image via Cloud Build
#=============================================================================

build_image() {
  log_info "Building Docker image via Cloud Build..."
  log_info "Using Dockerfile.deduplication..."

  # Create a temporary cloudbuild.yaml for the build
  local config_file
  config_file=$(mktemp)
  cat > "${config_file}" <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '${IMAGE_NAME}', '-f', 'Dockerfile.deduplication', '.']
images:
  - '${IMAGE_NAME}'
EOF

  # Submit build to Cloud Build using the deduplication Dockerfile
  if ! gcloud builds submit \
    --tag="${IMAGE_NAME}" \
    --project="${GCP_PROJECT_ID}" \
    --config="${config_file}" \
    --quiet \
    .; then
    log_error "Failed to build image with Cloud Build"
    log_error "Ensure Dockerfile.deduplication exists and Cloud Build API is enabled"
    rm -f "${config_file}"
    exit 1
  fi

  rm -f "${config_file}"
  log_info "Image built successfully: ${IMAGE_NAME}"
}

#=============================================================================
# Deploy to Cloud Run
#=============================================================================

deploy_cloud_run() {
  log_info "Deploying to Cloud Run service: ${SERVICE_NAME}..."

  gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE_NAME}" \
    --region="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --service-account="${SERVICE_ACCOUNT_EMAIL}" \
    --set-env-vars="\
GOOGLE_CLOUD_PROJECT=${GCP_PROJECT_ID},\
VERTEX_AI_PROJECT=${GCP_PROJECT_ID},\
VERTEX_AI_LOCATION=${GCP_REGION},\
FIRESTORE_COLLECTION_PREFIX=evalforge_,\
FIRESTORE_DATABASE_ID=evalforge,\
SIMILARITY_THRESHOLD=${SIMILARITY_THRESHOLD},\
EMBEDDING_MODEL=text-embedding-004,\
DEDUP_BATCH_SIZE=${DEDUP_BATCH_SIZE},\
DEDUP_POLL_INTERVAL_SECONDS=${DEDUP_POLL_INTERVAL}" \
    --memory=1Gi \
    --cpu=1 \
    --min-instances=0 \
    --max-instances=5 \
    --timeout=300s \
    --ingress=all \
    --no-allow-unauthenticated \
    --labels="managed-by=evalforge,service=deduplication" \
    --quiet || {
      log_error "Failed to deploy to Cloud Run"
      log_error "Ensure service account exists and has required permissions"
      exit 1
    }

  log_info "Cloud Run service deployed successfully"
}

#=============================================================================
# Get Service URL
#=============================================================================

get_service_url() {
  log_info "Retrieving Cloud Run service URL..."

  SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
    --region="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --format="value(status.url)" 2>/dev/null)

  if [[ -z "${SERVICE_URL}" ]]; then
    log_error "Failed to retrieve service URL"
    exit 1
  fi

  log_info "Service URL: ${SERVICE_URL}"
  echo "${SERVICE_URL}"
}

#=============================================================================
# Grant Cloud Run Invoker Role (for Cloud Scheduler)
#=============================================================================

grant_run_invoker() {
  log_info "Granting Cloud Run invoker role to service account..."

  gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --region="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/run.invoker" \
    --quiet &>/dev/null || {
      log_error "Failed to grant Cloud Run invoker role"
      exit 1
    }

  log_info "Cloud Run invoker role granted"
}

#=============================================================================
# Create or Update Cloud Scheduler Job (Idempotent)
#=============================================================================

create_or_update_scheduler_job() {
  local service_url="$1"
  local job_name="${SERVICE_NAME}-trigger"

  log_info "Setting up Cloud Scheduler job: ${job_name}..."

  # Check if job already exists
  if gcloud scheduler jobs describe "${job_name}" \
    --location="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --quiet &>/dev/null; then

    log_info "Scheduler job already exists, updating..."

    if gcloud scheduler jobs update http "${job_name}" \
      --location="${GCP_REGION}" \
      --project="${GCP_PROJECT_ID}" \
      --schedule="${DEDUP_SCHEDULE}" \
      --uri="${service_url}/dedup/run-once" \
      --http-method=POST \
      --headers="Content-Type=application/json" \
      --message-body="{\"batchSize\":${DEDUP_BATCH_SIZE},\"triggeredBy\":\"cloud-scheduler\"}" \
      --oidc-service-account-email="${SERVICE_ACCOUNT_EMAIL}" \
      --oidc-token-audience="${service_url}" \
      --time-zone="UTC" \
      --attempt-deadline=300s \
      --quiet 2>/dev/null; then
      log_info "Scheduler job updated successfully: ${job_name}"
      return 0
    else
      # Update failed, recreate
      log_info "Update failed, recreating job..."
      gcloud scheduler jobs pause "${job_name}" \
        --location="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --quiet &>/dev/null || true

      gcloud scheduler jobs delete "${job_name}" \
        --location="${GCP_REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --quiet || {
          log_error "Failed to delete existing scheduler job"
          exit 1
        }
    fi
  fi

  # Create new scheduler job
  log_info "Creating Cloud Scheduler job with schedule: ${DEDUP_SCHEDULE}..."
  gcloud scheduler jobs create http "${job_name}" \
    --location="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --schedule="${DEDUP_SCHEDULE}" \
    --uri="${service_url}/dedup/run-once" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body="{\"batchSize\":${DEDUP_BATCH_SIZE},\"triggeredBy\":\"cloud-scheduler\"}" \
    --oidc-service-account-email="${SERVICE_ACCOUNT_EMAIL}" \
    --oidc-token-audience="${service_url}" \
    --time-zone="UTC" \
    --attempt-deadline=300s \
    --quiet || {
      log_error "Failed to create scheduler job"
      exit 1
    }

  log_info "Cloud Scheduler job created successfully: ${job_name}"
}

#=============================================================================
# Main Execution Flow
#=============================================================================

main() {
  # Step 1: Create service account
  create_service_account

  # Step 2: Grant IAM permissions
  setup_permissions

  # Step 3: Build Docker image via Cloud Build
  build_image

  # Step 4: Deploy image to Cloud Run
  deploy_cloud_run

  # Step 5: Get the service URL
  SERVICE_URL=$(get_service_url)

  # Step 6-7: Setup Cloud Scheduler (unless skipped)
  if [[ "${SKIP_SCHEDULER}" != "1" ]]; then
    grant_run_invoker
    create_or_update_scheduler_job "${SERVICE_URL}"
  else
    log_info "Skipping Cloud Scheduler setup (SKIP_SCHEDULER=1)"
  fi

  # Success message
  log_success "Deployment complete!"
  echo ""
  echo "==================================================================="
  echo "  DEDUPLICATION SERVICE DEPLOYMENT SUMMARY"
  echo "==================================================================="
  echo "Service URL:     ${SERVICE_URL}"
  echo "Service Name:    ${SERVICE_NAME}"
  echo "Region:          ${GCP_REGION}"
  echo "Service Account: ${SERVICE_ACCOUNT_EMAIL}"
  if [[ "${SKIP_SCHEDULER}" != "1" ]]; then
    echo "Scheduler Job:   ${SERVICE_NAME}-trigger"
    echo "Schedule:        ${DEDUP_SCHEDULE} (UTC)"
  fi
  echo ""
  echo "Configuration:"
  echo "  Similarity Threshold: ${SIMILARITY_THRESHOLD}"
  echo "  Batch Size:           ${DEDUP_BATCH_SIZE}"
  echo "  Poll Interval:        ${DEDUP_POLL_INTERVAL}s"
  echo ""
  echo "==================================================================="
  echo "  NEXT STEPS"
  echo "==================================================================="
  echo ""
  echo "1. Verify deployment (health check):"
  echo "   curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
  echo "     ${SERVICE_URL}/health"
  echo ""
  echo "2. Trigger a manual deduplication run:"
  echo "   curl -X POST -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
  echo "     -H \"Content-Type: application/json\" \\"
  echo "     -d '{\"batchSize\": 10, \"triggeredBy\": \"manual\"}' \\"
  echo "     ${SERVICE_URL}/dedup/run-once"
  echo ""
  echo "3. View Cloud Run logs:"
  echo "   gcloud run services logs read ${SERVICE_NAME} \\"
  echo "     --region=${GCP_REGION} \\"
  echo "     --project=${GCP_PROJECT_ID} \\"
  echo "     --limit=50"
  echo ""
  if [[ "${SKIP_SCHEDULER}" != "1" ]]; then
    echo "4. Manually trigger scheduler job:"
    echo "   gcloud scheduler jobs run ${SERVICE_NAME}-trigger \\"
    echo "     --location=${GCP_REGION} \\"
    echo "     --project=${GCP_PROJECT_ID}"
    echo ""
  fi
  echo "==================================================================="
}

# Execute main function
main
