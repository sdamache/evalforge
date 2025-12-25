"""Gemini client wrapper using google-genai SDK.

Per research.md: Uses the new google-genai SDK (not deprecated vertexai.generative_models)
with response_mime_type="application/json" and response_schema to guarantee structured
JSON output from Gemini.

Includes retry logic with exponential backoff (3 retries) per constitution requirements.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.common.config import GeminiConfig
from src.extraction.models import get_failure_pattern_response_schema

logger = logging.getLogger(__name__)


class GeminiClientError(Exception):
    """Base exception for Gemini client errors."""

    pass


class GeminiAPIError(GeminiClientError):
    """Error from Gemini API call."""

    pass


class GeminiParseError(GeminiClientError):
    """Error parsing Gemini response."""

    pass


class GeminiTimeoutError(GeminiClientError):
    """Gemini call exceeded timeout."""

    pass


@dataclass
class GeminiResponse:
    """Structured response from Gemini extraction call."""

    raw_text: str
    parsed_json: Dict[str, Any]
    usage_metadata: Optional[Dict[str, Any]] = None


class GeminiClient:
    """Client for calling Gemini via google-genai SDK.

    Handles:
    - Structured JSON output via response_mime_type and response_schema
    - Retry with exponential backoff (3 retries per research.md)
    - Error classification for upstream handling
    """

    def __init__(self, config: GeminiConfig):
        """Initialize the Gemini client.

        Args:
            config: Gemini configuration with model, temperature, etc.
        """
        self.config = config
        self._client = None
        self._response_schema = get_failure_pattern_response_schema()

    def _get_client(self):
        """Lazy-load the google-genai client."""
        if self._client is None:
            try:
                from google import genai
                from google.genai.types import HttpOptions

                # Initialize client with Vertex AI backend
                self._client = genai.Client(
                    vertexai=True,
                    project=None,  # Uses GOOGLE_CLOUD_PROJECT from env
                    location=self.config.location,
                    http_options=HttpOptions(api_version="v1"),
                )
            except ImportError as e:
                raise GeminiClientError(
                    "google-genai package not installed. Run: pip install google-genai"
                ) from e
            except Exception as e:
                raise GeminiClientError(f"Failed to initialize Gemini client: {e}") from e

        return self._client

    @retry(
        retry=retry_if_exception_type(GeminiAPIError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def extract_pattern(self, prompt: str) -> GeminiResponse:
        """Call Gemini to extract a failure pattern from a trace.

        Args:
            prompt: The full extraction prompt including trace data.

        Returns:
            GeminiResponse with parsed JSON pattern data.

        Raises:
            GeminiAPIError: If the API call fails (will be retried).
            GeminiParseError: If the response cannot be parsed as JSON.
            GeminiClientError: For other client-side errors.
        """
        client = self._get_client()

        try:
            from google.genai import types

            # Build generation config with structured output
            config = types.GenerateContentConfig(
                temperature=self.config.temperature,
                max_output_tokens=self.config.max_output_tokens,
                response_mime_type="application/json",
                response_schema=self._response_schema,
            )

            # Make the API call
            response = client.models.generate_content(
                model=self.config.model,
                contents=prompt,
                config=config,
            )

            # Extract text from response
            if not response.text:
                raise GeminiParseError("Empty response from Gemini")

            raw_text = response.text

            # Parse the JSON response
            try:
                parsed_json = json.loads(raw_text)
            except json.JSONDecodeError as e:
                raise GeminiParseError(f"Invalid JSON in Gemini response: {e}") from e

            # Extract usage metadata if available
            usage_metadata = None
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage_metadata = {
                    "prompt_token_count": getattr(response.usage_metadata, "prompt_token_count", None),
                    "candidates_token_count": getattr(
                        response.usage_metadata, "candidates_token_count", None
                    ),
                    "total_token_count": getattr(response.usage_metadata, "total_token_count", None),
                }

            return GeminiResponse(
                raw_text=raw_text,
                parsed_json=parsed_json,
                usage_metadata=usage_metadata,
            )

        except GeminiParseError:
            raise
        except Exception as e:
            error_msg = str(e)

            # Check for rate limiting
            if "429" in error_msg or "rate limit" in error_msg.lower():
                logger.warning(f"Gemini rate limit hit, will retry: {error_msg}")
                raise GeminiAPIError(f"Rate limit exceeded: {error_msg}") from e

            # Check for transient errors
            if any(code in error_msg for code in ["500", "502", "503", "504"]):
                logger.warning(f"Gemini transient error, will retry: {error_msg}")
                raise GeminiAPIError(f"Transient error: {error_msg}") from e

            # Other errors - still wrap as GeminiAPIError to allow retry
            logger.error(f"Gemini API error: {error_msg}")
            raise GeminiAPIError(f"API error: {error_msg}") from e

    def get_model_info(self) -> Dict[str, Any]:
        """Return current model configuration for logging.

        Returns:
            Dict with model name, temperature, and other config.
        """
        return {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_output_tokens": self.config.max_output_tokens,
            "location": self.config.location,
        }


def create_gemini_client(config: GeminiConfig) -> GeminiClient:
    """Factory function to create a GeminiClient.

    Args:
        config: Gemini configuration.

    Returns:
        Configured GeminiClient instance.
    """
    return GeminiClient(config)
