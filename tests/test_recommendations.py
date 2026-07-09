"""Unit tests for the Recommendation Engine package including the classical MIR pipeline."""

import pickle
from pathlib import Path
import numpy as np
import pytest
from sqlalchemy.orm import Session
from app.database.models import AudioFeatures, Embeddings, Song
from app.recommendations.base import BaseRecommender
from app.recommendations.content import ContentRecommender
from app.recommendations.content_pipeline import (
    FeatureStatisticsGenerator,
    FeatureVectorBuilder,
)
from app.recommendations.hybrid import HybridRecommender
from app.recommendations.registry import (
    RecommenderRegistry,
    get_recommender,
    register_recommender,
)
from app.recommendations.vector import VectorRecommender


class MockFAISSIndex:
    """Mock FAISS index for VectorRecommender testing."""

    def __init__(self, target_results: list[tuple[int, float]]) -> None:
        self.target_results = target_results
        self.ntotal = len(target_results)

    def search(self, query_vector: list[float], k: int) -> list[tuple[int, float]]:
        return self.target_results


@pytest.fixture
def populated_db(db_session: Session) -> Session:
    """Fixture populating database with multiple songs, embeddings, and acoustic features."""
    rng = np.random.RandomState(42)

    # Insert 5 songs
    songs = []
    for i in range(1, 6):
        song = Song(
            path=f"/path/song{i}.mp3",
            hash=f"hash{i}",
            title=f"Song {i}",
            artist="Various Artists",
        )
        db_session.add(song)
        songs.append(song)
    db_session.commit()

    # Add embeddings (512-dim unit-normalized) and audio features
    for idx, song in enumerate(songs):
        # Embeddings
        vec = rng.rand(512).astype(np.float32)
        vec /= np.linalg.norm(vec)
        emb = Embeddings(song_id=song.id, vector=pickle.dumps(vec.tolist()))
        db_session.add(emb)

        # Audio features: set features that make song 1 and 2 very similar acoustically,
        # song 3 moderately similar, and song 4 and 5 different.
        bpm = 120.0
        chroma_arr = np.zeros((12, 10))
        mfcc_arr = np.zeros((13, 10))

        if idx == 0:  # Song 1
            bpm = 120.0
            chroma_arr[0, :] = 1.0
            mfcc_arr[0, :] = 1.0
        elif idx == 1:  # Song 2
            bpm = 120.5
            chroma_arr[0, :] = 0.95
            chroma_arr[1, :] = 0.1  # slightly different
            mfcc_arr[0, :] = 0.95
            mfcc_arr[1, :] = 0.1
        elif idx == 2:  # Song 3
            bpm = 110.0
            chroma_arr[4, :] = 1.0
            mfcc_arr[4, :] = 1.0
        else:  # Song 4 & 5
            bpm = 80.0
            chroma_arr[11, :] = 1.0
            mfcc_arr[12, :] = 1.0

        feat = AudioFeatures(
            song_id=song.id,
            bpm=bpm,
            chroma=pickle.dumps(chroma_arr),
            mfcc=pickle.dumps(mfcc_arr),
            spectral_centroid=pickle.dumps(np.ones((1, 10))),
            spectral_contrast=pickle.dumps(np.ones((7, 10))),
            rms=pickle.dumps(np.ones((1, 10))),
            zero_crossing_rate=pickle.dumps(np.ones((1, 10))),
        )
        db_session.add(feat)

    db_session.commit()
    return db_session


def test_statistics_generator() -> None:
    """Verifies that FeatureStatisticsGenerator computes the expected channels and statistics."""
    stats_gen = FeatureStatisticsGenerator()

    # Create dummy AudioFeatures record
    chroma_arr = np.random.rand(12, 100)  # 12 channels, 100 frames
    feat = AudioFeatures(
        bpm=120.0,
        key_estimation="C# Minor",
        chroma=pickle.dumps(chroma_arr),
    )

    stats = stats_gen.generate_stats(feat)

    # 1. Key Parsing Check
    # "C# Minor" -> mode = 0.0, Pitch index 1 = 1.0 (C#)
    assert stats["key"][0] == 0.0
    assert stats["key"][2] == 1.0  # C# is index 1 of PITCH_NAMES -> idx+1 = index 2 of stats["key"]

    # 2. Statistics dimension checks (6 stats per channel)
    # Chroma: 12 channels * 6 stats = 72 dimensions
    assert stats["chroma"].shape == (72,)
    # MFCC: 13 channels * 6 stats = 78 dimensions (defaulted to 0s as mfcc is empty)
    assert stats["mfcc"].shape == (78,)
    assert np.all(stats["mfcc"] == 0)


def test_group_normalization() -> None:
    """Verifies that FeatureVectorBuilder group-normalizes descriptor families independently."""
    builder = FeatureVectorBuilder()

    stats = {
        "bpm": np.array([120.0]),  # norm will become 1.0 after normalization
        "key": np.zeros(13),
        "mfcc": np.ones(78) * 5.0,  # norm will become 1.0 after normalization
        "chroma": np.zeros(72),
        "spectral_contrast": np.zeros(42),
        "spectral_centroid": np.zeros(6),
        "rms": np.zeros(6),
        "zero_crossing_rate": np.zeros(6),
    }

    vec = builder.build_vector(stats)
    # Total dim: 1 + 13 + 78 + 72 + 42 + 6 + 6 + 6 = 224
    assert vec.shape == (224,)

    # Verify BPM group (first element) normalized to 1.0
    assert vec[0] == 1.0

    # Verify MFCC group (starts at index 14 to 14+78) has L2 norm = 1.0
    mfcc_norm = np.linalg.norm(vec[14 : 14 + 78])
    assert pytest.approx(mfcc_norm) == 1.0


def test_vector_recommender(populated_db: Session) -> None:
    """Verifies that VectorRecommender queries FAISS and excludes the query song itself."""
    mock_index = MockFAISSIndex([(1, 1.0), (2, 0.9), (3, 0.8)])
    recommender = VectorRecommender(faiss_index=mock_index)

    # Generate recommendations for Song 1 (id=1)
    results = recommender.recommend(song_id=1, limit=2, db_session=populated_db)

    # Verification: should exclude song 1 itself and return top 2
    assert len(results) == 2
    assert results[0][0] == 2
    assert results[0][1] == 0.9
    assert results[1][0] == 3
    assert results[1][1] == 0.8


def test_content_recommender_mir_pipeline(populated_db: Session, tmp_path: Path) -> None:
    """Verifies that ContentRecommender fits, persists, and queries using the MIR pipeline."""
    scaler_path = tmp_path / "scaler.pkl"
    pca_path = tmp_path / "pca.pkl"
    index_path = tmp_path / "content_index.bin"

    recommender = ContentRecommender(
        scaler_path=scaler_path,
        pca_path=pca_path,
        index_path=index_path,
    )

    # Generate recommendations for Song 1 (id=1)
    results = recommender.recommend(song_id=1, limit=3, db_session=populated_db)

    # Verification
    # Song 2 (id=2) should be the closest content recommendation to Song 1 (id=1)
    assert len(results) > 0
    assert results[0][0] == 2
    # Result list should not include target song 1
    assert 1 not in [item[0] for item in results]

    # Verify scaler, PCA, and FAISS index files were persisted to disk
    assert scaler_path.exists()
    assert pca_path.exists()
    assert index_path.exists()


def test_hybrid_recommender(populated_db: Session) -> None:
    """Verifies that HybridRecommender correctly combines and weights scores from other recommenders."""

    class MockRecommender(BaseRecommender):

        def __init__(self, returned_scores: list[tuple[int, float]]) -> None:
            self.scores = returned_scores

        def recommend(
            self, song_id: int, limit: int = 10, db_session: Session | None = None
        ) -> list[tuple[int, float]]:
            return self.scores

    # Recommender A gives: song 2 -> 0.8, song 3 -> 0.6
    rec_a = MockRecommender([(2, 0.8), (3, 0.6)])
    # Recommender B gives: song 2 -> 0.4, song 4 -> 0.9
    rec_b = MockRecommender([(2, 0.4), (4, 0.9)])

    # Hybrid weights: Rec A = 0.7, Rec B = 0.3
    hybrid = HybridRecommender([rec_a, rec_b], weights=[0.7, 0.3])

    results = hybrid.recommend(song_id=1, limit=3, db_session=populated_db)

    assert len(results) == 3
    assert results[0][0] == 2  # Score 0.68 (highest)
    assert pytest.approx(results[0][1]) == 0.68
    assert results[1][0] == 3  # Score 0.42
    assert pytest.approx(results[1][1]) == 0.42
    assert results[2][0] == 4  # Score 0.27
    assert pytest.approx(results[2][1]) == 0.27


def test_registry() -> None:
    """Verifies registering, listing, and retrieving from the RecommenderRegistry."""
    registry = RecommenderRegistry()

    class DummyRec(BaseRecommender):

        def recommend(
            self, song_id: int, limit: int = 10, db_session: Session | None = None
        ) -> list[tuple[int, float]]:
            return []

    dummy = DummyRec()
    registry.register("dummy", dummy)

    assert "dummy" in registry.list_strategies()
    assert registry.get("dummy") is dummy
    assert registry.get("DUMMY") is dummy

    # Test global registry wrappers
    register_recommender("test_global", dummy)
    assert get_recommender("test_global") is dummy

    with pytest.raises(KeyError):
        get_recommender("non_existent_recommender")
