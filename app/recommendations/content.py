"""Content-based recommender using the statistical classical MIR pipeline and FAISS."""

import logging
from pathlib import Path
from sqlalchemy.orm import Session
from app.database.models import AudioFeatures
from app.recommendations.base import BaseRecommender
from app.search.index import FAISSIndex
from app.recommendations.content_pipeline import (
    ContentEmbeddingGenerator,
    FeatureStatisticsGenerator,
    FeatureVectorBuilder,
    rebuild_content_pipeline,
)

logger = logging.getLogger("music_rec.recommendations.content")


class ContentRecommender(BaseRecommender):
    """Generates recommendations using Cosine Similarity on handcrafted classical MIR embeddings."""

    def __init__(
        self,
        scaler_path: str | Path = "data/content_scaler.pkl",
        pca_path: str | Path = "data/content_pca.pkl",
        index_path: str | Path = "data/content_index.bin",
    ) -> None:
        """Initializes the ContentRecommender with model storage paths.

        Args:
            scaler_path: Path to the serialized StandardScaler.
            pca_path: Path to the serialized PCA transformer.
            index_path: Path to the serialized FAISS content index.
        """
        self.scaler_path = Path(scaler_path)
        self.pca_path = Path(pca_path)
        self.index_path = Path(index_path)

    def _ensure_pipeline(self, db_session: Session) -> tuple[ContentEmbeddingGenerator, FAISSIndex]:
        """Loads the embedding models and FAISS index, rebuilding them if they do not exist."""
        stats_gen = FeatureStatisticsGenerator()
        builder = FeatureVectorBuilder()
        generator = ContentEmbeddingGenerator(
            self.scaler_path, self.pca_path, stats_gen, builder
        )

        # Rebuild if models or index file are missing
        if (
            not self.scaler_path.exists()
            or not self.pca_path.exists()
            or not self.index_path.exists()
        ):
            logger.info("Content recommendation files missing. Building pipeline...")
            rebuild_content_pipeline(
                db_session, self.scaler_path, self.pca_path, self.index_path
            )
            # Reload generator models
            generator.load_models()

        # Load index
        # We need to extract the dimension of the PCA model to initialize the index manager
        dim = generator.pca.n_components if generator.pca else 32
        index = FAISSIndex(self.index_path, dim=dim)
        index.load()

        return generator, index

    def recommend(
        self, song_id: int, limit: int = 10, db_session: Session | None = None
    ) -> list[tuple[int, float]]:
        """Generates content recommendations for a song using the persistent MIR pipeline.

        Args:
            song_id: Database key of the target song.
            limit: Maximum recommendations to return.
            db_session: Database session.

        Returns:
            List of (song_id, similarity_score) sorted descending by similarity.
        """
        if db_session is None:
            logger.error("Database session is required for ContentRecommender.")
            return []

        # 1. Ensure embedding generator and FAISS index are loaded
        try:
            generator, index = self._ensure_pipeline(db_session)
        except Exception as e:
            logger.error("Failed to load/initialize the ContentRecommender pipeline: %s", e)
            return []

        if index.index.ntotal == 0:
            logger.warning("FAISS content index is empty.")
            return []

        # 2. Retrieve query embedding vector for the target song
        query_vector = None
        # Try FAISS reconstruction first
        try:
            # Reconstruct returns a NumPy array.
            query_vector = index.index.reconstruct(song_id)
        except Exception:
            logger.debug(
                "FAISS reconstruction not available for song_id %d. Computing from database.",
                song_id,
            )

        # Fallback: compute embedding on the fly from the DB features
        if query_vector is None:
            rec = db_session.get(AudioFeatures, song_id)
            if not rec:
                logger.warning(
                    "Target song %d has no audio features extracted. Cannot generate recommendations.",
                    song_id,
                )
                return []
            query_vector = generator.generate_embedding(rec)

        if query_vector is None:
            logger.error("Failed to acquire query embedding for song_id %d.", song_id)
            return []

        # Convert numpy array to list for FAISS wrapper search method
        query_vector_list = query_vector.tolist()

        # 3. Query the FAISS content index
        try:
            # Query limit + 1 items in case the target song itself is returned
            raw_results = index.search(query_vector_list, k=limit + 1)
        except Exception as e:
            logger.error("FAISS content index search failed: %s", e)
            return []

        # 4. Filter out target song and return top results
        recommendations = [res for res in raw_results if res[0] != song_id]
        return recommendations[:limit]
