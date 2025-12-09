"""Configuration loader for ingestion services."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


def _get_env(key: str, default: Optional[str] = None, required: bool = False) -> str:
    value = os.getenv(key, default)
    if required and (value is None or value == ""):
        raise ConfigError(f"Missing required environment variable: {key}")
    if value is None:
        raise ConfigError(f"Environment variable {key} is not set and no default provided")
    if value == "" and default is None:
        raise ConfigError(f"Environment variable {key} is empty and no default provided")
    return value


def _int_env(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Invalid int for {key}: {raw}") from exc


def _float_env(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"Invalid float for {key}: {raw}") from exc


def _optional_env(key: str) -> Optional[str]:
    value = os.getenv(key)
    if value is None or value == "":
        return None
    return value


@dataclass
class DatadogConfig:
    api_key: str
    app_key: str
    site: str
    trace_lookback_hours: int
    quality_threshold: float
    rate_limit_max_sleep: int


@dataclass
class FirestoreConfig:
    collection_prefix: str
    project_id: Optional[str] = None
    database_id: str = "(default)"


@dataclass
class Settings:
    datadog: DatadogConfig
    firestore: FirestoreConfig


def load_settings() -> Settings:
    """Load settings from environment variables."""
    datadog = DatadogConfig(
        api_key=_get_env("DATADOG_API_KEY", required=True),
        app_key=_get_env("DATADOG_APP_KEY", required=True),
        site=_get_env("DATADOG_SITE", default="datadoghq.com"),
        trace_lookback_hours=_int_env("TRACE_LOOKBACK_HOURS", default=24),
        quality_threshold=_float_env("QUALITY_THRESHOLD", default=0.5),
        rate_limit_max_sleep=_int_env("DATADOG_RATE_LIMIT_MAX_SLEEP", default=10),
    )

    firestore = FirestoreConfig(
        collection_prefix=_get_env("FIRESTORE_COLLECTION_PREFIX", default="evalforge_"),
        project_id=_optional_env("GOOGLE_CLOUD_PROJECT"),
        database_id=_get_env("FIRESTORE_DATABASE_ID", default="(default)"),
    )

    return Settings(datadog=datadog, firestore=firestore)
