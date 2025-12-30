#!/usr/bin/env bash
# =============================================================================
# Deploy EvalForge Metrics Publisher to Cloud Functions
# =============================================================================
# Purpose: Deploy the Datadog metrics publisher Cloud Function with
#          Cloud Scheduler trigger for automatic 60-second execution.
#
# What this script does:
#   1. Creates service account with Firestore permissions
#   2. Creates Datadog API key secret in Secret Manager
#   3. Deploys Cloud Function with environment variables
#   4. Creates/updates Cloud Scheduler job for periodic execution
#
# Prerequisites:
#   - gcloud CLI authenticated (gcloud auth login)
#   - Cloud Functions, Cloud Scheduler, Secret Manager APIs enabled
#   - DATADOG_API_KEY set in environment or Secret Manager
#
# Usage:
#   GCP_PROJECT_ID=your-project-id DATADOG_API_KEY=your-key ./scripts/deploy_metrics_publisher.sh
#   GCP_PROJECT_ID=your-project SKIP_SCHEDULER=1 ./scripts/deploy_metrics_publisher.sh
#
# Environment variables:
#   GCP_PROJECT_ID   (required) - Target GCP project
#   DATADOG_API_KEY  (required) - Datadog API key (or use existing secret)
#   GCP_REGION       (optional) - Deployment region (default: us-central1)
#   DATADOG_SITE     (optional) - Datadog site (default: us5.datadoghq.com)
#   SCHEDULE         (optional) - Cron schedule (default: * * * * * = every minute)
#   SKIP_SCHEDULER   (optional) - Set to 1 to skip Cloud Scheduler setup
#
# Exit codes:
#   0 - Success
#   1 - Missing requirements or deployment error
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
  log_error "Usage: GCP_PROJECT_ID=your-project-id ./scripts/deploy_metrics_publisher.sh"
  exit 1
fi

# Optional: Configurable deployment parameters
GCP_REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-evalforge-metrics-publisher}"
DATADOG_SITE="${DATADOG_SITE:-us5.datadoghq.com}"
SCHEDULE="${SCHEDULE:-* * * * *}"  # Every minute
SKIP_SCHEDULER="${SKIP_SCHEDULER:-0}"

# Derived values
SERVICE_ACCOUNT_NAME="evalforge-metrics-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_JOB_NAME="${SERVICE_NAME}-trigger"

log_info "Starting metrics publisher deployment"
log_info "Project: ${GCP_PROJECT_ID}"
log_info "Region: ${GCP_REGION}"
log_info "Function Name: ${SERVICE_NAME}"
log_info "Datadog Site: ${DATADOG_SITE}"

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
      --display-name="EvalForge Metrics Publisher Service Account" \
      --description="Managed by evalforge automation - metrics publisher" \
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

  # Firestore access for reading suggestions
  grant_iam_role "roles/datastore.viewer"

  # Secret Manager access for Datadog API key
  grant_iam_role "roles/secretmanager.secretAccessor"

  log_info "IAM permissions configured"
}

#=============================================================================
# Setup Datadog API Key Secret
#=============================================================================

setup_datadog_secret() {
  local secret_name="DATADOG_API_KEY"

  log_info "Checking Datadog API key secret..."

  # Check if secret exists
  if gcloud secrets describe "${secret_name}" \
    --project="${GCP_PROJECT_ID}" &>/dev/null; then
    log_info "Secret already exists: ${secret_name}"
  else
    if [[ -z "${DATADOG_API_KEY:-}" ]]; then
      log_error "DATADOG_API_KEY environment variable required to create secret"
      log_error "Either set DATADOG_API_KEY or create the secret manually:"
      log_error "  echo -n 'your-key' | gcloud secrets create DATADOG_API_KEY --data-file=- --project=${GCP_PROJECT_ID}"
      exit 1
    fi

    log_info "Creating Datadog API key secret..."
    echo -n "${DATADOG_API_KEY}" | gcloud secrets create "${secret_name}" \
      --data-file=- \
      --project="${GCP_PROJECT_ID}" \
      --replication-policy="automatic"
    log_info "Secret created: ${secret_name}"
  fi
}

#=============================================================================
# Deploy Cloud Function
#=============================================================================

deploy_function() {
  log_info "Deploying Cloud Function: ${SERVICE_NAME}..."

  # Create requirements.txt for the function
  local temp_dir
  temp_dir=$(mktemp -d)

  # Copy source files preserving package structure
  # Create dashboard/ subdirectory to maintain import paths like 'from dashboard.config import ...'
  mkdir -p "${temp_dir}/dashboard"
  cp -r src/dashboard/* "${temp_dir}/dashboard/"
  # Move main.py to root (Cloud Functions expects entry point at root)
  mv "${temp_dir}/dashboard/metrics_publisher.py" "${temp_dir}/main.py"

  # Create requirements.txt
  cat > "${temp_dir}/requirements.txt" <<EOF
datadog-api-client>=2.0.0
functions-framework>=3.0.0
google-cloud-firestore>=2.0.0
flask>=2.0.0
EOF

  log_info "Deploying from temporary directory..."

  gcloud functions deploy "${SERVICE_NAME}" \
    --gen2 \
    --runtime=python311 \
    --region="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --source="${temp_dir}" \
    --entry-point=publish_metrics \
    --trigger-http \
    --service-account="${SERVICE_ACCOUNT_EMAIL}" \
    --set-env-vars="\
GOOGLE_CLOUD_PROJECT=${GCP_PROJECT_ID},\
FIRESTORE_DATABASE_ID=evalforge,\
FIRESTORE_SUGGESTIONS_COLLECTION=evalforge_suggestions,\
DATADOG_SITE=${DATADOG_SITE},\
ENVIRONMENT=production,\
SERVICE_NAME=evalforge" \
    --set-secrets="DATADOG_API_KEY=DATADOG_API_KEY:latest" \
    --memory=256Mi \
    --timeout=60s \
    --min-instances=0 \
    --max-instances=1 \
    --no-allow-unauthenticated \
    --quiet || {
      log_error "Failed to deploy Cloud Function"
      rm -rf "${temp_dir}"
      exit 1
    }

  rm -rf "${temp_dir}"
  log_info "Cloud Function deployed successfully"
}

#=============================================================================
# Get Function URL
#=============================================================================

get_function_url() {
  log_info "Retrieving Cloud Function URL..."

  FUNCTION_URL=$(gcloud functions describe "${SERVICE_NAME}" \
    --region="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --gen2 \
    --format="value(serviceConfig.uri)" 2>/dev/null)

  if [[ -z "${FUNCTION_URL}" ]]; then
    log_error "Failed to retrieve function URL"
    exit 1
  fi

  log_info "Function URL: ${FUNCTION_URL}"
  echo "${FUNCTION_URL}"
}

#=============================================================================
# Grant Cloud Functions Invoker Role (for Cloud Scheduler)
#=============================================================================

grant_invoker_role() {
  log_info "Granting Cloud Functions invoker role..."

  gcloud functions add-invoker-policy-binding "${SERVICE_NAME}" \
    --region="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --gen2 \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --quiet &>/dev/null || {
      log_error "Failed to grant invoker role"
      exit 1
    }

  log_info "Invoker role granted"
}

#=============================================================================
# Create or Update Cloud Scheduler Job
#=============================================================================

create_or_update_scheduler_job() {
  local function_url="$1"

  log_info "Setting up Cloud Scheduler job: ${SCHEDULER_JOB_NAME}..."

  # Check if job exists
  if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" \
    --location="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --quiet &>/dev/null; then

    log_info "Scheduler job exists, updating..."

    gcloud scheduler jobs update http "${SCHEDULER_JOB_NAME}" \
      --location="${GCP_REGION}" \
      --project="${GCP_PROJECT_ID}" \
      --schedule="${SCHEDULE}" \
      --uri="${function_url}" \
      --http-method=POST \
      --oidc-service-account-email="${SERVICE_ACCOUNT_EMAIL}" \
      --time-zone="UTC" \
      --attempt-deadline=60s \
      --quiet || {
        log_error "Failed to update scheduler job"
        exit 1
      }
  else
    log_info "Creating Cloud Scheduler job with schedule: ${SCHEDULE}..."

    gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
      --location="${GCP_REGION}" \
      --project="${GCP_PROJECT_ID}" \
      --schedule="${SCHEDULE}" \
      --uri="${function_url}" \
      --http-method=POST \
      --oidc-service-account-email="${SERVICE_ACCOUNT_EMAIL}" \
      --time-zone="UTC" \
      --attempt-deadline=60s \
      --quiet || {
        log_error "Failed to create scheduler job"
        exit 1
      }
  fi

  log_info "Cloud Scheduler job configured: ${SCHEDULER_JOB_NAME}"
}

#=============================================================================
# Main Execution Flow
#=============================================================================

main() {
  # Step 1: Create service account
  create_service_account

  # Step 2: Grant IAM permissions
  setup_permissions

  # Step 3: Setup Datadog API key secret
  setup_datadog_secret

  # Step 4: Deploy Cloud Function
  deploy_function

  # Step 5: Get function URL
  FUNCTION_URL=$(get_function_url)

  # Step 6-7: Setup Cloud Scheduler
  if [[ "${SKIP_SCHEDULER}" != "1" ]]; then
    grant_invoker_role
    create_or_update_scheduler_job "${FUNCTION_URL}"
  else
    log_info "Skipping Cloud Scheduler setup (SKIP_SCHEDULER=1)"
  fi

  # Success message
  log_success "Deployment complete!"
  echo ""
  echo "==================================================================="
  echo "  METRICS PUBLISHER DEPLOYMENT SUMMARY"
  echo "==================================================================="
  echo "Function URL:    ${FUNCTION_URL}"
  echo "Function Name:   ${SERVICE_NAME}"
  echo "Region:          ${GCP_REGION}"
  echo "Service Account: ${SERVICE_ACCOUNT_EMAIL}"
  echo "Datadog Site:    ${DATADOG_SITE}"
  if [[ "${SKIP_SCHEDULER}" != "1" ]]; then
    echo "Scheduler Job:   ${SCHEDULER_JOB_NAME}"
    echo "Schedule:        ${SCHEDULE} (UTC)"
  fi
  echo ""
  echo "==================================================================="
  echo "  NEXT STEPS"
  echo "==================================================================="
  echo ""
  echo "1. Test the function manually:"
  echo "   curl -X POST -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
  echo "     ${FUNCTION_URL}"
  echo ""
  echo "2. View function logs:"
  echo "   gcloud functions logs read ${SERVICE_NAME} \\"
  echo "     --region=${GCP_REGION} \\"
  echo "     --project=${GCP_PROJECT_ID} \\"
  echo "     --gen2 \\"
  echo "     --limit=50"
  echo ""
  if [[ "${SKIP_SCHEDULER}" != "1" ]]; then
    echo "3. Manually trigger scheduler job:"
    echo "   gcloud scheduler jobs run ${SCHEDULER_JOB_NAME} \\"
    echo "     --location=${GCP_REGION} \\"
    echo "     --project=${GCP_PROJECT_ID}"
    echo ""
  fi
  echo "4. Verify metrics in Datadog:"
  echo "   - Open Datadog Metrics Explorer"
  echo "   - Search for: evalforge.suggestions.*"
  echo ""
  echo "==================================================================="
}

# Execute main function
main
