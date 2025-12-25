"""Environment variable loading utilities.

Provides automatic .env file loading for Python applications using python-dotenv.
This module should be imported early in application startup to ensure environment
variables are available before other configuration modules load.

Usage in application entrypoints:

    # At the top of main.py, before other imports that need env vars:
    from src.common.env import load_env
    load_env()

    # Or auto-load on import:
    from src.common import env  # Loads .env automatically

Usage in tests:

    # In conftest.py:
    from src.common.env import load_env
    load_env()

The module searches for .env files in this order:
1. Current working directory
2. Project root (detected by pyproject.toml)
3. Parent directories up to filesystem root

Environment variables already set in the shell take precedence over .env values
(standard python-dotenv behavior with override=False).
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv as _load_dotenv

# Track if we've already loaded to avoid duplicate loads
_env_loaded = False


def find_project_root(start_path: Optional[Path] = None) -> Optional[Path]:
    """Find the project root by looking for pyproject.toml.

    Args:
        start_path: Starting directory for search. Defaults to current working directory.

    Returns:
        Path to project root, or None if not found.
    """
    current = start_path or Path.cwd()

    # Walk up to filesystem root
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
        if (parent / ".git").exists():
            return parent

    return None


def find_env_file(filename: str = ".env") -> Optional[Path]:
    """Find .env file in standard locations.

    Search order:
    1. Current working directory
    2. Project root (if detected)
    3. Already returns None if not found

    Args:
        filename: Name of the env file to find. Defaults to ".env".

    Returns:
        Path to .env file, or None if not found.
    """
    # Check current directory first
    cwd_env = Path.cwd() / filename
    if cwd_env.exists():
        return cwd_env

    # Check project root
    project_root = find_project_root()
    if project_root:
        root_env = project_root / filename
        if root_env.exists():
            return root_env

    return None


def load_env(
    env_file: Optional[str] = None,
    override: bool = False,
    verbose: bool = False,
) -> bool:
    """Load environment variables from .env file.

    Uses python-dotenv to load variables. By default, existing environment
    variables are NOT overwritten (shell env takes precedence).

    Args:
        env_file: Path to .env file. If None, searches standard locations.
        override: If True, .env values override existing environment variables.
        verbose: If True, print which file is being loaded.

    Returns:
        True if .env file was found and loaded, False otherwise.

    Example:
        # Load from default location
        load_env()

        # Load from specific file
        load_env("/path/to/.env.production")

        # Override existing variables
        load_env(override=True)
    """
    global _env_loaded

    # Find .env file
    if env_file:
        dotenv_path = Path(env_file)
    else:
        dotenv_path = find_env_file()

    if dotenv_path is None or not dotenv_path.exists():
        if verbose:
            print(f"[env] No .env file found, using environment variables only")
        return False

    if verbose:
        print(f"[env] Loading environment from: {dotenv_path}")

    # Load the .env file
    _load_dotenv(dotenv_path=dotenv_path, override=override)
    _env_loaded = True

    return True


def is_loaded() -> bool:
    """Check if .env has been loaded.

    Returns:
        True if load_env() has been called and found a .env file.
    """
    return _env_loaded


def require_env(var_name: str) -> str:
    """Get required environment variable or raise error.

    Args:
        var_name: Name of the environment variable.

    Returns:
        The value of the environment variable.

    Raises:
        EnvironmentError: If the variable is not set or empty.
    """
    value = os.getenv(var_name)
    if not value:
        raise EnvironmentError(f"Required environment variable not set: {var_name}")
    return value


def get_env(var_name: str, default: Optional[str] = None) -> Optional[str]:
    """Get environment variable with optional default.

    Args:
        var_name: Name of the environment variable.
        default: Default value if not set.

    Returns:
        The value of the environment variable, or default.
    """
    value = os.getenv(var_name)
    return value if value else default


# Auto-load on import (common pattern for convenience)
# This makes `from src.common import env` load the .env file automatically
load_env()
