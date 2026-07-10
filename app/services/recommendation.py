"""RecommendationService wrapping the multi-strategy recommendation registry queries."""

from pathlib import Path
from sqlalchemy.orm import Session
from app.config.settings import settings
from app.database.models import Song
from app.recommendations.registry import get_recommender


class RecommendationService:
    """Wrapper querying the underlying Vector, Content, and Hybrid engines."""

    @staticmethod
    def recommend(song_id: int, strategy: str, limit: int, session: Session) -> list[dict]:
        """Runs the recommendation strategy to retrieve ranked recommendations."""
        strat = strategy.lower().strip()
        recommender = get_recommender(strat)
        if not recommender:
            raise ValueError(f"Unknown recommendation strategy: {strategy}")

        # Inject default vector index paths dynamically for vector/hybrid strategies
        if strat in ["vector", "hybrid"]:
            recommender.index_path = Path(settings.PROJECT_ROOT) / "data" / "vector_index.bin"
            recommender.faiss_index = None

        results = recommender.recommend(song_id=song_id, limit=limit, db_session=session)

        detailed = []
        for sid, score in results:
            song = session.get(Song, sid)
            if song:
                detailed.append({
                    "id": song.id,
                    "title": song.title,
                    "artist": song.artist,
                    "album": song.album,
                    "score": float(score),
                })
        return detailed
