"""Cosine similarity computation for suggestion deduplication.

Implements efficient similarity calculation using NumPy for in-memory
comparison of embedding vectors. Sufficient for hackathon scale (~1000 suggestions).

Per research.md:
- Uses cosine similarity with 0.85 threshold
- Pre-normalization optimization available for batch comparisons
- O(n) comparison per new pattern is acceptable for batch processing
"""

from typing import List, Optional, Tuple

import numpy as np


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        vec_a: First embedding vector (768 dimensions).
        vec_b: Second embedding vector (768 dimensions).

    Returns:
        Cosine similarity score between 0.0 and 1.0.
        Returns 0.0 if either vector has zero magnitude.

    Example:
        >>> import numpy as np
        >>> a = np.array([1.0, 0.0, 0.0])
        >>> b = np.array([1.0, 0.0, 0.0])
        >>> cosine_similarity(a, b)
        1.0
    """
    dot_product = np.dot(vec_a, vec_b)
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(dot_product / (norm_a * norm_b))


def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    """Normalize an embedding vector to unit length.

    Pre-normalization optimization: When embeddings are normalized at storage time,
    cosine similarity becomes a simple dot product (faster for batch comparisons).

    Args:
        embedding: Raw embedding vector (768 dimensions).

    Returns:
        Unit-normalized embedding vector.
        Returns zero vector if input has zero magnitude.

    Example:
        >>> import numpy as np
        >>> vec = np.array([3.0, 4.0])
        >>> normalized = normalize_embedding(vec)
        >>> np.linalg.norm(normalized)
        1.0
    """
    norm = np.linalg.norm(embedding)
    if norm == 0:
        return embedding
    return embedding / norm


def find_best_match(
    new_embedding: np.ndarray,
    existing_embeddings: List[Tuple[str, np.ndarray]],
    threshold: float = 0.85,
) -> Optional[Tuple[str, float]]:
    """Find the best matching suggestion above the similarity threshold.

    Compares a new pattern's embedding against all existing suggestion embeddings
    and returns the suggestion with the highest similarity if it exceeds threshold.

    Args:
        new_embedding: Embedding vector for the new pattern (768 dimensions).
        existing_embeddings: List of (suggestion_id, embedding) tuples for comparison.
        threshold: Minimum similarity score for a match (default: 0.85).

    Returns:
        Tuple of (suggestion_id, similarity_score) for the best match,
        or None if no suggestion exceeds the threshold.

    Example:
        >>> import numpy as np
        >>> new_vec = np.array([1.0, 0.0, 0.0])
        >>> existing = [
        ...     ("sugg_1", np.array([0.9, 0.1, 0.0])),
        ...     ("sugg_2", np.array([0.0, 1.0, 0.0])),
        ... ]
        >>> result = find_best_match(new_vec, existing, threshold=0.8)
        >>> result[0] if result else None
        'sugg_1'
    """
    if not existing_embeddings:
        return None

    best_match: Optional[Tuple[str, float]] = None
    best_score = 0.0  # Track highest score seen

    for suggestion_id, embedding in existing_embeddings:
        score = cosine_similarity(new_embedding, embedding)
        # Score must be >= threshold (inclusive) AND better than current best
        if score >= threshold and score > best_score:
            best_score = score
            best_match = (suggestion_id, score)

    return best_match


def find_all_matches(
    new_embedding: np.ndarray,
    existing_embeddings: List[Tuple[str, np.ndarray]],
    threshold: float = 0.85,
) -> List[Tuple[str, float]]:
    """Find all suggestions matching above the similarity threshold.

    Useful for debugging and understanding why a pattern matched a specific
    suggestion when multiple candidates exist.

    Args:
        new_embedding: Embedding vector for the new pattern (768 dimensions).
        existing_embeddings: List of (suggestion_id, embedding) tuples.
        threshold: Minimum similarity score for inclusion (default: 0.85).

    Returns:
        List of (suggestion_id, similarity_score) tuples sorted by score descending.
        Empty list if no suggestions exceed the threshold.
    """
    if not existing_embeddings:
        return []

    matches = []
    for suggestion_id, embedding in existing_embeddings:
        score = cosine_similarity(new_embedding, embedding)
        if score >= threshold:
            matches.append((suggestion_id, score))

    # Sort by score descending
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches


def batch_cosine_similarity(
    query_embedding: np.ndarray,
    embeddings_matrix: np.ndarray,
) -> np.ndarray:
    """Compute cosine similarity between a query and multiple embeddings efficiently.

    Uses vectorized NumPy operations for performance when comparing against
    many embeddings at once.

    Args:
        query_embedding: Single embedding vector (768 dimensions).
        embeddings_matrix: Matrix of embeddings (N x 768).

    Returns:
        Array of N similarity scores.

    Note:
        For best performance, pre-normalize the embeddings_matrix rows.
        Then similarity is just: embeddings_matrix @ query_embedding
    """
    # Normalize query
    query_norm = np.linalg.norm(query_embedding)
    if query_norm == 0:
        return np.zeros(len(embeddings_matrix))
    normalized_query = query_embedding / query_norm

    # Normalize each row of the matrix
    row_norms = np.linalg.norm(embeddings_matrix, axis=1, keepdims=True)
    # Avoid division by zero
    row_norms = np.where(row_norms == 0, 1, row_norms)
    normalized_matrix = embeddings_matrix / row_norms

    # Dot product gives cosine similarity for normalized vectors
    return normalized_matrix @ normalized_query
