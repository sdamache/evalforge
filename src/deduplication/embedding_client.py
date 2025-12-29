"""Vertex AI embedding client for deduplication service.

Provides text embedding generation using Vertex AI's text-embedding-004 model
with batch support, in-memory caching, and exponential backoff retry logic.

Per research.md:
- Uses text-embedding-004 (768 dimensions, up to 5 texts per batch)
- Task type: SEMANTIC_SIMILARITY
- Rate limits: 600 RPM, 5 million tokens/minute
- Retry strategy: 3 attempts with exponential backoff (1s -> 2s -> 4s)
"""

from typing import Dict, List, Optional
import hashlib
import logging

import numpy as np
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from src.common.config import EmbeddingConfig, load_embedding_config

logger = logging.getLogger(__name__)


class EmbeddingServiceError(Exception):
    """Base exception for embedding service errors."""

    pass


class RateLimitError(EmbeddingServiceError):
    """Raised when Vertex AI returns a rate limit (429) error."""

    pass


class EmbeddingClient:
    """Client for generating text embeddings via Vertex AI.

    Provides:
    - Single text embedding generation
    - Batch embedding generation (up to 5 texts per API call)
    - In-memory cache to avoid redundant computation (FR-007)
    - Exponential backoff retry for rate limit handling (FR-017, FR-018)

    Usage:
        client = EmbeddingClient()
        embedding = client.get_embedding("hallucination: User asked for facts")
        embeddings = client.get_embeddings_batch(["text1", "text2", "text3"])
    """

    def __init__(
        self,
        config: Optional[EmbeddingConfig] = None,
        cache_enabled: bool = True,
    ):
        """Initialize the embedding client.

        Args:
            config: Optional EmbeddingConfig. If not provided, loads from environment.
            cache_enabled: Whether to enable in-memory caching (default: True).
        """
        self.config = config or load_embedding_config()
        self.cache_enabled = cache_enabled
        self._cache: Dict[str, List[float]] = {}
        self._model = None  # Lazy initialization

    def _get_model(self):
        """Lazy-load the Vertex AI embedding model.

        Initializes the Vertex AI SDK with project and location settings
        before loading the model for correct regional routing.

        Returns:
            TextEmbeddingModel instance.

        Raises:
            EmbeddingServiceError: If model initialization fails.
        """
        if self._model is None:
            try:
                import vertexai
                from vertexai.language_models import TextEmbeddingModel

                # Initialize Vertex AI with project and location for correct routing
                vertexai.init(
                    project=self.config.project,
                    location=self.config.location,
                )

                self._model = TextEmbeddingModel.from_pretrained(self.config.model)
                logger.info(
                    "Initialized embedding model",
                    extra={
                        "model": self.config.model,
                        "project": self.config.project,
                        "location": self.config.location,
                    },
                )
            except ImportError as e:
                raise EmbeddingServiceError(
                    "vertexai not installed. Run: pip install google-cloud-aiplatform"
                ) from e
            except Exception as e:
                raise EmbeddingServiceError(f"Failed to initialize embedding model: {e}") from e
        return self._model

    def _cache_key(self, text: str) -> str:
        """Generate a cache key for a text string.

        Uses SHA-256 hash to handle long texts efficiently.

        Args:
            text: Input text to hash.

        Returns:
            Hex digest of the text hash.
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _get_from_cache(self, text: str) -> Optional[List[float]]:
        """Retrieve embedding from cache if available.

        Args:
            text: Input text to look up.

        Returns:
            Cached embedding list or None if not in cache.
        """
        if not self.cache_enabled:
            return None
        key = self._cache_key(text)
        return self._cache.get(key)

    def _store_in_cache(self, text: str, embedding: List[float]) -> None:
        """Store embedding in cache.

        Args:
            text: Input text (used to generate cache key).
            embedding: Embedding vector to cache.
        """
        if self.cache_enabled:
            key = self._cache_key(text)
            self._cache[key] = embedding

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
    )
    def _call_embedding_api(self, texts: List[str]) -> List[List[float]]:
        """Call Vertex AI embedding API with retry logic.

        Args:
            texts: List of texts to embed (max 5 per call).

        Returns:
            List of embedding vectors.

        Raises:
            RateLimitError: If rate limited (triggers retry).
            EmbeddingServiceError: For other API errors.
        """
        model = self._get_model()

        try:
            from vertexai.language_models import TextEmbeddingInput

            # Create TextEmbeddingInput objects with task_type for each text
            inputs = [
                TextEmbeddingInput(text=t, task_type="SEMANTIC_SIMILARITY")
                for t in texts
            ]
            embeddings = model.get_embeddings(
                texts=inputs,
                output_dimensionality=self.config.output_dimensionality,
            )
            return [e.values for e in embeddings]
        except Exception as e:
            error_str = str(e).lower()
            if "429" in str(e) or "quota" in error_str or "rate" in error_str:
                logger.warning(
                    "Rate limit hit, will retry",
                    extra={"error": str(e), "texts_count": len(texts)},
                )
                raise RateLimitError(str(e)) from e
            raise EmbeddingServiceError(f"Embedding API error: {e}") from e

    def get_embedding(self, text: str) -> List[float]:
        """Get embedding for a single text.

        Checks cache first, then calls API if not cached.

        Args:
            text: Text to embed.

        Returns:
            768-dimensional embedding vector.

        Raises:
            EmbeddingServiceError: If embedding generation fails.
        """
        # Check cache first
        cached = self._get_from_cache(text)
        if cached is not None:
            logger.debug("Cache hit for embedding", extra={"text_length": len(text)})
            return cached

        # Call API
        embeddings = self._call_embedding_api([text])
        embedding = embeddings[0]

        # Cache result
        self._store_in_cache(text, embedding)

        return embedding

    def get_embeddings_batch(
        self,
        texts: List[str],
        batch_size: int = 5,
    ) -> List[List[float]]:
        """Get embeddings for multiple texts efficiently.

        Batches API calls (max 5 texts per call) and uses cache for duplicates.
        Maintains order of input texts in output.

        Args:
            texts: List of texts to embed.
            batch_size: Max texts per API call (default: 5, max allowed by API).

        Returns:
            List of embedding vectors in same order as input texts.

        Raises:
            EmbeddingServiceError: If embedding generation fails.
        """
        if not texts:
            return []

        # Clamp batch size to API limit
        batch_size = min(batch_size, 5)

        results: List[Optional[List[float]]] = [None] * len(texts)
        texts_to_fetch: List[tuple[int, str]] = []  # (index, text)

        # Check cache for each text
        for i, text in enumerate(texts):
            cached = self._get_from_cache(text)
            if cached is not None:
                results[i] = cached
            else:
                texts_to_fetch.append((i, text))

        # Fetch uncached texts in batches
        for batch_start in range(0, len(texts_to_fetch), batch_size):
            batch = texts_to_fetch[batch_start : batch_start + batch_size]
            batch_texts = [text for _, text in batch]

            embeddings = self._call_embedding_api(batch_texts)

            for (original_index, text), embedding in zip(batch, embeddings):
                results[original_index] = embedding
                self._store_in_cache(text, embedding)

        # Ensure all results are filled
        return [r for r in results if r is not None]

    def get_embedding_as_array(self, text: str) -> np.ndarray:
        """Get embedding as NumPy array for similarity computation.

        Convenience method that converts the embedding list to a NumPy array.

        Args:
            text: Text to embed.

        Returns:
            768-dimensional NumPy array.
        """
        embedding = self.get_embedding(text)
        return np.array(embedding, dtype=np.float32)

    def clear_cache(self) -> int:
        """Clear the in-memory embedding cache.

        Returns:
            Number of entries cleared.
        """
        count = len(self._cache)
        self._cache.clear()
        logger.info("Cleared embedding cache", extra={"entries_cleared": count})
        return count

    def cache_size(self) -> int:
        """Get current cache size.

        Returns:
            Number of cached embeddings.
        """
        return len(self._cache)

    def is_available(self) -> bool:
        """Check if embedding service is available.

        Attempts to load the model without making an API call.

        Returns:
            True if model can be initialized, False otherwise.
        """
        try:
            self._get_model()
            return True
        except Exception:
            return False
