"""Classical Music Information Retrieval (MIR) pipeline components for ContentRecommender."""

import logging
import pickle
from pathlib import Path
import faiss
import numpy as np
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session
from app.database.models import AudioFeatures
from app.search.index import FAISSIndex

logger = logging.getLogger("music_rec.recommendations.content_pipeline")

PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


class FeatureStatisticsGenerator:
    """Computes descriptive statistical summaries from raw time-series audio features."""

    def _deserialize(self, data: bytes | None) -> np.ndarray | None:
        if not data:
            return None
        try:
            return pickle.loads(data)
        except Exception as e:
            logger.warning("Failed to deserialize feature: %s", e)
            return None

    def _compute_stats(self, arr: np.ndarray | None, expected_channels: int) -> np.ndarray:
        """Computes mean, std, median, min, max, and dynamic range along the time axis (axis=1).

        Returns a 1D vector of size (expected_channels * 6).
        """
        if arr is None or arr.size == 0:
            return np.zeros(expected_channels * 6, dtype=np.float32)

        # Force 2D shape (channels, frames)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)

        # Handle channel mismatch by truncating or padding
        if arr.shape[0] != expected_channels:
            if arr.shape[0] > expected_channels:
                arr = arr[:expected_channels, :]
            else:
                padding = np.zeros((expected_channels - arr.shape[0], arr.shape[1]))
                arr = np.vstack([arr, padding])

        # Compute statistics along time axis (axis=1)
        means = np.mean(arr, axis=1)
        stds = np.std(arr, axis=1)
        medians = np.median(arr, axis=1)
        mins = np.min(arr, axis=1)
        maxs = np.max(arr, axis=1)
        ranges = maxs - mins

        # Stack and flatten -> shape (channels * 6,)
        stats = np.column_stack([means, stds, medians, mins, maxs, ranges])
        return stats.flatten().astype(np.float32)

    def _parse_key(self, key_str: str | None) -> np.ndarray:
        """Encodes musical key estimation as Mode (1=Major, 0=Minor) and one-hot Pitch (12-dim)."""
        mode = 0.5  # Default/Unknown
        pitch_one_hot = np.zeros(12, dtype=np.float32)

        if key_str and key_str != "Unknown":
            parts = key_str.split()
            if len(parts) == 2:
                pitch_name, mode_name = parts[0], parts[1]
                # Parse Mode
                if mode_name.lower() == "major":
                    mode = 1.0
                elif mode_name.lower() == "minor":
                    mode = 0.0

                # Parse Pitch
                if pitch_name in PITCH_NAMES:
                    idx = PITCH_NAMES.index(pitch_name)
                    pitch_one_hot[idx] = 1.0

        return np.concatenate([[mode], pitch_one_hot])

    def generate_stats(self, rec: AudioFeatures) -> dict[str, np.ndarray]:
        """Computes statistics for all features in an AudioFeatures record."""
        return {
            "bpm": np.array([rec.bpm or 120.0], dtype=np.float32),
            "key": self._parse_key(rec.key_estimation),
            "mfcc": self._compute_stats(self._deserialize(rec.mfcc), expected_channels=13),
            "chroma": self._compute_stats(self._deserialize(rec.chroma), expected_channels=12),
            "spectral_contrast": self._compute_stats(
                self._deserialize(rec.spectral_contrast), expected_channels=7
            ),
            "spectral_centroid": self._compute_stats(
                self._deserialize(rec.spectral_centroid), expected_channels=1
            ),
            "rms": self._compute_stats(self._deserialize(rec.rms), expected_channels=1),
            "zero_crossing_rate": self._compute_stats(
                self._deserialize(rec.zero_crossing_rate), expected_channels=1
            ),
        }


class FeatureVectorBuilder:
    """Group-normalizes feature families independently and concatenates them."""

    def _l2_normalize_group(self, vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        if norm > 0:
            return vec / norm
        return vec

    def build_vector(self, stats: dict[str, np.ndarray]) -> np.ndarray:
        """Applies independent L2 normalization to each family and concatenates them."""
        normalized_groups = []
        # Group-normalize each family independently
        for key in [
            "bpm",
            "key",
            "mfcc",
            "chroma",
            "spectral_contrast",
            "spectral_centroid",
            "rms",
            "zero_crossing_rate",
        ]:
            group = stats.get(key, np.array([], dtype=np.float32))
            normalized_groups.append(self._l2_normalize_group(group))

        return np.concatenate(normalized_groups)


class ContentEmbeddingGenerator:
    """Orchestrates transformation from AudioFeatures to normalized content embeddings."""

    def __init__(
        self,
        scaler_path: Path,
        pca_path: Path,
        stats_gen: FeatureStatisticsGenerator,
        builder: FeatureVectorBuilder,
    ) -> None:
        self.scaler_path = scaler_path
        self.pca_path = pca_path
        self.stats_gen = stats_gen
        self.builder = builder

        self.scaler: StandardScaler | None = None
        self.pca: PCA | None = None
        self.load_models()

    def load_models(self) -> bool:
        """Loads fitted scaler and PCA models from disk."""
        success = True
        if self.scaler_path.exists():
            try:
                with open(self.scaler_path, "rb") as f:
                    self.scaler = pickle.load(f)
            except Exception as e:
                logger.error("Failed to load StandardScaler from %s: %s", self.scaler_path, e)
                success = False
        else:
            success = False

        if self.pca_path.exists():
            try:
                with open(self.pca_path, "rb") as f:
                    self.pca = pickle.load(f)
            except Exception as e:
                logger.error("Failed to load PCA from %s: %s", self.pca_path, e)
                success = False
        else:
            success = False

        return success

    def generate_embedding(self, rec: AudioFeatures) -> np.ndarray | None:
        """Transforms a DB feature record into a unit-normalized content embedding."""
        if not self.scaler or not self.pca:
            logger.warning("Scaler or PCA models not fitted/loaded. Cannot generate embedding.")
            return None

        # 1. Compute stats
        stats = self.stats_gen.generate_stats(rec)

        # 2. Group normalize & concatenate
        raw_vector = self.builder.build_vector(stats).reshape(1, -1)

        # 3. Global Scaling
        scaled = self.scaler.transform(raw_vector)

        # 4. Dimensionality Reduction (PCA)
        reduced = self.pca.transform(scaled)[0]

        # 5. L2 Normalization (Cosine compatibility)
        norm = np.linalg.norm(reduced)
        if norm > 0:
            return (reduced / norm).astype(np.float32)
        return np.zeros(reduced.shape[0], dtype=np.float32)


def rebuild_content_pipeline(
    db_session: Session,
    scaler_path: str | Path,
    pca_path: str | Path,
    index_path: str | Path,
) -> bool:
    """Fits scaler & PCA on the entire database library, saves them, and builds the FAISS index."""
    scaler_path = Path(scaler_path)
    pca_path = Path(pca_path)
    index_path = Path(index_path)

    records = db_session.query(AudioFeatures).all()
    if not records:
        logger.warning("No audio features in DB. Pipeline cannot be rebuilt.")
        return False

    stats_gen = FeatureStatisticsGenerator()
    builder = FeatureVectorBuilder()

    # 1. Compute raw concatenated vectors for all songs
    song_ids = []
    raw_vectors = []
    for rec in records:
        song_ids.append(rec.song_id)
        stats = stats_gen.generate_stats(rec)
        vec = builder.build_vector(stats)
        raw_vectors.append(vec)

    X = np.array(raw_vectors, dtype=np.float32)

    # 2. Fit and save StandardScaler
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    scaler_path.parent.mkdir(parents=True, exist_ok=True)
    with open(scaler_path, "wb") as f:
        pickle.dump(scaler, f)
    logger.info("Fitted and saved StandardScaler.")

    # 3. Fit and save PCA (explaining 95% variance)
    n_samples, n_features = X_scaled.shape
    max_components = min(n_samples, n_features)

    # We fit a preliminary PCA to find how many components explain 95% variance
    pca_full = PCA(n_components=max_components)
    pca_full.fit(X_scaled)
    cumulative_variance = np.cumsum(pca_full.explained_variance_ratio_)
    n_components = int(np.argmax(cumulative_variance >= 0.95) + 1)
    n_components = max(1, min(n_components, max_components))

    pca = PCA(n_components=n_components)
    X_reduced = pca.fit_transform(X_scaled)

    with open(pca_path, "wb") as f:
        pickle.dump(pca, f)
    logger.info("Fitted and saved PCA model with %d components.", n_components)

    # 4. Generate content embeddings (L2 normalized)
    embeddings = []
    for row in X_reduced:
        norm = np.linalg.norm(row)
        if norm > 0:
            embeddings.append(row / norm)
        else:
            embeddings.append(np.zeros(n_components, dtype=np.float32))

    # 5. Build and save FAISS index using FAISSIndex wrapper
    index = FAISSIndex(index_path, dim=n_components)
    index.add_songs(song_ids, [emb.tolist() for emb in embeddings])
    index.save()
    logger.info("Built and saved FAISS content index with %d songs.", len(song_ids))

    return True
