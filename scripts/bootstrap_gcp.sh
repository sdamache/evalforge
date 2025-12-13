#!/bin/bash
# =============================================================================
# GCP Infrastructure Bootstrap Script for EvalForge
# =============================================================================
# Purpose: One-command setup of all GCP infrastructure required for EvalForge
#          ingestion service. This script is idempotent - safe to run multiple
#          times without causing errors or duplicate resources.
#
# What this script provisions:
#   1. Enables required GCP APIs (Firestore, Cloud Run, Secret Manager, etc.)
#   2. Creates Firestore database in native mode
#   3. Creates a dedicated service account with minimal permissions
#   4. Creates Secret Manager secrets for Datadog credentials (with placeholders)
#   5. Bootstraps Firestore collections via existing Python script
#
# Usage:
#   GCP_PROJECT_ID=your-project-id ./scripts/bootstrap_gcp.sh
#   GCP_PROJECT_ID=your-project-id GCP_REGION=us-east1 ./scripts/bootstrap_gcp.sh
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - GCP project with billing enabled
#   - Python 3.11+ (for Firestore collection bootstrap)
#
# Exit codes:
#   0 - Success
#   1 - Missing required environment variables or authentication
# =============================================================================

set -euo pipefail  # Exit on error, undefined vars, and pipe failures

#=============================================================================
# Logging Helper Functions
# Provides structured logging with timestamps for observability and debugging.
# All functions output to appropriate streams (stdout for info, stderr for errors).
#=============================================================================

log_info() {
  # Standard informational messages with ISO timestamp
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] $*"
}

log_error() {
  # Error messages directed to stderr for proper stream separation
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" >&2
}

log_success() {
  # Success messages for completed operations
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [SUCCESS] $*"
}

#=============================================================================
# Environment Variable Validation
# Fail fast if required configuration is missing. This prevents partial
# provisioning that would leave the project in an inconsistent state.
#=============================================================================

# Required: GCP Project ID - identifies which GCP project to provision
if [[ -z "${GCP_PROJECT_ID:-}" ]]; then
  log_error "GCP_PROJECT_ID environment variable is required"
  log_error "Usage: GCP_PROJECT_ID=your-project-id ./scripts/bootstrap_gcp.sh"
  exit 1
fi

# Optional: GCP Region (defaults to us-central1)
# This determines where Firestore and other regional resources are created
GCP_REGION="${GCP_REGION:-us-central1}"

# Configuration: Service account naming convention
# The SA is dedicated to the ingestion service with minimal required permissions
SERVICE_ACCOUNT_NAME="evalforge-ingestion-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

log_info "Starting GCP bootstrap for project: ${GCP_PROJECT_ID}"
log_info "Region: ${GCP_REGION}"

#=============================================================================
# gcloud Configuration and Authentication Check
# Ensures gcloud is properly configured before making any API calls.
# This prevents confusing errors from mismatched project contexts.
#=============================================================================

# Set the active project for all subsequent gcloud commands
log_info "Configuring gcloud to use project: ${GCP_PROJECT_ID}"
gcloud config set project "${GCP_PROJECT_ID}" --quiet

# Verify authentication: ensure user has logged in with gcloud auth login
# This check prevents cryptic API errors downstream
log_info "Verifying gcloud authentication..."
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
  log_error "No active gcloud authentication found"
  log_error "Please run: gcloud auth login"
  exit 1
fi

log_info "Authenticated as: $(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -n1)"

#=============================================================================
# API Enablement Function (Idempotent)
# Each GCP service requires its API to be enabled before use. This function
# checks first to provide clearer logging and avoid unnecessary API calls.
#=============================================================================

enable_api() {
  local api_name="$1"

  # Idempotency check: only enable if not already enabled
  # This provides better logging ("already enabled" vs "enabling") and
  # reduces API calls on subsequent runs
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
# These APIs must be enabled before their respective resources can be created.
# Order matters: some APIs depend on others (e.g., Cloud Run needs Firestore).
#=============================================================================

log_info "Enabling required GCP APIs..."
enable_api "run.googleapis.com"           # Cloud Run - hosts the ingestion service
enable_api "firestore.googleapis.com"     # Firestore - stores captured failure traces
enable_api "secretmanager.googleapis.com" # Secret Manager - stores Datadog credentials
enable_api "cloudscheduler.googleapis.com" # Cloud Scheduler - triggers periodic ingestion
enable_api "cloudbuild.googleapis.com"    # Cloud Build - builds Docker images remotely

#=============================================================================
# Firestore Database Creation (Idempotent)
# Creates the default Firestore database in native mode (not Datastore mode).
# Note: A GCP project can only have one default database, so this is truly
# idempotent - second runs will simply skip creation.
#=============================================================================

create_firestore_database() {
  log_info "Checking Firestore database..."

  # Check if Firestore database exists using the "(default)" database identifier
  # Note: GCP projects have a default database that cannot be deleted without
  # disabling the entire Firestore API
  if gcloud firestore databases describe --database="(default)" --project="${GCP_PROJECT_ID}" &>/dev/null; then
    log_info "Firestore database already exists"
  else
    log_info "Creating Firestore database in ${GCP_REGION}..."
    # Use native mode (not Datastore mode) for better Firestore features
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
# Creates a dedicated service account for the Cloud Run service.
# Using a dedicated SA (vs default compute SA) enables least-privilege:
# - Only the permissions needed for this specific service
# - Easier auditing of what this service can access
# - Can be scoped to specific secrets
#=============================================================================

create_service_account() {
  log_info "Checking service account: ${SERVICE_ACCOUNT_NAME}..."

  # Check if service account exists by attempting to describe it
  if gcloud iam service-accounts describe "${SERVICE_ACCOUNT_EMAIL}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
    log_info "Service account already exists: ${SERVICE_ACCOUNT_NAME}"
  else
    log_info "Creating service account: ${SERVICE_ACCOUNT_NAME}..."
    # Description marks this as automation-managed (since SA doesn't support labels)
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
# Grants minimal required permissions to the service account.
# Note: add-iam-policy-binding is naturally idempotent - adding an existing
# binding is a no-op that succeeds silently.
#=============================================================================

grant_iam_role() {
  local role="$1"

  log_info "Granting IAM role: ${role}..."

  # Grant role at project level (gcloud add-iam-policy-binding is idempotent)
  # --condition=None explicitly sets no IAM conditions
  # --quiet suppresses the policy output which can be verbose
  gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="${role}" \
    --condition=None \
    --quiet &>/dev/null

  log_info "IAM role granted: ${role}"
}

# Grant required roles - following least-privilege principle:
grant_iam_role "roles/datastore.user"              # Read/write Firestore documents
grant_iam_role "roles/secretmanager.secretAccessor" # Read secrets (Datadog API keys)

#=============================================================================
# Secret Manager Secret Creation (Idempotent)
# Creates secrets with placeholder values. The actual credentials must be
# added manually after bootstrap (for security - never commit real secrets).
# Labels are applied for resource management and future cleanup scripts.
#=============================================================================

create_secret() {
  local secret_name="$1"
  local placeholder_value="$2"

  log_info "Checking secret: ${secret_name}..."

  # Check if secret exists - if so, skip creation (don't overwrite)
  if gcloud secrets describe "${secret_name}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
    log_info "Secret already exists: ${secret_name}"
  else
    log_info "Creating secret: ${secret_name}..."

    # Create secret with automatic replication (GCP manages region distribution)
    # Label enables filtering: gcloud secrets list --filter="labels.managed-by=evalforge"
    gcloud secrets create "${secret_name}" \
      --replication-policy="automatic" \
      --labels="managed-by=evalforge" \
      --project="${GCP_PROJECT_ID}"

    # Add placeholder value as first version - user must update with real credentials
    # Using echo -n to avoid trailing newline in secret value
    echo -n "${placeholder_value}" | gcloud secrets versions add "${secret_name}" \
      --data-file=- \
      --project="${GCP_PROJECT_ID}"

    log_info "Secret created: ${secret_name}"
  fi
}

# Create secrets with placeholder values that MUST be replaced before deploy
# These store Datadog API credentials needed for trace ingestion
create_secret "datadog-api-key" "REPLACE_WITH_ACTUAL_API_KEY"
create_secret "datadog-app-key" "REPLACE_WITH_ACTUAL_APP_KEY"

#=============================================================================
# Grant Secret Access to Service Account (Idempotent)
# This grants secret-level IAM permissions (more granular than project-level).
# Only this specific service account can read these specific secrets.
#=============================================================================

grant_secret_access() {
  local secret_name="$1"

  log_info "Granting secret access for ${secret_name}..."

  # Grant secret-level access (more granular than project-level secretAccessor)
  # add-iam-policy-binding is idempotent - safe to run multiple times
  gcloud secrets add-iam-policy-binding "${secret_name}" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="${GCP_PROJECT_ID}" \
    --quiet &>/dev/null

  log_info "Secret access granted: ${secret_name}"
}

# Grant access to both Datadog credential secrets
grant_secret_access "datadog-api-key"
grant_secret_access "datadog-app-key"

#=============================================================================
# Bootstrap Firestore Collections
# Calls the existing Python script to create required collections.
# This ensures the service has the expected collection structure on first run.
#=============================================================================

log_info "Bootstrapping Firestore collections..."

# Set required environment variables for bootstrap_firestore.py
# These tell the Python script which project and collection prefix to use
export GOOGLE_CLOUD_PROJECT="${GCP_PROJECT_ID}"
export FIRESTORE_COLLECTION_PREFIX="evalforge_"

# Run the Python bootstrap script (handles its own idempotency)
# Try python3 first (macOS/Linux), fall back to python (Windows)
if command -v python3 &>/dev/null; then
  python3 scripts/bootstrap_firestore.py
elif command -v python &>/dev/null; then
  python scripts/bootstrap_firestore.py
else
  # Non-fatal: collections will be created on first write anyway
  log_error "Python not found. Please install Python 3.11+ to bootstrap Firestore collections"
  log_error "Skipping Firestore collection bootstrap..."
fi

#=============================================================================
# Success Message with Next Steps
# Provides clear guidance on what to do after bootstrap completes.
# The "next steps" pattern ensures users don't forget to update secrets.
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
