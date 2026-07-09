"""Unit tests for the embedding generation module."""

import pickle
import numpy as np
import pytest
from app.embeddings.generator import generate_embedding
from app.features.extractor import AudioFeaturesInfo


def _create_mock_features(bpm: float, seed: int) -> AudioFeaturesInfo:
    """Helper to construct mock AudioFeaturesInfo with random acoustic content."""
    rng = np.random.RandomState(seed)
    return AudioFeaturesInfo(
        bpm=bpm,
        chroma=pickle.dumps(rng.rand(12, 10)),
        mfcc=pickle.dumps(rng.rand(13, 10)),
        spectral_centroid=pickle.dumps(rng.rand(1, 10)),
        spectral_contrast=pickle.dumps(rng.rand(7, 10)),
        rms=pickle.dumps(rng.rand(1, 10)),
        zero_crossing_rate=pickle.dumps(rng.rand(1, 10)),
        key_estimation="C Major",
    )


def test_generate_embedding_shape_and_norm() -> None:
    """Verifies that the generated embedding has 512 dimensions and is unit-normalized."""
    info = _create_mock_features(bpm=120.0, seed=42)
    vector = generate_embedding(info)

    assert isinstance(vector, list)
    assert len(vector) == 512

    # Check L2 Norm is approximately 1.0
    arr = np.array(vector)
    norm = np.linalg.norm(arr)
    assert pytest.approx(norm, rel=1e-5) == 1.0


def test_generate_embedding_determinism() -> None:
    """Verifies that embedding generation is completely reproducible and deterministic."""
    info1 = _create_mock_features(bpm=120.0, seed=42)
    info2 = _create_mock_features(bpm=120.0, seed=42)

    vec1 = generate_embedding(info1)
    vec2 = generate_embedding(info2)

    assert vec1 == vec2


def test_generate_embedding_uniqueness() -> None:
    """Verifies that distinct acoustic features produce different embeddings."""
    info1 = _create_mock_features(bpm=120.0, seed=42)
    info2 = _create_mock_features(bpm=95.0, seed=99)

    vec1 = generate_embedding(info1)
    vec2 = generate_embedding(info2)

    assert vec1 != vec2
