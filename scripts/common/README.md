# Common Environment Loading

This project provides consistent `.env` file loading for both Python and shell scripts.

## Quick Start

### Python

```python
# Option 1: Auto-load on import (recommended for scripts)
from src.common import env

# Option 2: Explicit load with options
from src.common.env import load_env
load_env(verbose=True)

# After loading, use standard os.getenv or common/config.py helpers
import os
project = os.getenv("GOOGLE_CLOUD_PROJECT")
```

### Shell (Bash)

```bash
#!/usr/bin/env bash

# Source the loader (auto-loads .env)
source "$(dirname "$0")/common/load_env.sh"

# Now all .env variables are available
echo "Project: $GOOGLE_CLOUD_PROJECT"
```

## How It Works

Both loaders:
1. Find `.env` file in project root (or current directory)
2. Load variables into environment
3. Preserve existing environment variables (shell takes precedence)
4. Fail gracefully if `.env` doesn't exist

## Python Module: `src/common/env.py`

Uses `python-dotenv` (industry standard).

```python
from src.common.env import load_env, require_env, get_env

# Load .env (auto-loads on import)
load_env()

# Get required variable (raises EnvironmentError if missing)
project_id = require_env("GOOGLE_CLOUD_PROJECT")

# Get optional variable with default
region = get_env("GOOGLE_CLOUD_LOCATION", "us-central1")
```

**Features:**
- Auto-loads on `from src.common import env`
- Searches project root for `.env`
- Shell environment takes precedence over `.env` values
- Validation helpers: `require_env()`, `get_env()`

## Shell Helper: `scripts/common/load_env.sh`

```bash
# Source to load .env automatically
source scripts/common/load_env.sh

# Validation helpers
require_env "GOOGLE_CLOUD_PROJECT" || exit 1
require_env_any "auth" "GOOGLE_APPLICATION_CREDENTIALS" "GOOGLE_CLOUD_PROJECT" || exit 1
```

**Features:**
- Auto-loads on source (unless `SKIP_AUTO_LOAD=true`)
- Graceful fallback if `.env` missing
- Validation: `require_env`, `require_env_any`
- Custom path: `LOAD_ENV_FILE=/path/to/.env source load_env.sh`

## Integration in Services

### FastAPI Entrypoints

```python
# src/extraction/main.py
from src.common import env  # Load .env first!
from src.common.config import load_extraction_settings

settings = load_extraction_settings()  # Now has access to .env vars
```

### Test Configuration

```python
# tests/conftest.py
from src.common.env import load_env
load_env()  # Load .env for test runs
```

## .env.example

All available environment variables are documented in `.env.example`. Copy it to `.env` and fill in your values:

```bash
cp .env.example .env
# Edit .env with your credentials
```

## Design Decisions

1. **Shell precedence**: Environment variables set in shell override `.env` values
2. **Graceful fallback**: Missing `.env` is not an error (enables cloud deployments)
3. **Single source of truth**: One `.env` file for Python, shell, and docker-compose
4. **Industry standard**: Uses `python-dotenv` (1B+ downloads/month)
