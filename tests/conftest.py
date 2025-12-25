"""Pytest configuration and shared fixtures.

Automatically loads .env file for all tests, ensuring environment variables
are available for both unit tests (with mocks) and integration tests (with
real credentials).
"""

import sys
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# Load .env file before any tests run
# This makes environment variables available to all tests
from src.common.env import load_env

load_env(verbose=False)
