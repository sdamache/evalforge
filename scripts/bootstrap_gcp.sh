#!/bin/bash
# GCP Infrastructure Bootstrap Script for EvalForge
# Purpose: One-command setup of all GCP infrastructure
# Usage: GCP_PROJECT_ID=your-project ./scripts/bootstrap_gcp.sh

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
# Environment Variable Validation
#=============================================================================

# Required: GCP Project ID
if [[ -z "${GCP_PROJECT_ID:-}" ]]; then
  log_error "GCP_PROJECT_ID environment variable is required"
  log_error "Usage: GCP_PROJECT_ID=your-project-id ./scripts/bootstrap_gcp.sh"
  exit 1
fi

# Optional: GCP Region (defaults to us-central1)
GCP_REGION="${GCP_REGION:-us-central1}"

# Configuration
SERVICE_ACCOUNT_NAME="evalforge-ingestion-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

log_info "Starting GCP bootstrap for project: ${GCP_PROJECT_ID}"
log_info "Region: ${GCP_REGION}"

#=============================================================================
# gcloud Configuration and Authentication Check
#=============================================================================

# Set the active project
log_info "Configuring gcloud to use project: ${GCP_PROJECT_ID}"
gcloud config set project "${GCP_PROJECT_ID}" --quiet

# Verify authentication
log_info "Verifying gcloud authentication..."
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
  log_error "No active gcloud authentication found"
  log_error "Please run: gcloud auth login"
  exit 1
fi

log_info "Authenticated as: $(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -n1)"

#=============================================================================
# API Enablement Function (Idempotent)
#=============================================================================

enable_api() {
  local api_name="$1"

  # Check if API is already enabled
  if gcloud services list --enabled --filter="name:${api_name}" --format="value(name)" | grep -q "${api_name}"; then
    log_info "API already enabled: ${api_name}"
  else
    log_info "Enabling API: ${api_name}..."
    gcloud services enable "${api_name}" --project="${GCP_PROJECT_ID}"
    log_info "API enabled: ${api_name}"
  fi
}

#=============================================================================
# Enable Required GCP APIs
#=============================================================================

log_info "Enabling required GCP APIs..."
enable_api "run.googleapis.com"
enable_api "firestore.googleapis.com"
enable_api "secretmanager.googleapis.com"
enable_api "cloudscheduler.googleapis.com"
enable_api "cloudbuild.googleapis.com"

#=============================================================================
# Firestore Database Creation (Idempotent)
#=============================================================================

create_firestore_database() {
  log_info "Checking Firestore database..."

  # Check if Firestore database exists
  if gcloud firestore databases describe --database="(default)" --project="${GCP_PROJECT_ID}" &>/dev/null; then
    log_info "Firestore database already exists"
  else
    log_info "Creating Firestore database in ${GCP_REGION}..."
    gcloud firestore databases create \
      --location="${GCP_REGION}" \
      --type=firestore-native \
      --project="${GCP_PROJECT_ID}"
    log_info "Firestore database created"
  fi
}

create_firestore_database

#=============================================================================
# Service Account Creation (Idempotent)
#=============================================================================

create_service_account() {
  log_info "Checking service account: ${SERVICE_ACCOUNT_NAME}..."

  # Check if service account exists
  if gcloud iam service-accounts describe "${SERVICE_ACCOUNT_EMAIL}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
    log_info "Service account already exists: ${SERVICE_ACCOUNT_NAME}"
  else
    log_info "Creating service account: ${SERVICE_ACCOUNT_NAME}..."
    gcloud iam service-accounts create "${SERVICE_ACCOUNT_NAME}" \
      --display-name="EvalForge Ingestion Service Account" \
      --description="Managed by evalforge automation" \
      --project="${GCP_PROJECT_ID}"
    log_info "Service account created: ${SERVICE_ACCOUNT_NAME}"
  fi
}

create_service_account

#=============================================================================
# IAM Role Binding (Idempotent)
#=============================================================================

grant_iam_role() {
  local role="$1"

  log_info "Granting IAM role: ${role}..."

  # Grant role (gcloud add-iam-policy-binding is idempotent)
  gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="${role}" \
    --condition=None \
    --quiet &>/dev/null

  log_info "IAM role granted: ${role}"
}

# Grant required roles
grant_iam_role "roles/datastore.user"
grant_iam_role "roles/secretmanager.secretAccessor"

#=============================================================================
# Secret Manager Secret Creation (Idempotent)
#=============================================================================

create_secret() {
  local secret_name="$1"
  local placeholder_value="$2"

  log_info "Checking secret: ${secret_name}..."

  # Check if secret exists
  if gcloud secrets describe "${secret_name}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
    log_info "Secret already exists: ${secret_name}"
  else
    log_info "Creating secret: ${secret_name}..."

    # Create secret with label
    gcloud secrets create "${secret_name}" \
      --replication-policy="automatic" \
      --labels="managed-by=evalforge" \
      --project="${GCP_PROJECT_ID}"

    # Add placeholder value as first version
    echo -n "${placeholder_value}" | gcloud secrets versions add "${secret_name}" \
      --data-file=- \
      --project="${GCP_PROJECT_ID}"

    log_info "Secret created: ${secret_name}"
  fi
}

# Create secrets with placeholder values
create_secret "datadog-api-key" "REPLACE_WITH_ACTUAL_API_KEY"
create_secret "datadog-app-key" "REPLACE_WITH_ACTUAL_APP_KEY"

#=============================================================================
# Grant Secret Access to Service Account (Idempotent)
#=============================================================================

grant_secret_access() {
  local secret_name="$1"

  log_info "Granting secret access for ${secret_name}..."

  # Grant access (gcloud secrets add-iam-policy-binding is idempotent)
  gcloud secrets add-iam-policy-binding "${secret_name}" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="${GCP_PROJECT_ID}" \
    --quiet &>/dev/null

  log_info "Secret access granted: ${secret_name}"
}

# Grant access to both secrets
grant_secret_access "datadog-api-key"
grant_secret_access "datadog-app-key"

#=============================================================================
# Bootstrap Firestore Collections
#=============================================================================

log_info "Bootstrapping Firestore collections..."

# Set required environment variables for bootstrap_firestore.py
export GOOGLE_CLOUD_PROJECT="${GCP_PROJECT_ID}"
export FIRESTORE_COLLECTION_PREFIX="evalforge_"

# Run the Python bootstrap script
if command -v python3 &>/dev/null; then
  python3 scripts/bootstrap_firestore.py
elif command -v python &>/dev/null; then
  python scripts/bootstrap_firestore.py
else
  log_error "Python not found. Please install Python 3.11+ to bootstrap Firestore collections"
  log_error "Skipping Firestore collection bootstrap..."
fi

#=============================================================================
# Success Message with Next Steps
#=============================================================================

log_success "Bootstrap complete!"
echo ""
echo "==============================================================================="
echo "                          BOOTSTRAP SUCCESSFUL                                  "
echo "==============================================================================="
echo ""
echo "Infrastructure provisioned in project: ${GCP_PROJECT_ID}"
echo ""
echo "✅ Enabled APIs:"
echo "   - Cloud Run"
echo "   - Firestore"
echo "   - Secret Manager"
echo "   - Cloud Scheduler"
echo "   - Cloud Build"
echo ""
echo "✅ Created Resources:"
echo "   - Firestore database (native mode) in ${GCP_REGION}"
echo "   - Service account: ${SERVICE_ACCOUNT_EMAIL}"
echo "   - Secrets: datadog-api-key, datadog-app-key (with placeholder values)"
echo "   - Firestore collections: evalforge_raw_traces, evalforge_exports"
echo ""
echo "==============================================================================="
echo "                              NEXT STEPS                                        "
echo "==============================================================================="
echo ""
echo "1. Update Datadog secrets with actual credentials:"
echo ""
echo "   Get your Datadog keys from:"
echo "   - API Key: https://app.datadoghq.com/organization-settings/api-keys"
echo "   - App Key: https://app.datadoghq.com/organization-settings/application-keys"
echo ""
echo "   Then run:"
echo "   echo -n 'your-actual-api-key' | gcloud secrets versions add datadog-api-key \\"
echo "     --data-file=- --project=${GCP_PROJECT_ID}"
echo ""
echo "   echo -n 'your-actual-app-key' | gcloud secrets versions add datadog-app-key \\"
echo "     --data-file=- --project=${GCP_PROJECT_ID}"
echo ""
echo "2. Deploy the service:"
echo "   ./scripts/deploy.sh"
echo ""
echo "==============================================================================="
