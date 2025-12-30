"""Gemini client wrapper for runbook generation using google-genai SDK.

Uses response_mime_type="application/json" with response_schema to enforce
structured output for runbook drafts with SRE-standard format.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.common.config import GeminiConfig
from src.generators.runbooks.models import get_runbook_draft_response_schema


class GeminiClientError(Exception):
    """Base exception for Gemini client errors."""


class GeminiAPIError(GeminiClientError):
    """Error from Gemini API call."""


class GeminiRateLimitError(GeminiAPIError):
    """Rate limit or quota exceeded error from Gemini API.

    Callers should implement exponential backoff when catching this exception.
    """


class GeminiParseError(GeminiClientError):
    """Error parsing Gemini response."""


@dataclass
class GeminiResponse:
    """Structured response from Gemini generation call."""

    raw_text: str
    parsed_json: Dict[str, Any]
    prompt_hash: str
    response_sha256: str
    usage_metadata: Optional[Dict[str, Any]] = None


class GeminiClient:
    """Client for calling Gemini via google-genai SDK for runbook generation."""

    def __init__(self, config: GeminiConfig):
        self.config = config
        self._client = None
        self._response_schema = get_runbook_draft_response_schema()

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
                from google.genai.types import HttpOptions

                self._client = genai.Client(
                    vertexai=True,
                    project=None,  # Uses GOOGLE_CLOUD_PROJECT from env
                    location=self.config.location,
                    http_options=HttpOptions(api_version="v1"),
                )
            except ImportError as exc:
                raise GeminiClientError("google-genai package is required (pip install google-genai).") from exc
            except Exception as exc:
                raise GeminiClientError(f"Failed to initialize Gemini client: {exc}") from exc
        return self._client

    @retry(
        retry=retry_if_exception_type(GeminiAPIError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def generate_runbook_draft(self, prompt: str) -> GeminiResponse:
        """Generate a runbook draft using Gemini with structured output.

        Args:
            prompt: The generation prompt including failure context

        Returns:
            GeminiResponse with parsed JSON containing runbook fields

        Raises:
            GeminiRateLimitError: Rate limit exceeded (retry with backoff)
            GeminiAPIError: Transient API errors
            GeminiParseError: Invalid JSON in response
        """
        client = self._get_client()

        prompt_hash = f"sha256:{hashlib.sha256(prompt.encode('utf-8')).hexdigest()}"

        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                temperature=self.config.temperature,
                max_output_tokens=self.config.max_output_tokens,
                response_mime_type="application/json",
                response_schema=self._response_schema,
            )

            response = client.models.generate_content(
                model=self.config.model,
                contents=prompt,
                config=config,
            )

            if not response.text:
                raise GeminiParseError("Empty response from Gemini")

            raw_text = response.text
            response_sha256 = f"sha256:{hashlib.sha256(raw_text.encode('utf-8')).hexdigest()}"

            try:
                parsed_json = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise GeminiParseError(f"Invalid JSON in Gemini response: {exc}") from exc

            usage_metadata = None
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage_metadata = {
                    "prompt_token_count": getattr(response.usage_metadata, "prompt_token_count", None),
                    "candidates_token_count": getattr(response.usage_metadata, "candidates_token_count", None),
                    "total_token_count": getattr(response.usage_metadata, "total_token_count", None),
                }

            return GeminiResponse(
                raw_text=raw_text,
                parsed_json=parsed_json,
                prompt_hash=prompt_hash,
                response_sha256=response_sha256,
                usage_metadata=usage_metadata,
            )
        except GeminiParseError:
            raise
        except Exception as exc:
            error_msg = str(exc)

            if "429" in error_msg or "rate limit" in error_msg.lower() or "quota" in error_msg.lower():
                raise GeminiRateLimitError(f"Rate limit exceeded: {error_msg}") from exc

            if any(code in error_msg for code in ["500", "502", "503", "504"]):
                raise GeminiAPIError(f"Transient error: {error_msg}") from exc

            raise GeminiAPIError(f"API error: {error_msg}") from exc

    def get_model_info(self) -> Dict[str, Any]:
        """Return model configuration for health/debugging."""
        return {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_output_tokens": self.config.max_output_tokens,
            "location": self.config.location,
        }
