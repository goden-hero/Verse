"""Unit tests for the FAISS vector similarity search index."""

from pathlib import Path
import numpy as np
import pytest
from app.search.index import FAISSIndex


@pytest.fixture
def temp_index_path(tmp_path: Path) -> Path:
    """Fixture returning a temporary path for the FAISS index file."""
    return tmp_path / "test_faiss.bin"


def test_faiss_empty_index(temp_index_path: Path) -> None:
    """Verifies that an empty index search returns no results and behaves cleanly."""
    index = FAISSIndex(temp_index_path)
    assert index.index.ntotal == 0

    results = index.search([0.1] * 512, k=5)
    assert results == []


def test_faiss_add_and_search(temp_index_path: Path) -> None:
    """Verifies adding vectors, matching dimensions, and finding nearest neighbors."""
    index = FAISSIndex(temp_index_path)

    # Create dummy embeddings (unit-normalized)
    rng = np.random.RandomState(42)
    vec1 = rng.rand(512).astype(np.float32)
    vec1 /= np.linalg.norm(vec1)

    vec2 = rng.rand(512).astype(np.float32)
    vec2 /= np.linalg.norm(vec2)

    index.add_songs([101, 102], [vec1.tolist(), vec2.tolist()])
    assert index.index.ntotal == 2

    # Query with exactly vec1. Top result should be ID 101 with similarity ~ 1.0
    results = index.search(vec1.tolist(), k=2)
    assert len(results) == 2
    assert results[0][0] == 101
    assert pytest.approx(results[0][1], rel=1e-5) == 1.0
    assert results[1][0] == 102


def test_faiss_save_and_load(temp_index_path: Path) -> None:
    """Verifies that saving the index to disk and reloading it recovers the exact state."""
    index = FAISSIndex(temp_index_path)

    rng = np.random.RandomState(42)
    vec = rng.rand(512).astype(np.float32)
    vec /= np.linalg.norm(vec)

    index.add_songs([999], [vec.tolist()])
    index.save()

    # Create a new index instance loaded from the same path
    new_index = FAISSIndex(temp_index_path)
    new_index.load()

    assert new_index.index.ntotal == 1
    results = new_index.search(vec.tolist(), k=1)
    assert results[0][0] == 999
    assert pytest.approx(results[0][1], rel=1e-5) == 1.0


def test_faiss_remove_songs(temp_index_path: Path) -> None:
    """Verifies that songs can be dynamically removed from the index by ID."""
    index = FAISSIndex(temp_index_path)

    rng = np.random.RandomState(42)
    vec = rng.rand(512).astype(np.float32)
    vec /= np.linalg.norm(vec)

    index.add_songs([10, 20], [vec.tolist(), (vec * -1).tolist()])
    assert index.index.ntotal == 2

    index.remove_songs([10])
    assert index.index.ntotal == 1

    # Search should now only return ID 20
    results = index.search(vec.tolist(), k=5)
    assert len(results) == 1
    assert results[0][0] == 20


def test_faiss_add_mismatched_dimensions(temp_index_path: Path) -> None:
    """Verifies that inserting vectors with invalid dimensions raises a ValueError."""
    index = FAISSIndex(temp_index_path)

    with pytest.raises(ValueError):
        index.add_songs([1], [[0.5] * 256])  # Dimension is 256 instead of 512

    with pytest.raises(ValueError):
        index.add_songs([1, 2], [[0.5] * 512])  # ID list is size 2, vector list is size 1
