"""Vector Cosine Similarity recommender strategy using the FAISS index."""

import logging
import pickle
from pathlib import Path
from sqlalchemy.orm import Session
from app.database.models import Embeddings
from app.recommendations.base import BaseRecommender
from app.search.index import FAISSIndex

logger = logging.getLogger("music_rec.recommendations.vector")


class VectorRecommender(BaseRecommender):
    """Generates song recommendations using FAISS-based cosine similarity of embeddings."""

    def __init__(
        self,
        faiss_index: FAISSIndex | None = None,
        index_path: str | Path | None = None,
    ) -> None:
        """Initializes the VectorRecommender.

        Args:
            faiss_index: An optional pre-loaded FAISSIndex instance.
            index_path: An optional path to load the FAISS index from.
        """
        self.faiss_index = faiss_index
        self.index_path = Path(index_path) if index_path else None

    def _get_index(self) -> FAISSIndex:
        """Helper to retrieve or initialize the FAISS index wrapper."""
        if self.faiss_index is not None:
            return self.faiss_index
        if self.index_path is not None:
            idx = FAISSIndex(self.index_path)
            idx.load()
            self.faiss_index = idx
            return idx
        raise ValueError(
            "VectorRecommender requires either a preloaded 'faiss_index' or a valid 'index_path'."
        )

    def recommend(
        self, song_id: int, limit: int = 10, db_session: Session | None = None
    ) -> list[tuple[int, float]]:
        """Generates recommendations for a song using embedding vector similarity.

        Args:
            song_id: Database key of the target song to base recommendations on.
            limit: Maximum recommendations to return.
            db_session: Database session. Required to load the song's embedding.

        Returns:
            List of (song_id, similarity_score) sorted descending by similarity.
        """
        if db_session is None:
            logger.error("Database session is required to fetch target song embeddings.")
            return []

        # 1. Fetch the target song's embedding from the database
        emb_record = db_session.get(Embeddings, song_id)
        if not emb_record or not emb_record.vector:
            logger.warning(
                "No embedding vector found in database for song_id: %d. Cannot generate recommendations.",
                song_id,
            )
            return []

        try:
            query_vector = pickle.loads(emb_record.vector)
        except Exception as e:
            logger.error(
                "Failed to deserialize embedding vector for song %d: %s",
                song_id,
                e,
            )
            return []

        # 2. Query the FAISS index
        try:
            idx = self._get_index()
            # Request limit + 1 items in case the target song itself is returned as the nearest match
            raw_results = idx.search(query_vector, k=limit + 1)
        except Exception as e:
            logger.error("FAISS index search failed: %s", e)
            return []

        # 3. Filter out the target query song itself and return the top matches
        recommendations = [res for res in raw_results if res[0] != song_id]
        return recommendations[:limit]
