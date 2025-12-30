"""Configuration loader for Evalforge services.

Provides shared configuration dataclasses and environment variable helpers
used across ingestion, extraction, and API services.

All service configurations are centralized here to avoid duplication.

Exports:
    - ConfigError: Exception for configuration errors
    - _get_env, _int_env, _float_env, _optional_env: Environment helpers
    - DatadogConfig, FirestoreConfig, GeminiConfig: Service configurations
    - Settings: Combined settings for ingestion services
    - ExtractionSettings: Combined settings for extraction service
    - load_settings: Load ingestion settings from environment
    - load_extraction_settings: Load extraction settings from environment
    - load_firestore_config: Load just Firestore config
    - load_gemini_config: Load just Gemini config
"""

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
    """Firestore connection configuration used across all services."""

    collection_prefix: str
    project_id: Optional[str] = None
    database_id: str = "(default)"


@dataclass
class GeminiConfig:
    """Gemini model configuration for AI-powered extraction and generation.

    Used by extraction service and future generator services.
    """

    model: str
    temperature: float
    max_output_tokens: int
    location: str


# Default values for Gemini configuration
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_TEMPERATURE = 0.2
DEFAULT_GEMINI_MAX_OUTPUT_TOKENS = 4096
DEFAULT_VERTEX_AI_LOCATION = "us-central1"

# Default values for extraction service
DEFAULT_BATCH_SIZE = 50
DEFAULT_PER_TRACE_TIMEOUT_SEC = 10.0


@dataclass
class Settings:
    """Combined settings for ingestion service."""

    datadog: DatadogConfig
    firestore: FirestoreConfig


@dataclass
class ExtractionSettings:
    """Combined settings for extraction service.

    Includes Gemini config, Firestore config, and extraction-specific
    operational settings like batch size and timeout.
    """

    gemini: GeminiConfig
    firestore: FirestoreConfig
    batch_size: int
    per_trace_timeout_sec: float


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


def load_firestore_config() -> FirestoreConfig:
    """Load Firestore configuration from environment variables.

    Standalone loader for services that only need Firestore config
    (e.g., extraction service which doesn't need Datadog config).
    """
    return FirestoreConfig(
        collection_prefix=_get_env("FIRESTORE_COLLECTION_PREFIX", default="evalforge_"),
        project_id=_optional_env("GOOGLE_CLOUD_PROJECT"),
        database_id=_get_env("FIRESTORE_DATABASE_ID", default="(default)"),
    )


def load_gemini_config() -> GeminiConfig:
    """Load Gemini configuration from environment variables.

    Returns:
        GeminiConfig with model settings for Vertex AI Gemini.
    """
    return GeminiConfig(
        model=_get_env("GEMINI_MODEL", default=DEFAULT_GEMINI_MODEL),
        temperature=_float_env("GEMINI_TEMPERATURE", default=DEFAULT_GEMINI_TEMPERATURE),
        max_output_tokens=_int_env("GEMINI_MAX_OUTPUT_TOKENS", default=DEFAULT_GEMINI_MAX_OUTPUT_TOKENS),
        location=_get_env("VERTEX_AI_LOCATION", default=DEFAULT_VERTEX_AI_LOCATION),
    )


def load_extraction_settings() -> ExtractionSettings:
    """Load extraction service settings from environment variables.

    Returns:
        ExtractionSettings with Gemini, Firestore, and batch settings.

    Raises:
        ConfigError: If required environment variables are missing or invalid.
    """
    return ExtractionSettings(
        gemini=load_gemini_config(),
        firestore=load_firestore_config(),
        batch_size=_int_env("BATCH_SIZE", default=DEFAULT_BATCH_SIZE),
        per_trace_timeout_sec=_float_env("PER_TRACE_TIMEOUT_SEC", default=DEFAULT_PER_TRACE_TIMEOUT_SEC),
    )


# =============================================================================
# Deduplication Service Configuration
# =============================================================================

# Default values for deduplication service
DEFAULT_SIMILARITY_THRESHOLD = 0.85
DEFAULT_EMBEDDING_MODEL = "text-embedding-004"
DEFAULT_DEDUP_BATCH_SIZE = 20
DEFAULT_DEDUP_POLL_INTERVAL_SECONDS = 300  # 5 minutes between polling runs


@dataclass
class EmbeddingConfig:
    """Vertex AI embedding model configuration for deduplication service."""

    model: str
    project: str
    location: str
    output_dimensionality: int = 768


@dataclass
class DeduplicationSettings:
    """Combined settings for deduplication service.

    Includes embedding config, Firestore config, and deduplication-specific
    operational settings like similarity threshold, batch size, and polling interval.
    """

    embedding: EmbeddingConfig
    firestore: FirestoreConfig
    similarity_threshold: float
    batch_size: int
    poll_interval_seconds: int  # Interval between polling runs (FR-015)


def load_embedding_config() -> EmbeddingConfig:
    """Load embedding configuration from environment variables.

    Returns:
        EmbeddingConfig with Vertex AI embedding model settings.
    """
    return EmbeddingConfig(
        model=_get_env("EMBEDDING_MODEL", default=DEFAULT_EMBEDDING_MODEL),
        project=_get_env("VERTEX_AI_PROJECT", default=_get_env("GOOGLE_CLOUD_PROJECT", default="konveyn2ai")),
        location=_get_env("VERTEX_AI_LOCATION", default=DEFAULT_VERTEX_AI_LOCATION),
        output_dimensionality=_int_env("EMBEDDING_DIMENSIONALITY", default=768),
    )


def load_deduplication_settings() -> DeduplicationSettings:
    """Load deduplication service settings from environment variables.

    Returns:
        DeduplicationSettings with embedding, Firestore, and dedup settings.

    Raises:
        ConfigError: If required environment variables are missing or invalid.
    """
    return DeduplicationSettings(
        embedding=load_embedding_config(),
        firestore=load_firestore_config(),
        similarity_threshold=_float_env("SIMILARITY_THRESHOLD", default=DEFAULT_SIMILARITY_THRESHOLD),
        batch_size=_int_env("DEDUP_BATCH_SIZE", default=DEFAULT_DEDUP_BATCH_SIZE),
        poll_interval_seconds=_int_env("DEDUP_POLL_INTERVAL_SECONDS", default=DEFAULT_DEDUP_POLL_INTERVAL_SECONDS),
    )


# =============================================================================
# Eval Test Generator Configuration
# =============================================================================

DEFAULT_EVAL_TEST_BATCH_SIZE = 20
DEFAULT_EVAL_TEST_PER_SUGGESTION_TIMEOUT_SEC = 30.0
DEFAULT_EVAL_TEST_COST_BUDGET_USD_PER_SUGGESTION = 0.10


@dataclass
class EvalTestGeneratorSettings:
    """Combined settings for eval test draft generator service."""

    gemini: GeminiConfig
    firestore: FirestoreConfig
    batch_size: int
    per_suggestion_timeout_sec: float
    cost_budget_usd_per_suggestion: float
    run_cost_budget_usd: Optional[float]


def _optional_int_env(key: str) -> Optional[int]:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Invalid int for {key}: {raw}") from exc


def _optional_float_env(key: str) -> Optional[float]:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"Invalid float for {key}: {raw}") from exc


def load_eval_test_generator_settings() -> EvalTestGeneratorSettings:
    """Load eval test generator settings from environment variables."""
    gemini = load_gemini_config()
    override_max_tokens = _optional_int_env("EVAL_TEST_MAX_OUTPUT_TOKENS")
    if override_max_tokens is not None:
        gemini.max_output_tokens = override_max_tokens

    return EvalTestGeneratorSettings(
        gemini=gemini,
        firestore=load_firestore_config(),
        batch_size=_int_env("EVAL_TEST_BATCH_SIZE", default=DEFAULT_EVAL_TEST_BATCH_SIZE),
        per_suggestion_timeout_sec=_float_env(
            "EVAL_TEST_PER_SUGGESTION_TIMEOUT_SEC", default=DEFAULT_EVAL_TEST_PER_SUGGESTION_TIMEOUT_SEC
        ),
        cost_budget_usd_per_suggestion=_float_env(
            "EVAL_TEST_COST_BUDGET_USD_PER_SUGGESTION", default=DEFAULT_EVAL_TEST_COST_BUDGET_USD_PER_SUGGESTION
        ),
        run_cost_budget_usd=_optional_float_env("EVAL_TEST_RUN_COST_BUDGET_USD"),
    )


# =============================================================================
# Approval Workflow API Configuration
# =============================================================================


@dataclass
class ApprovalConfig:
    """Configuration for approval workflow API.

    Used by the approval workflow service for API key authentication
    and Slack webhook notifications.
    """

    api_key: Optional[str]
    slack_webhook_url: Optional[str]
    firestore: FirestoreConfig


def load_approval_config() -> ApprovalConfig:
    """Load approval workflow configuration from environment variables.

    Returns:
        ApprovalConfig with API key, webhook URL, and Firestore config.

    Note:
        api_key and slack_webhook_url are optional to allow running
        in development mode without full configuration.
    """
    return ApprovalConfig(
        api_key=_optional_env("APPROVAL_API_KEY"),
        slack_webhook_url=_optional_env("SLACK_WEBHOOK_URL"),
        firestore=load_firestore_config(),
    )
