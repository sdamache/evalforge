#!/usr/bin/env bash
# =============================================================================
# Common Environment Loader
# =============================================================================
# Purpose: Load .env file into the shell environment for all scripts
#
# Usage:
#   source scripts/common/load_env.sh
#
# What it does:
#   1. Finds .env file in project root
#   2. Loads all variables into environment (export)
#   3. Provides validation helpers
#
# Exit codes:
#   0 - Success
#   1 - .env file not found or invalid
# =============================================================================

# Get script directory and project root
LOAD_ENV_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOAD_ENV_PROJECT_ROOT="$(cd "$LOAD_ENV_SCRIPT_DIR/../.." && pwd)"
LOAD_ENV_FILE="${LOAD_ENV_FILE:-${LOAD_ENV_PROJECT_ROOT}/.env}"

# =============================================================================
# Logging helpers
# =============================================================================

load_env_log_info() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] $*" >&2
}

load_env_log_error() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" >&2
}

load_env_log_warn() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN] $*" >&2
}

# =============================================================================
# Environment loading
# =============================================================================

load_dotenv() {
  local env_file="${1:-$LOAD_ENV_FILE}"

  if [[ ! -f "$env_file" ]]; then
    load_env_log_warn ".env file not found at: $env_file"
    load_env_log_warn "Using environment variables only. To use .env, create one from .env.example"
    return 0  # Not an error - can run with env vars only
  fi

  load_env_log_info "Loading environment from: $env_file"

  # Export all variables from .env (skip comments and empty lines)
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a

  load_env_log_info "Environment loaded successfully"
}

# =============================================================================
# Validation helpers
# =============================================================================

require_env() {
  local var_name="$1"
  local var_value="${!var_name}"

  if [[ -z "$var_value" ]]; then
    load_env_log_error "Required environment variable not set: $var_name"
    return 1
  fi

  return 0
}

require_env_any() {
  local description="$1"
  shift
  local var_names=("$@")

  for var_name in "${var_names[@]}"; do
    if [[ -n "${!var_name}" ]]; then
      return 0
    fi
  done

  load_env_log_error "At least one of these environment variables is required for $description: ${var_names[*]}"
  return 1
}

# =============================================================================
# Auto-load on source (unless SKIP_AUTO_LOAD is set)
# =============================================================================

if [[ "${SKIP_AUTO_LOAD:-}" != "true" ]]; then
  load_dotenv
fi
