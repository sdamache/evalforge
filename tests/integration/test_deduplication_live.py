"""
Integration tests for suggestion deduplication with live Vertex AI and Firestore.

These tests verify that the deduplication service can:
1. Generate embeddings via Vertex AI text-embedding-004
2. Compute cosine similarity correctly
3. Create and merge suggestions in Firestore
4. Track lineage (source traces) correctly

Requirements:
- RUN_LIVE_TESTS=1 environment variable must be set
- Valid GOOGLE_CLOUD_PROJECT and credentials configured
- Vertex AI API enabled in the project
- Firestore access configured

Usage:
    # Run all deduplication integration tests
    RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_deduplication_live.py -v

    # Run specific test
    RUN_LIVE_TESTS=1 PYTHONPATH=src python -m pytest tests/integration/test_deduplication_live.py::test_embedding_generation -v
"""

import os
import time
import uuid
from datetime import datetime, UTC

import numpy as np
import pytest

from src.common.config import load_deduplication_settings, load_firestore_config
from src.common.firestore import get_firestore_client, suggestions_collection, failure_patterns_collection
from src.deduplication.embedding_client import EmbeddingClient
from src.deduplication.similarity import cosine_similarity, find_best_match
from src.deduplication.models import SuggestionStatus, SuggestionType
from src.deduplication.firestore_repository import SuggestionRepository
from src.extraction.models import (
    FailurePattern,
    FailureType,
    Severity,
    Evidence,
    ReproductionContext,
)


# Mark all tests in this module as integration tests requiring live API
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LIVE_TESTS"),
    reason="Live deduplication integration tests require RUN_LIVE_TESTS=1"
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def embedding_client():
    """Create embedding client with live credentials."""
    return EmbeddingClient(cache_enabled=True)


@pytest.fixture
def repository():
    """Create repository with live Firestore."""
    return SuggestionRepository()


@pytest.fixture
def test_prefix():
    """Generate unique prefix for test data isolation."""
    return f"test_{uuid.uuid4().hex[:8]}_"


@pytest.fixture
def cleanup_firestore(repository, test_prefix):
    """Cleanup test data after tests."""
    created_ids = []

    yield created_ids

    # Cleanup: Delete all test suggestions
    for suggestion_id in created_ids:
        try:
            repository.suggestions_ref.document(suggestion_id).delete()
        except Exception:
            pass


def _create_test_pattern(
    trace_id: str,
    failure_type: FailureType = FailureType.HALLUCINATION,
    trigger_condition: str = "User asked for product recommendation",
) -> FailurePattern:
    """Create a test FailurePattern for deduplication testing."""
    pattern_id = f"pattern_{trace_id}"
    return FailurePattern(
        pattern_id=pattern_id,
        source_trace_id=trace_id,
        title=f"Test Pattern {trace_id[-6:]}",
        failure_type=failure_type,
        trigger_condition=trigger_condition,
        summary="Test failure pattern for deduplication testing.",
        root_cause_hypothesis="Testing hypothesis",
        evidence=Evidence(signals=["test_signal_1", "test_signal_2"]),
        recommended_actions=["Fix the issue", "Add more tests"],
        reproduction_context=ReproductionContext(
            input_pattern="Test input pattern",
            required_state=None,
            tools_involved=["test_tool"],
        ),
        severity=Severity.MEDIUM,
        confidence=0.85,
        confidence_rationale="High confidence for testing",
        extracted_at=datetime.now(UTC),
    )


# ============================================================================
# User Story 1: Embedding and Similarity Tests
# ============================================================================


class TestEmbeddingGeneration:
    """Tests for Vertex AI embedding generation (T013 - US1)."""

    def test_single_embedding_generation(self, embedding_client):
        """Test that we can generate an embedding for a single text."""
        text = "hallucination: User asked for product recommendation without category"

        embedding = embedding_client.get_embedding(text)

        assert embedding is not None
        assert len(embedding) == 768, f"Expected 768 dimensions, got {len(embedding)}"
        assert all(isinstance(v, float) for v in embedding)
        print(f"Generated embedding with {len(embedding)} dimensions")

    def test_batch_embedding_generation(self, embedding_client):
        """Test batch embedding generation."""
        texts = [
            "hallucination: User asked for facts that don't exist",
            "stale_data: Recommended discontinued product",
            "wrong_tool: Used weather API for product search",
        ]

        embeddings = embedding_client.get_embeddings_batch(texts)

        assert len(embeddings) == 3
        assert all(len(e) == 768 for e in embeddings)
        print(f"Generated {len(embeddings)} embeddings in batch")

    def test_embedding_cache(self, embedding_client):
        """Test that cache prevents redundant API calls."""
        text = "test: Cache verification text"

        # First call - should hit API
        embedding1 = embedding_client.get_embedding(text)
        cache_size_after_first = embedding_client.cache_size()

        # Second call - should hit cache
        embedding2 = embedding_client.get_embedding(text)
        cache_size_after_second = embedding_client.cache_size()

        assert embedding1 == embedding2
        assert cache_size_after_first == cache_size_after_second == 1
        print("Cache correctly prevented redundant API call")


class TestSimilarityComputation:
    """Tests for cosine similarity computation."""

    def test_similar_texts_high_similarity(self, embedding_client):
        """Test that semantically similar texts have high similarity."""
        text1 = "hallucination: User asked for product recommendation without specifying category"
        text2 = "hallucination: User requested product suggestion without category specified"

        emb1 = embedding_client.get_embedding_as_array(text1)
        emb2 = embedding_client.get_embedding_as_array(text2)

        similarity = cosine_similarity(emb1, emb2)

        assert similarity > 0.85, f"Expected similarity > 0.85, got {similarity}"
        print(f"Similar texts have similarity: {similarity:.4f}")

    def test_different_texts_lower_similarity(self, embedding_client):
        """Test that semantically different texts have lower similarity."""
        text1 = "hallucination: Made up facts about product"
        text2 = "infrastructure_error: Database connection timeout"

        emb1 = embedding_client.get_embedding_as_array(text1)
        emb2 = embedding_client.get_embedding_as_array(text2)

        similarity = cosine_similarity(emb1, emb2)

        assert similarity < 0.85, f"Expected similarity < 0.85, got {similarity}"
        print(f"Different texts have similarity: {similarity:.4f}")

    def test_find_best_match_above_threshold(self, embedding_client):
        """Test find_best_match returns correct match."""
        query = "hallucination: Provided incorrect product details"
        candidates = [
            ("sugg_1", "hallucination: Made up product information"),
            ("sugg_2", "stale_data: Old product catalog used"),
            ("sugg_3", "wrong_tool: Used incorrect API endpoint"),
        ]

        query_emb = embedding_client.get_embedding_as_array(query)
        candidate_embs = [
            (id, embedding_client.get_embedding_as_array(text))
            for id, text in candidates
        ]

        result = find_best_match(query_emb, candidate_embs, threshold=0.7)

        assert result is not None, "Expected a match above threshold"
        assert result[0] == "sugg_1", f"Expected sugg_1, got {result[0]}"
        print(f"Best match: {result[0]} with score {result[1]:.4f}")


# ============================================================================
# User Story 1: Deduplication Integration Tests
# ============================================================================


class TestDeduplicationIntegration:
    """End-to-end tests for deduplication workflow (T013 - US1)."""

    def test_create_new_suggestion(self, repository, embedding_client, cleanup_firestore):
        """Test creating a new suggestion when no similar exists."""
        # Create unique test pattern
        trace_id = f"trace_test_{uuid.uuid4().hex[:8]}"
        pattern = _create_test_pattern(
            trace_id=trace_id,
            trigger_condition="Unique test condition that should not match anything",
        )

        # Generate embedding
        text = f"{pattern.failure_type.value}: {pattern.trigger_condition}"
        embedding = embedding_client.get_embedding(text)

        # Create suggestion
        suggestion = repository.create_suggestion(
            pattern=pattern,
            embedding=embedding,
            suggestion_type=SuggestionType.EVAL,
        )

        # Track for cleanup
        cleanup_firestore.append(suggestion.suggestion_id)

        # Verify
        assert suggestion.suggestion_id.startswith("sugg_")
        assert suggestion.status == SuggestionStatus.PENDING
        assert len(suggestion.source_traces) == 1
        assert suggestion.source_traces[0].trace_id == trace_id
        print(f"Created suggestion: {suggestion.suggestion_id}")

    def test_merge_similar_pattern(self, repository, embedding_client, cleanup_firestore):
        """Test merging a similar pattern into existing suggestion."""
        # Create first pattern and suggestion
        trace_id_1 = f"trace_test_{uuid.uuid4().hex[:8]}"
        pattern1 = _create_test_pattern(
            trace_id=trace_id_1,
            trigger_condition="User asked for restaurant recommendation without location",
        )

        text1 = f"{pattern1.failure_type.value}: {pattern1.trigger_condition}"
        embedding1 = embedding_client.get_embedding(text1)

        suggestion = repository.create_suggestion(
            pattern=pattern1,
            embedding=embedding1,
            suggestion_type=SuggestionType.EVAL,
        )
        cleanup_firestore.append(suggestion.suggestion_id)

        # Create similar second pattern
        trace_id_2 = f"trace_test_{uuid.uuid4().hex[:8]}"
        pattern2 = _create_test_pattern(
            trace_id=trace_id_2,
            trigger_condition="User requested restaurant suggestion without specifying location",
        )

        text2 = f"{pattern2.failure_type.value}: {pattern2.trigger_condition}"
        embedding2 = embedding_client.get_embedding_as_array(text2)

        # Check similarity
        existing_embeddings = [(suggestion.suggestion_id, np.array(embedding1))]
        match = find_best_match(embedding2, existing_embeddings, threshold=0.85)

        # Should find a match
        assert match is not None, "Expected patterns to be similar enough to merge"
        print(f"Similarity score: {match[1]:.4f}")

        # Merge
        updated = repository.merge_into_suggestion(
            suggestion_id=suggestion.suggestion_id,
            pattern=pattern2,
            similarity_score=match[1],
        )

        # Verify lineage
        assert len(updated.source_traces) == 2
        trace_ids = [st.trace_id for st in updated.source_traces]
        assert trace_id_1 in trace_ids
        assert trace_id_2 in trace_ids
        print(f"Merged pattern into suggestion, now has {len(updated.source_traces)} traces")

    def test_deduplication_reduces_suggestions(self, embedding_client):
        """Test that 10 similar patterns result in fewer suggestions (demonstration).

        This test demonstrates the core value proposition without actually
        writing to Firestore - it simulates the deduplication logic.
        """
        # Generate 10 similar failure pattern texts
        similar_texts = [
            "hallucination: User asked for product without category",
            "hallucination: User requested product recommendation without specifying type",
            "hallucination: Product suggestion requested without category information",
            "hallucination: User wanted product advice without category details",
            "hallucination: Asked for product without telling category",
            "hallucination: Product request missing category specification",
            "hallucination: User needs product recommendation, no category given",
            "hallucination: Seeking product without category context",
            "hallucination: Product query without category parameter",
            "hallucination: Wants product suggestion but no category provided",
        ]

        # Get embeddings for all
        embeddings = embedding_client.get_embeddings_batch(similar_texts)
        embeddings_np = [np.array(e) for e in embeddings]

        # Simulate deduplication: first becomes a "suggestion", rest get compared
        suggestions = [(0, embeddings_np[0])]  # (index, embedding)
        merged_count = 0
        new_count = 1  # First one is always new

        for i in range(1, len(embeddings_np)):
            match = find_best_match(
                embeddings_np[i],
                [(str(idx), emb) for idx, emb in suggestions],
                threshold=0.85,
            )

            if match:
                merged_count += 1
            else:
                suggestions.append((i, embeddings_np[i]))
                new_count += 1

        # Assert deduplication worked
        total_suggestions = new_count
        dedup_rate = merged_count / len(similar_texts)

        print(f"Input patterns: {len(similar_texts)}")
        print(f"Resulting suggestions: {total_suggestions}")
        print(f"Merged: {merged_count}, New: {new_count}")
        print(f"Deduplication rate: {dedup_rate:.1%}")

        # Should have significantly fewer suggestions than patterns
        assert total_suggestions <= 3, f"Expected <=3 suggestions, got {total_suggestions}"
        assert dedup_rate >= 0.7, f"Expected >=70% dedup rate, got {dedup_rate:.1%}"


# ============================================================================
# User Story 2: Lineage Tracking Tests (T024)
# ============================================================================


class TestLineageTracking:
    """Tests for suggestion lineage tracking (T024 - US2).

    Verifies that source_traces are populated correctly when:
    1. Creating a new suggestion from a pattern
    2. Merging additional patterns into existing suggestions
    3. Retrieving suggestions via API returns full lineage
    """

    def test_lineage_on_create(self, repository, embedding_client, cleanup_firestore):
        """Test that new suggestion has correct initial source trace."""
        trace_id = f"trace_lineage_{uuid.uuid4().hex[:8]}"
        pattern = _create_test_pattern(
            trace_id=trace_id,
            trigger_condition="Unique lineage test pattern",
        )

        text = f"{pattern.failure_type.value}: {pattern.trigger_condition}"
        embedding = embedding_client.get_embedding(text)

        suggestion = repository.create_suggestion(
            pattern=pattern,
            embedding=embedding,
            suggestion_type=SuggestionType.EVAL,
        )
        cleanup_firestore.append(suggestion.suggestion_id)

        # Verify lineage
        assert len(suggestion.source_traces) == 1
        first_trace = suggestion.source_traces[0]
        assert first_trace.trace_id == trace_id
        assert first_trace.pattern_id == pattern.pattern_id
        assert first_trace.similarity_score is None  # First trace has no score
        assert first_trace.added_at is not None
        print(f"Created suggestion with 1 source trace: {first_trace.trace_id}")

    def test_lineage_on_merge(self, repository, embedding_client, cleanup_firestore):
        """Test that merging adds to source_traces with correct metadata."""
        # Create initial suggestion
        trace_id_1 = f"trace_lineage_{uuid.uuid4().hex[:8]}"
        pattern1 = _create_test_pattern(
            trace_id=trace_id_1,
            trigger_condition="First lineage pattern for merge test",
        )

        text1 = f"{pattern1.failure_type.value}: {pattern1.trigger_condition}"
        embedding1 = embedding_client.get_embedding(text1)

        suggestion = repository.create_suggestion(
            pattern=pattern1,
            embedding=embedding1,
            suggestion_type=SuggestionType.EVAL,
        )
        cleanup_firestore.append(suggestion.suggestion_id)

        # Merge second pattern
        trace_id_2 = f"trace_lineage_{uuid.uuid4().hex[:8]}"
        pattern2 = _create_test_pattern(
            trace_id=trace_id_2,
            trigger_condition="Second lineage pattern for merge test",
        )

        similarity_score = 0.92
        updated = repository.merge_into_suggestion(
            suggestion_id=suggestion.suggestion_id,
            pattern=pattern2,
            similarity_score=similarity_score,
        )

        # Verify lineage now has 2 entries
        assert len(updated.source_traces) == 2

        # First trace
        first = updated.source_traces[0]
        assert first.trace_id == trace_id_1
        assert first.similarity_score is None

        # Second trace
        second = updated.source_traces[1]
        assert second.trace_id == trace_id_2
        assert second.similarity_score == similarity_score
        assert second.added_at > first.added_at

        print(f"Merged suggestion now has {len(updated.source_traces)} traces")

    def test_lineage_multiple_merges(self, repository, embedding_client, cleanup_firestore):
        """Test that multiple merges accumulate correctly."""
        # Create initial suggestion
        trace_ids = []
        trace_id_initial = f"trace_multi_{uuid.uuid4().hex[:8]}"
        trace_ids.append(trace_id_initial)

        pattern = _create_test_pattern(
            trace_id=trace_id_initial,
            trigger_condition="Initial pattern for multi-merge test",
        )

        text = f"{pattern.failure_type.value}: {pattern.trigger_condition}"
        embedding = embedding_client.get_embedding(text)

        suggestion = repository.create_suggestion(
            pattern=pattern,
            embedding=embedding,
            suggestion_type=SuggestionType.EVAL,
        )
        cleanup_firestore.append(suggestion.suggestion_id)

        # Merge 4 more patterns
        for i in range(4):
            trace_id = f"trace_multi_{uuid.uuid4().hex[:8]}"
            trace_ids.append(trace_id)

            merge_pattern = _create_test_pattern(
                trace_id=trace_id,
                trigger_condition=f"Merge pattern {i+1} for multi-merge test",
            )

            suggestion = repository.merge_into_suggestion(
                suggestion_id=suggestion.suggestion_id,
                pattern=merge_pattern,
                similarity_score=0.90 + (i * 0.01),
            )

        # Verify all 5 traces are present
        assert len(suggestion.source_traces) == 5

        # Verify all trace IDs are captured
        captured_trace_ids = [st.trace_id for st in suggestion.source_traces]
        for tid in trace_ids:
            assert tid in captured_trace_ids

        print(f"Multi-merge test: {len(suggestion.source_traces)} traces accumulated")


# ============================================================================
# User Story 3: Audit Trail Tests (T029)
# ============================================================================


class TestAuditTrail:
    """Tests for suggestion audit trail (T029 - US3).

    Verifies that version_history is populated correctly when:
    1. Suggestion is created (initial status entry)
    2. Status is changed (approval/rejection)
    3. Multiple status changes are recorded (if re-transitioned - though not allowed)
    """

    def test_initial_version_history(self, repository, embedding_client, cleanup_firestore):
        """Test that new suggestion has initial version_history entry."""
        trace_id = f"trace_audit_{uuid.uuid4().hex[:8]}"
        pattern = _create_test_pattern(
            trace_id=trace_id,
            trigger_condition="Audit test pattern - initial",
        )

        text = f"{pattern.failure_type.value}: {pattern.trigger_condition}"
        embedding = embedding_client.get_embedding(text)

        suggestion = repository.create_suggestion(
            pattern=pattern,
            embedding=embedding,
            suggestion_type=SuggestionType.EVAL,
        )
        cleanup_firestore.append(suggestion.suggestion_id)

        # Verify initial version history
        assert len(suggestion.version_history) == 1
        initial_entry = suggestion.version_history[0]
        assert initial_entry.previous_status is None  # First entry has no previous
        assert initial_entry.new_status == SuggestionStatus.PENDING
        assert initial_entry.actor == "system"
        assert initial_entry.timestamp is not None
        print(f"Initial version history entry: {initial_entry.new_status.value}")

    def test_approval_adds_to_history(self, repository, embedding_client, cleanup_firestore):
        """Test that approving a suggestion adds to version_history."""
        trace_id = f"trace_audit_{uuid.uuid4().hex[:8]}"
        pattern = _create_test_pattern(
            trace_id=trace_id,
            trigger_condition="Audit test pattern - approval",
        )

        text = f"{pattern.failure_type.value}: {pattern.trigger_condition}"
        embedding = embedding_client.get_embedding(text)

        suggestion = repository.create_suggestion(
            pattern=pattern,
            embedding=embedding,
            suggestion_type=SuggestionType.EVAL,
        )
        cleanup_firestore.append(suggestion.suggestion_id)

        # Approve the suggestion
        updated, history_entry = repository.update_suggestion_status(
            suggestion_id=suggestion.suggestion_id,
            new_status=SuggestionStatus.APPROVED,
            actor="test@example.com",
            notes="Approved for production use",
        )

        # Verify version history now has 2 entries
        assert len(updated.version_history) == 2

        # Verify the approval entry
        assert history_entry.previous_status == SuggestionStatus.PENDING
        assert history_entry.new_status == SuggestionStatus.APPROVED
        assert history_entry.actor == "test@example.com"
        assert history_entry.notes == "Approved for production use"
        assert history_entry.timestamp > updated.version_history[0].timestamp

        # Verify suggestion status changed
        assert updated.status == SuggestionStatus.APPROVED
        print(f"Version history after approval: {len(updated.version_history)} entries")

    def test_rejection_adds_to_history(self, repository, embedding_client, cleanup_firestore):
        """Test that rejecting a suggestion adds to version_history."""
        trace_id = f"trace_audit_{uuid.uuid4().hex[:8]}"
        pattern = _create_test_pattern(
            trace_id=trace_id,
            trigger_condition="Audit test pattern - rejection",
        )

        text = f"{pattern.failure_type.value}: {pattern.trigger_condition}"
        embedding = embedding_client.get_embedding(text)

        suggestion = repository.create_suggestion(
            pattern=pattern,
            embedding=embedding,
            suggestion_type=SuggestionType.EVAL,
        )
        cleanup_firestore.append(suggestion.suggestion_id)

        # Reject the suggestion
        updated, history_entry = repository.update_suggestion_status(
            suggestion_id=suggestion.suggestion_id,
            new_status=SuggestionStatus.REJECTED,
            actor="reviewer@example.com",
            notes="Not reproducible - edge case",
        )

        # Verify version history
        assert len(updated.version_history) == 2
        assert history_entry.new_status == SuggestionStatus.REJECTED
        assert updated.status == SuggestionStatus.REJECTED
        print(f"Rejection recorded with notes: {history_entry.notes}")

    def test_approval_metadata_set(self, repository, embedding_client, cleanup_firestore):
        """Test that approval_metadata is set on status change."""
        trace_id = f"trace_audit_{uuid.uuid4().hex[:8]}"
        pattern = _create_test_pattern(
            trace_id=trace_id,
            trigger_condition="Audit test pattern - metadata",
        )

        text = f"{pattern.failure_type.value}: {pattern.trigger_condition}"
        embedding = embedding_client.get_embedding(text)

        suggestion = repository.create_suggestion(
            pattern=pattern,
            embedding=embedding,
            suggestion_type=SuggestionType.EVAL,
        )
        cleanup_firestore.append(suggestion.suggestion_id)

        # Initially no approval metadata
        assert suggestion.approval_metadata is None

        # Approve
        updated, _ = repository.update_suggestion_status(
            suggestion_id=suggestion.suggestion_id,
            new_status=SuggestionStatus.APPROVED,
            actor="approver@example.com",
            notes="LGTM",
        )

        # Verify approval metadata
        assert updated.approval_metadata is not None
        assert updated.approval_metadata.actor == "approver@example.com"
        assert updated.approval_metadata.action == "approved"
        assert updated.approval_metadata.notes == "LGTM"
        print(f"Approval metadata set: actor={updated.approval_metadata.actor}")

    def test_cannot_change_approved_status(self, repository, embedding_client, cleanup_firestore):
        """Test that approved suggestions cannot be changed (terminal state)."""
        from src.deduplication.firestore_repository import SuggestionRepositoryError

        trace_id = f"trace_audit_{uuid.uuid4().hex[:8]}"
        pattern = _create_test_pattern(
            trace_id=trace_id,
            trigger_condition="Audit test pattern - terminal",
        )

        text = f"{pattern.failure_type.value}: {pattern.trigger_condition}"
        embedding = embedding_client.get_embedding(text)

        suggestion = repository.create_suggestion(
            pattern=pattern,
            embedding=embedding,
            suggestion_type=SuggestionType.EVAL,
        )
        cleanup_firestore.append(suggestion.suggestion_id)

        # First approve
        repository.update_suggestion_status(
            suggestion_id=suggestion.suggestion_id,
            new_status=SuggestionStatus.APPROVED,
            actor="approver@example.com",
        )

        # Try to reject after approval (should fail)
        try:
            repository.update_suggestion_status(
                suggestion_id=suggestion.suggestion_id,
                new_status=SuggestionStatus.REJECTED,
                actor="another@example.com",
            )
            assert False, "Should have raised SuggestionRepositoryError"
        except SuggestionRepositoryError as e:
            assert "Cannot change status" in str(e)
            print(f"Correctly prevented invalid transition: {e}")


# ============================================================================
# API Health Check Test
# ============================================================================


class TestAPIIntegration:
    """Tests for FastAPI endpoints."""

    def test_health_endpoint(self):
        """Test that /health endpoint works via TestClient."""
        from fastapi.testclient import TestClient
        from src.deduplication.main import app

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"
        print(f"Health check: {data}")

    def test_get_suggestion_endpoint(self, repository, embedding_client, cleanup_firestore):
        """Test GET /suggestions/{suggestionId} returns full lineage (T027)."""
        from fastapi.testclient import TestClient
        from src.deduplication.main import app

        # Create a suggestion with 2 traces
        trace_id_1 = f"trace_api_{uuid.uuid4().hex[:8]}"
        pattern1 = _create_test_pattern(
            trace_id=trace_id_1,
            trigger_condition="API test pattern 1",
        )

        text1 = f"{pattern1.failure_type.value}: {pattern1.trigger_condition}"
        embedding1 = embedding_client.get_embedding(text1)

        suggestion = repository.create_suggestion(
            pattern=pattern1,
            embedding=embedding1,
            suggestion_type=SuggestionType.EVAL,
        )
        cleanup_firestore.append(suggestion.suggestion_id)

        # Merge second pattern
        trace_id_2 = f"trace_api_{uuid.uuid4().hex[:8]}"
        pattern2 = _create_test_pattern(
            trace_id=trace_id_2,
            trigger_condition="API test pattern 2",
        )
        repository.merge_into_suggestion(
            suggestion_id=suggestion.suggestion_id,
            pattern=pattern2,
            similarity_score=0.91,
        )

        # Call API endpoint
        client = TestClient(app)
        response = client.get(f"/suggestions/{suggestion.suggestion_id}")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert data["suggestionId"] == suggestion.suggestion_id
        assert data["type"] == "eval"
        assert data["status"] == "pending"

        # Verify lineage in response
        assert len(data["sourceTraces"]) == 2
        trace_ids_in_response = [st["traceId"] for st in data["sourceTraces"]]
        assert trace_id_1 in trace_ids_in_response
        assert trace_id_2 in trace_ids_in_response

        print(f"GET suggestion returned {len(data['sourceTraces'])} traces")

    def test_get_suggestion_not_found(self):
        """Test GET /suggestions/{suggestionId} returns 404 for non-existent."""
        from fastapi.testclient import TestClient
        from src.deduplication.main import app

        client = TestClient(app)
        response = client.get("/suggestions/sugg_nonexistent123")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"] == "not_found"
        print("404 returned correctly for non-existent suggestion")

    def test_list_suggestions_endpoint(self, repository, embedding_client, cleanup_firestore):
        """Test GET /suggestions returns paginated list (T028)."""
        from fastapi.testclient import TestClient
        from src.deduplication.main import app

        # Create 3 suggestions
        created_ids = []
        for i in range(3):
            trace_id = f"trace_list_{uuid.uuid4().hex[:8]}"
            pattern = _create_test_pattern(
                trace_id=trace_id,
                trigger_condition=f"List test pattern {i}",
            )

            text = f"{pattern.failure_type.value}: {pattern.trigger_condition}"
            embedding = embedding_client.get_embedding(text)

            suggestion = repository.create_suggestion(
                pattern=pattern,
                embedding=embedding,
                suggestion_type=SuggestionType.EVAL,
            )
            created_ids.append(suggestion.suggestion_id)
            cleanup_firestore.append(suggestion.suggestion_id)

        # Call API endpoint
        client = TestClient(app)
        response = client.get("/suggestions?limit=10")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "suggestions" in data
        assert "total" in data
        assert len(data["suggestions"]) >= 3

        # Verify our created suggestions are in the list
        returned_ids = [s["suggestionId"] for s in data["suggestions"]]
        for cid in created_ids:
            assert cid in returned_ids

        print(f"List returned {len(data['suggestions'])} suggestions")

    def test_list_suggestions_with_status_filter(self, repository, embedding_client, cleanup_firestore):
        """Test GET /suggestions with status filter."""
        from fastapi.testclient import TestClient
        from src.deduplication.main import app

        # Create a pending suggestion
        trace_id = f"trace_filter_{uuid.uuid4().hex[:8]}"
        pattern = _create_test_pattern(
            trace_id=trace_id,
            trigger_condition="Filter test pattern",
        )

        text = f"{pattern.failure_type.value}: {pattern.trigger_condition}"
        embedding = embedding_client.get_embedding(text)

        suggestion = repository.create_suggestion(
            pattern=pattern,
            embedding=embedding,
            suggestion_type=SuggestionType.EVAL,
        )
        cleanup_firestore.append(suggestion.suggestion_id)

        # Filter by pending status
        client = TestClient(app)
        response = client.get("/suggestions?status=pending&limit=10")

        assert response.status_code == 200
        data = response.json()

        # Verify all returned are pending
        for s in data["suggestions"]:
            assert s["status"] == "pending"

        print(f"Filtered list: {len(data['suggestions'])} pending suggestions")

    def test_update_status_endpoint(self, repository, embedding_client, cleanup_firestore):
        """Test PATCH /suggestions/{suggestionId}/status endpoint (T032)."""
        from fastapi.testclient import TestClient
        from src.deduplication.main import app

        # Create a pending suggestion
        trace_id = f"trace_patch_{uuid.uuid4().hex[:8]}"
        pattern = _create_test_pattern(
            trace_id=trace_id,
            trigger_condition="PATCH endpoint test pattern",
        )

        text = f"{pattern.failure_type.value}: {pattern.trigger_condition}"
        embedding = embedding_client.get_embedding(text)

        suggestion = repository.create_suggestion(
            pattern=pattern,
            embedding=embedding,
            suggestion_type=SuggestionType.EVAL,
        )
        cleanup_firestore.append(suggestion.suggestion_id)

        # Call PATCH endpoint
        client = TestClient(app)
        response = client.patch(
            f"/suggestions/{suggestion.suggestion_id}/status",
            json={
                "status": "approved",
                "actor": "api_test@example.com",
                "notes": "Approved via API test",
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response
        assert data["suggestionId"] == suggestion.suggestion_id
        assert data["previousStatus"] == "pending"
        assert data["newStatus"] == "approved"
        assert data["actor"] == "api_test@example.com"
        assert data["notes"] == "Approved via API test"

        print(f"PATCH status update: {data['previousStatus']} -> {data['newStatus']}")

    def test_update_status_invalid_transition(self, repository, embedding_client, cleanup_firestore):
        """Test PATCH endpoint rejects invalid transitions (T033)."""
        from fastapi.testclient import TestClient
        from src.deduplication.main import app

        # Create and approve a suggestion
        trace_id = f"trace_invalid_{uuid.uuid4().hex[:8]}"
        pattern = _create_test_pattern(
            trace_id=trace_id,
            trigger_condition="Invalid transition test pattern",
        )

        text = f"{pattern.failure_type.value}: {pattern.trigger_condition}"
        embedding = embedding_client.get_embedding(text)

        suggestion = repository.create_suggestion(
            pattern=pattern,
            embedding=embedding,
            suggestion_type=SuggestionType.EVAL,
        )
        cleanup_firestore.append(suggestion.suggestion_id)

        # First approve it
        repository.update_suggestion_status(
            suggestion_id=suggestion.suggestion_id,
            new_status=SuggestionStatus.APPROVED,
            actor="first_approver@example.com",
        )

        # Try to reject via API (should fail with 400)
        client = TestClient(app)
        response = client.patch(
            f"/suggestions/{suggestion.suggestion_id}/status",
            json={
                "status": "rejected",
                "actor": "second_actor@example.com",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error"] == "invalid_transition"
        print(f"Correctly rejected invalid transition: {data['detail']['message']}")
