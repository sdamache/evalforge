#!/usr/bin/env bash
# =============================================================================
# Deploy EvalForge API Service to Cloud Run
# =============================================================================
# Purpose: Build Docker image via Cloud Build and deploy the API service
#          (includes Capture Queue, Exports, and Approval Workflow endpoints)
#
# What this script does:
#   1. Builds Docker image using Cloud Build
#   2. Deploys image to Cloud Run with secrets and environment variables
#   3. Outputs the service URL for use in other services
#
# Prerequisites:
#   - Run bootstrap_gcp.sh first (creates service account, secrets, APIs)
#   - Datadog secrets configured in Secret Manager
#   - Dockerfile.api exists at repository root
#
# Usage:
#   GCP_PROJECT_ID=konveyn2ai ./scripts/deploy_api.sh
#
# Environment variables:
#   GCP_PROJECT_ID     (required) - Target GCP project
#   GCP_REGION         (optional) - Deployment region (default: us-central1)
#   SERVICE_NAME       (optional) - Cloud Run service name (default: evalforge-api)
#
# Exit codes:
#   0 - Success
#   1 - Missing requirements, build failure, or deployment error
# =============================================================================

set -euo pipefail

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

if [[ -z "${GCP_PROJECT_ID:-}" ]]; then
  log_error "GCP_PROJECT_ID environment variable is required"
  log_error "Usage: GCP_PROJECT_ID=konveyn2ai ./scripts/deploy_api.sh"
  exit 1
fi

# Optional: Configurable deployment parameters
GCP_REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-evalforge-api}"

# Derived values
SERVICE_ACCOUNT_NAME="evalforge-api-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
IMAGE_NAME="gcr.io/${GCP_PROJECT_ID}/${SERVICE_NAME}:latest"

log_info "Starting API service deployment"
log_info "Project: ${GCP_PROJECT_ID}"
log_info "Region: ${GCP_REGION}"
log_info "Service Name: ${SERVICE_NAME}"

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
      --display-name="EvalForge API Service Account" \
      --description="Managed by evalforge automation - API service" \
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

  # Firestore access for reading/writing suggestions
  grant_iam_role "roles/datastore.user"

  # Secret Manager access for API keys
  grant_iam_role "roles/secretmanager.secretAccessor"

  log_info "IAM permissions configured"
}

#=============================================================================
# Build Docker Image via Cloud Build
#=============================================================================

build_image() {
  log_info "Building Docker image via Cloud Build..."

  # Create a temporary cloudbuild.yaml to specify the Dockerfile
  cat > /tmp/cloudbuild-api.yaml <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '${IMAGE_NAME}', '-f', 'Dockerfile.api', '.']
images:
  - '${IMAGE_NAME}'
EOF

  gcloud builds submit \
    --project="${GCP_PROJECT_ID}" \
    --config=/tmp/cloudbuild-api.yaml \
    --quiet || {
      log_error "Failed to build Docker image"
      rm -f /tmp/cloudbuild-api.yaml
      exit 1
    }

  rm -f /tmp/cloudbuild-api.yaml
  log_info "Docker image built: ${IMAGE_NAME}"
}

#=============================================================================
# Deploy to Cloud Run
#=============================================================================

deploy_service() {
  log_info "Deploying to Cloud Run: ${SERVICE_NAME}..."

  gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE_NAME}" \
    --region="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --service-account="${SERVICE_ACCOUNT_EMAIL}" \
    --set-env-vars="\
GOOGLE_CLOUD_PROJECT=${GCP_PROJECT_ID},\
FIRESTORE_DATABASE_ID=evalforge,\
FIRESTORE_SUGGESTIONS_COLLECTION=evalforge_suggestions,\
ENVIRONMENT=production,\
SERVICE_NAME=evalforge-api" \
    --set-secrets="APPROVAL_API_KEY=APPROVAL_API_KEY:latest" \
    --memory=512Mi \
    --timeout=60s \
    --min-instances=0 \
    --max-instances=10 \
    --allow-unauthenticated \
    --quiet || {
      log_error "Failed to deploy to Cloud Run"
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
# Main Execution Flow
#=============================================================================

main() {
  # Step 1: Create service account
  create_service_account

  # Step 2: Grant IAM permissions
  setup_permissions

  # Step 3: Build Docker image
  build_image

  # Step 4: Deploy to Cloud Run
  deploy_service

  # Step 5: Get service URL
  SERVICE_URL=$(get_service_url)

  # Success message
  log_success "Deployment complete!"
  echo ""
  echo "==================================================================="
  echo "  API SERVICE DEPLOYMENT SUMMARY"
  echo "==================================================================="
  echo "Service URL:     ${SERVICE_URL}"
  echo "Service Name:    ${SERVICE_NAME}"
  echo "Region:          ${GCP_REGION}"
  echo "Service Account: ${SERVICE_ACCOUNT_EMAIL}"
  echo ""
  echo "==================================================================="
  echo "  ENDPOINTS"
  echo "==================================================================="
  echo ""
  echo "Health Check:"
  echo "  curl ${SERVICE_URL}/health"
  echo ""
  echo "Approval API:"
  echo "  curl ${SERVICE_URL}/approval/health"
  echo "  curl ${SERVICE_URL}/approval/suggestions?status=pending"
  echo "  curl -X POST ${SERVICE_URL}/approval/suggestions/{id}/approve"
  echo "  curl -X POST ${SERVICE_URL}/approval/suggestions/{id}/reject"
  echo ""
  echo "==================================================================="
  echo "  NEXT STEPS"
  echo "==================================================================="
  echo ""
  echo "1. Add to .env.local:"
  echo "   APPROVAL_API_URL=${SERVICE_URL}/approval"
  echo ""
  echo "2. Run smoke tests:"
  echo "   RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/smoke/ -v"
  echo ""
  echo "==================================================================="
}

# Execute main function
main
