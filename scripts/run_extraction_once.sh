#!/usr/bin/env bash
# =============================================================================
# Run Extraction Service Locally (One-Time Batch)
# =============================================================================
# Purpose: Developer helper script to run the extraction service locally
#          for testing and debugging. Triggers a single extraction run against
#          local or emulator Firestore.
#
# What this script does:
#   1. Activates Python virtual environment
#   2. Validates required environment variables
#   3. Runs extraction service with health check
#   4. Triggers a single extraction run via /extraction/run-once
#   5. Shows results and logs
#
# Prerequisites:
#   - Python venv activated or available at ./evalforge_venv
#   - .env file with credentials (or use Firestore emulator)
#   - Firestore with unprocessed traces in evalforge_raw_traces collection
#
# Usage:
#   # Use .env file
#   ./scripts/run_extraction_once.sh
#
#   # Use Firestore emulator
#   USE_EMULATOR=true ./scripts/run_extraction_once.sh
#
#   # Custom batch size
#   BATCH_SIZE=10 ./scripts/run_extraction_once.sh
#
# Environment variables:
#   USE_EMULATOR       (optional) - Use Firestore emulator (default: false)
#   BATCH_SIZE         (optional) - Number of traces to process (default: 5)
#   DRY_RUN            (optional) - Don't write results (default: false)
#   FIRESTORE_EMULATOR_HOST (optional) - Emulator host (default: localhost:8080)
#
# Exit codes:
#   0 - Success
#   1 - Missing requirements or execution error
# =============================================================================

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PATH="${PROJECT_ROOT}/evalforge_venv"

# Load environment variables from .env
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common/load_env.sh"

# Default values (can be overridden via .env or command line)
USE_EMULATOR="${USE_EMULATOR:-false}"
BATCH_SIZE="${BATCH_SIZE:-5}"
DRY_RUN="${DRY_RUN:-false}"
EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-localhost:8080}"
PORT="${PORT:-8080}"

# =============================================================================
# Logging
# =============================================================================

log_info() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] $*" >&2
}

log_error() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" >&2
}

log_success() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [SUCCESS] $*" >&2
}

# =============================================================================
# Prerequisites Check
# =============================================================================

check_prerequisites() {
  log_info "Checking prerequisites..."

  # Check if we're in project root
  if [[ ! -f "$PROJECT_ROOT/pyproject.toml" ]]; then
    log_error "Not in evalforge project root. Expected pyproject.toml"
    exit 1
  fi

  # Check Python venv
  if [[ ! -d "$VENV_PATH" ]]; then
    log_error "Virtual environment not found at $VENV_PATH"
    log_error "Run: python -m venv evalforge_venv && source evalforge_venv/bin/activate && pip install -e ."
    exit 1
  fi

  # Check if .env exists (unless using emulator)
  if [[ "$USE_EMULATOR" != "true" && ! -f "$PROJECT_ROOT/.env" ]]; then
    log_error ".env file not found. Copy .env.example and fill in credentials."
    log_error "Or use: USE_EMULATOR=true ./scripts/run_extraction_once.sh"
    exit 1
  fi

  log_success "Prerequisites validated"
}

# =============================================================================
# Environment Setup
# =============================================================================

setup_environment() {
  log_info "Setting up environment..."

  # Activate venv
  # shellcheck disable=SC1091
  source "$VENV_PATH/bin/activate"

  # Configure emulator if requested
  if [[ "$USE_EMULATOR" == "true" ]]; then
    log_info "Using Firestore emulator at $EMULATOR_HOST"
    export FIRESTORE_EMULATOR_HOST="$EMULATOR_HOST"
    export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-demo-project}"
  fi

  # Set PYTHONPATH
  export PYTHONPATH="$PROJECT_ROOT/src"

  log_success "Environment configured"
}

# =============================================================================
# Run Extraction
# =============================================================================

run_extraction_service() {
  log_info "Starting extraction service on port $PORT..."

  # Start service in background
  cd "$PROJECT_ROOT"
  python -m src.extraction.main --port "$PORT" &
  SERVICE_PID=$!

  # Wait for service to be ready
  log_info "Waiting for service to start (PID: $SERVICE_PID)..."
  for i in {1..30}; do
    if curl -s "http://localhost:$PORT/health" > /dev/null 2>&1; then
      log_success "Service is ready"
      return 0
    fi
    sleep 1
  done

  log_error "Service failed to start within 30 seconds"
  kill "$SERVICE_PID" 2>/dev/null || true
  exit 1
}

trigger_extraction_run() {
  log_info "Triggering extraction run..."
  log_info "Batch size: $BATCH_SIZE, Dry run: $DRY_RUN"

  # Build request body
  REQUEST_BODY=$(cat <<EOF
{
  "batchSize": $BATCH_SIZE,
  "dryRun": $DRY_RUN,
  "triggeredBy": "manual"
}
EOF
)

  # Make request
  RESPONSE=$(curl -s -X POST "http://localhost:$PORT/extraction/run-once" \
    -H "Content-Type: application/json" \
    -d "$REQUEST_BODY")

  # Display response
  echo "$RESPONSE" | python -m json.tool

  # Extract summary
  PICKED_UP=$(echo "$RESPONSE" | python -c "import sys, json; print(json.load(sys.stdin).get('pickedUpCount', 0))")
  STORED=$(echo "$RESPONSE" | python -c "import sys, json; print(json.load(sys.stdin).get('storedCount', 0))")
  ERRORS=$(echo "$RESPONSE" | python -c "import sys, json; print(json.load(sys.stdin).get('errorCount', 0))")

  log_success "Extraction run complete!"
  log_info "Summary: Picked up $PICKED_UP traces, stored $STORED patterns, $ERRORS errors"
}

cleanup() {
  log_info "Cleaning up..."
  if [[ -n "${SERVICE_PID:-}" ]]; then
    kill "$SERVICE_PID" 2>/dev/null || true
    log_info "Stopped extraction service"
  fi
}

# =============================================================================
# Main
# =============================================================================

main() {
  trap cleanup EXIT

  log_info "=== EvalForge Extraction - Local Run ==="
  log_info "Project root: $PROJECT_ROOT"

  check_prerequisites
  setup_environment
  run_extraction_service

  # Give service a moment to fully initialize
  sleep 2

  trigger_extraction_run

  log_success "=== Run complete! ==="
  log_info "Check logs above for details"

  # Keep service running briefly to show any async logs
  sleep 3
}

main "$@"
