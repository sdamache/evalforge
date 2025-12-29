# Research: Suggestion Storage and Deduplication

**Branch**: `003-suggestion-deduplication` | **Date**: 2025-12-28

## Research Tasks Completed

### 1. Vertex AI Text Embeddings

**Decision**: Use `text-embedding-004` model via Vertex AI Python SDK

**Rationale**:
- `text-embedding-004` provides 768 dimensions optimized for semantic similarity
- Vertex AI SDK provides simple interface: `TextEmbeddingModel.from_pretrained("text-embedding-004")`
- **Supports batch embedding** (up to 5 texts per request) - key advantage for hackathon throughput
- Rate limits: 600 RPM (established projects), **5 million tokens/minute**

**Model Comparison** (verified Dec 2025):
| Model | Dimensions | Batch Size | Status |
|-------|------------|------------|--------|
| `gemini-embedding-001` | 3072 (configurable to 768) | 1 text only | **Newest, best quality** |
| `text-embedding-004` | 768 | Up to 5 texts | **Recommended for batch processing** |
| `text-embedding-005` | 768 | Up to 5 texts | Available |

**Note**: `gemini-embedding-001` (May 2025) is now Google's recommended model with best-in-class performance, but it only processes 1 text per request. For hackathon batch processing, `text-embedding-004` is more practical.

**Alternatives Considered**:
- `gemini-embedding-001`: Better quality but no batch support (1 text per request)
- `textembedding-gecko@003`: Older model, lower quality for semantic tasks
- OpenAI embeddings: Not permitted per constitution (Vertex AI only)
- Sentence-transformers: Would require local GPU, not serverless-friendly

**Best Practices**:
```python
from vertexai.language_models import TextEmbeddingModel

model = TextEmbeddingModel.from_pretrained("text-embedding-004")

# Batch embedding (efficient)
embeddings = model.get_embeddings(
    texts=["text1", "text2", ...],
    task_type="SEMANTIC_SIMILARITY",  # Optimized for similarity
    output_dimensionality=768
)
```

### 2. Cosine Similarity for Text Deduplication

**Decision**: Use NumPy for cosine similarity computation (no external vector DB)

**Rationale**:
- For hackathon scale (1000 suggestions), in-memory comparison is sufficient
- NumPy is already a common dependency; no additional infrastructure
- O(n) comparison per new pattern is acceptable for batch processing

**Alternatives Considered**:
- Pinecone/Weaviate: Overkill for 1000 documents; adds operational complexity
- FAISS: Good but requires additional C++ dependencies
- Firestore vector search: Now available but requires different indexing strategy

**Implementation**:
```python
import numpy as np

def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot_product = np.dot(vec_a, vec_b)
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot_product / (norm_a * norm_b))

def find_best_match(
    new_embedding: np.ndarray,
    existing_embeddings: list[tuple[str, np.ndarray]],
    threshold: float = 0.85
) -> tuple[str, float] | None:
    """Find best matching suggestion above threshold."""
    best_match = None
    best_score = threshold

    for suggestion_id, embedding in existing_embeddings:
        score = cosine_similarity(new_embedding, embedding)
        if score > best_score:
            best_score = score
            best_match = (suggestion_id, score)

    return best_match
```

**Optimization Tip** (verified Dec 2025): Pre-normalize embeddings at storage time to convert cosine similarity to a simple dot product:
```python
# Normalize once when caching
normalized_embedding = embedding / np.linalg.norm(embedding)

# Then similarity becomes just a dot product (faster)
similarity = np.dot(normalized_vec_a, normalized_vec_b)
```

**Alternative**: For batch comparisons, `sklearn.metrics.pairwise.cosine_similarity` can be 10x faster than looping with NumPy.

### 3. Firestore Indexing for Efficient Queries

**Decision**: Create composite indexes for common query patterns

**Rationale**:
- Dashboard queries filter by status + type + created_at (sorting)
- Firestore requires composite indexes for multi-field queries
- Index on `(status, type, created_at)` covers most dashboard use cases

**Indexes Required**:
```yaml
# firestore.indexes.json
{
  "indexes": [
    {
      "collectionGroup": "evalforge_suggestions",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "status", "order": "ASCENDING"},
        {"fieldPath": "type", "order": "ASCENDING"},
        {"fieldPath": "created_at", "order": "DESCENDING"}
      ]
    },
    {
      "collectionGroup": "evalforge_suggestions",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "status", "order": "ASCENDING"},
        {"fieldPath": "severity", "order": "DESCENDING"}
      ]
    }
  ]
}
```

**Query Patterns**:
```python
# Pending suggestions by type, sorted by recency
db.collection("evalforge_suggestions") \
    .where("status", "==", "pending") \
    .where("type", "==", "eval") \
    .order_by("created_at", direction="DESCENDING") \
    .limit(50)

# Pending suggestions by severity (for prioritization)
db.collection("evalforge_suggestions") \
    .where("status", "==", "pending") \
    .order_by("severity", direction="DESCENDING") \
    .limit(50)
```

### 4. Existing Codebase Patterns

**Decision**: Follow established patterns from `src/extraction/` module

**Key Patterns to Reuse**:

1. **Models Structure** (from `extraction/models.py`):
   - Pydantic BaseModel for all data structures
   - Enums for controlled vocabularies (FailureType, Severity)
   - `to_dict()` method for Firestore serialization
   - Field validators for constraints

2. **Firestore Repository** (from `extraction/firestore_repository.py`):
   - Separate repository class for CRUD operations
   - Use `get_firestore_client()` from `common/firestore.py`
   - Standard collection naming: `evalforge_suggestions`

3. **Service Structure** (from `extraction/main.py`):
   - FastAPI app with `/health` endpoint
   - `/run-once` POST endpoint for batch processing
   - Structured response with run summary

4. **Error Handling** (from `common/config.py`):
   - Custom exception classes (e.g., `EmbeddingServiceError`)
   - Tenacity for retry logic with exponential backoff
   - Structured logging for all operations

### 5. Embedding Text Construction

**Decision**: Concatenate `failure_type` and `trigger_condition` for embedding input

**Rationale**:
- `failure_type` provides categorical signal (hallucination, toxicity, etc.)
- `trigger_condition` provides specific context for similarity matching
- Combined text gives best semantic representation for deduplication
- Aligns with spec assumption: "Embeddings are generated from the combination of failure type and trigger condition text"

**Format**:
```python
def build_embedding_text(pattern: FailurePattern) -> str:
    """Build text for embedding from failure pattern."""
    return f"{pattern.failure_type.value}: {pattern.trigger_condition}"

# Examples:
# "hallucination: User asks for product recommendation without specifying category"
# "stale_data: Agent recommended discontinued product SKU-9876"
```

### 6. Rate Limiting Strategy

**Decision**: Batch size of 20 patterns with exponential backoff

**Rationale** (verified Dec 2025):
- Vertex AI `text-embedding-004` allows up to 5 texts per API request
- We process 20 patterns per batch = ~4 embedding API calls per batch
- Conservative batch size provides safety margin for rate limits (600 RPM)
- Exponential backoff: 1s → 2s → 4s (max 3 retries) handles transient 429 errors
- Patterns that fail after 3 retries remain `processed=false` for next batch

**Implementation**:
```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class RateLimitError(Exception):
    pass

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(RateLimitError)
)
def get_embedding_with_retry(text: str) -> list[float]:
    try:
        return model.get_embeddings([text])[0].values
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            raise RateLimitError(str(e))
        raise
```

## Resolved NEEDS CLARIFICATION Items

All technical context items are resolved. No outstanding clarifications.

## Next Steps

Proceed to Phase 1: Design & Contracts
- Generate `data-model.md` with Suggestion, StatusHistoryEntry schemas
- Generate OpenAPI contract for deduplication service endpoints
- Generate `quickstart.md` for local development
