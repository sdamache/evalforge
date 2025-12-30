"""Dashboard configuration for Datadog integration.

Provides configuration for the metrics publisher Cloud Function,
including Datadog API credentials and Firestore collection settings.
"""

from dataclasses import dataclass
from typing import Optional
import os


class DashboardConfigError(Exception):
    """Raised when required dashboard configuration is missing or invalid."""


def _get_env(key: str, default: Optional[str] = None, required: bool = False) -> str:
    """Get environment variable with optional default and required flag."""
    value = os.getenv(key, default)
    if required and (value is None or value == ""):
        raise DashboardConfigError(f"Missing required environment variable: {key}")
    if value is None:
        raise DashboardConfigError(f"Environment variable {key} is not set and no default provided")
    return value


def _optional_env(key: str) -> Optional[str]:
    """Get optional environment variable, returns None if not set."""
    value = os.getenv(key)
    if value is None or value == "":
        return None
    return value


@dataclass
class DashboardConfig:
    """Configuration for Datadog dashboard metrics publisher.

    Attributes:
        datadog_api_key: Datadog API key for metrics submission.
        datadog_app_key: Datadog Application key (optional for metrics).
        datadog_site: Datadog site (e.g., datadoghq.com, datadoghq.eu).
        firestore_project_id: GCP project ID for Firestore.
        firestore_database_id: Firestore database ID (e.g., evalforge).
        firestore_collection: Firestore collection name for suggestions.
        environment: Environment tag for metrics (e.g., production, staging).
        service_name: Service tag for metrics.
    """

    datadog_api_key: str
    datadog_site: str
    firestore_project_id: str
    firestore_database_id: str
    firestore_collection: str
    environment: str
    service_name: str
    datadog_app_key: Optional[str] = None

    @property
    def datadog_api_url(self) -> str:
        """Get the Datadog API URL based on site configuration."""
        site_to_url = {
            "datadoghq.com": "https://api.datadoghq.com",
            "us3.datadoghq.com": "https://api.us3.datadoghq.com",
            "us5.datadoghq.com": "https://api.us5.datadoghq.com",
            "datadoghq.eu": "https://api.datadoghq.eu",
            "ap1.datadoghq.com": "https://api.ap1.datadoghq.com",
        }
        return site_to_url.get(self.datadog_site, f"https://api.{self.datadog_site}")


def load_dashboard_config() -> DashboardConfig:
    """Load dashboard configuration from environment variables.

    Returns:
        DashboardConfig with Datadog and Firestore settings.

    Raises:
        DashboardConfigError: If required environment variables are missing.
    """
    return DashboardConfig(
        datadog_api_key=_get_env("DATADOG_API_KEY", required=True),
        datadog_app_key=_optional_env("DATADOG_APP_KEY"),
        datadog_site=_get_env("DATADOG_SITE", default="datadoghq.com"),
        firestore_project_id=_get_env("GOOGLE_CLOUD_PROJECT", default="konveyn2ai"),
        firestore_database_id=_get_env("FIRESTORE_DATABASE_ID", default="evalforge"),
        firestore_collection=_get_env("FIRESTORE_SUGGESTIONS_COLLECTION", default="evalforge_suggestions"),
        environment=_get_env("ENVIRONMENT", default="production"),
        service_name=_get_env("SERVICE_NAME", default="evalforge"),
    )
