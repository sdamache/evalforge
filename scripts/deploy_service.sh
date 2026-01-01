#!/usr/bin/env bash
# =============================================================================
# Deploy EvalForge Service to Cloud Run (Unified Script)
# =============================================================================
# Purpose: Build and deploy any EvalForge service to Cloud Run.
#          Supports: extraction, deduplication, eval_tests, guardrails, runbooks
#
# Usage:
#   ./scripts/deploy_service.sh extraction
#   ./scripts/deploy_service.sh deduplication
#   ./scripts/deploy_service.sh eval_tests
#   ./scripts/deploy_service.sh guardrails
#   ./scripts/deploy_service.sh runbooks
#   ./scripts/deploy_service.sh all   # Deploy all services
#
# Environment variables:
#   GCP_PROJECT_ID     (optional) - defaults to konveyn2ai
#   GCP_REGION         (optional) - defaults to us-central1
# =============================================================================

set -eo pipefail

# Logging functions
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] $*" >&2; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" >&2; }
log_success() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [SUCCESS] $*" >&2; }

# Configuration
GCP_PROJECT_ID="${GCP_PROJECT_ID:-konveyn2ai}"
GCP_REGION="${GCP_REGION:-us-central1}"
SERVICE_ACCOUNT_NAME="evalforge-ingestion-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

# Service definitions: app_module|dockerfile|service_name
# For generators, we use Dockerfile.service with APP_MODULE build arg
get_service_config() {
  local service_key="$1"
  case "${service_key}" in
    extraction)
      echo "src.extraction.main:app|Dockerfile.extraction|evalforge-extraction"
      ;;
    deduplication)
      echo "src.deduplication.main:app|Dockerfile.deduplication|evalforge-deduplication"
      ;;
    eval_tests)
      echo "src.generators.eval_tests.main:app|Dockerfile.service|evalforge-eval-tests"
      ;;
    guardrails)
      echo "src.generators.guardrails.main:app|Dockerfile.service|evalforge-guardrails"
      ;;
    runbooks)
      echo "src.generators.runbooks.main:app|Dockerfile.service|evalforge-runbooks"
      ;;
    *)
      echo ""
      ;;
  esac
}

# Common environment variables for all services
COMMON_ENV_VARS="GOOGLE_CLOUD_PROJECT=${GCP_PROJECT_ID},FIRESTORE_COLLECTION_PREFIX=evalforge_,VERTEX_AI_LOCATION=${GCP_REGION}"

# Generator-specific environment variables
GENERATOR_ENV_VARS="${COMMON_ENV_VARS},GEMINI_MODEL=gemini-2.5-flash,GEMINI_TEMPERATURE=0.2,GEMINI_MAX_OUTPUT_TOKENS=2048"

deploy_service() {
  local service_key="$1"
  local config
  config=$(get_service_config "${service_key}")

  if [[ -z "${config}" ]]; then
    log_error "Unknown service: ${service_key}"
    log_error "Valid services: extraction deduplication eval_tests guardrails runbooks"
    return 1
  fi

  # Parse config: "app_module|dockerfile|service_name"
  IFS='|' read -r app_module dockerfile service_name <<< "${config}"

  local image_name="gcr.io/${GCP_PROJECT_ID}/${service_name}:latest"

  log_info "=== Deploying ${service_name} ==="
  log_info "App module: ${app_module}"
  log_info "Dockerfile: ${dockerfile}"
  log_info "Image: ${image_name}"

  # Determine environment variables based on service type
  local env_vars
  if [[ "${service_key}" == "extraction" ]] || [[ "${service_key}" == "deduplication" ]]; then
    env_vars="${COMMON_ENV_VARS}"
  else
    env_vars="${GENERATOR_ENV_VARS}"
  fi

  # Build image via Cloud Build
  log_info "Building Docker image via Cloud Build..."

  # Create temporary cloudbuild.yaml (required for custom Dockerfile names)
  local config_file
  config_file=$(mktemp)

  # For Dockerfile.service, we need to pass APP_MODULE as build arg
  if [[ "${dockerfile}" == "Dockerfile.service" ]]; then
    cat > "${config_file}" <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '${image_name}', '-f', '${dockerfile}', '--build-arg', 'APP_MODULE=${app_module}', '.']
images:
  - '${image_name}'
EOF
  else
    cat > "${config_file}" <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '${image_name}', '-f', '${dockerfile}', '.']
images:
  - '${image_name}'
EOF
  fi

  # Submit build to Cloud Build
  # Note: Use --config only (not --tag) when using custom cloudbuild.yaml
  if ! gcloud builds submit \
    --project="${GCP_PROJECT_ID}" \
    --config="${config_file}" \
    --quiet \
    .; then
    log_error "Failed to build ${service_name}"
    rm -f "${config_file}"
    return 1
  fi

  rm -f "${config_file}"
  log_info "Image built successfully: ${image_name}"

  # Deploy to Cloud Run
  log_info "Deploying to Cloud Run..."
  if ! gcloud run deploy "${service_name}" \
    --image="${image_name}" \
    --region="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --service-account="${SERVICE_ACCOUNT_EMAIL}" \
    --set-env-vars="${env_vars}" \
    --memory=512Mi \
    --cpu=1 \
    --min-instances=0 \
    --max-instances=10 \
    --ingress=internal-and-cloud-load-balancing \
    --no-allow-unauthenticated \
    --labels="managed-by=evalforge" \
    --quiet; then
    log_error "Failed to deploy ${service_name}"
    return 1
  fi

  # Get service URL
  local service_url
  service_url=$(gcloud run services describe "${service_name}" \
    --region="${GCP_REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --format="value(status.url)" 2>/dev/null)

  log_success "${service_name} deployed: ${service_url}"
  echo "${service_url}"
}

deploy_all() {
  log_info "Deploying all services..."
  local failed=()

  for service in extraction deduplication eval_tests guardrails runbooks; do
    log_info ""
    if ! deploy_service "${service}"; then
      failed+=("${service}")
    fi
  done

  echo ""
  echo "==================================================================="
  echo "  DEPLOYMENT SUMMARY"
  echo "==================================================================="

  if [[ ${#failed[@]} -eq 0 ]]; then
    log_success "All services deployed successfully!"
  else
    log_error "Failed services: ${failed[*]}"
    return 1
  fi
}

# Main
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <service|all>"
  echo "Services: extraction deduplication eval_tests guardrails runbooks all"
  exit 1
fi

case "$1" in
  all)
    deploy_all
    ;;
  extraction|deduplication|eval_tests|guardrails|runbooks)
    deploy_service "$1"
    ;;
  *)
    echo "Unknown service: $1"
    echo "Valid services: extraction deduplication eval_tests guardrails runbooks all"
    exit 1
    ;;
esac
