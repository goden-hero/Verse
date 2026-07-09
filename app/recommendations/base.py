"""Abstract base class for all recommendation engine strategies."""

from abc import ABC, abstractmethod
from sqlalchemy.orm import Session


class BaseRecommender(ABC):
    """Abstract base class defining the interface for recommendation strategies."""

    @abstractmethod
    def recommend(
        self, song_id: int, limit: int = 10, db_session: Session | None = None
    ) -> list[tuple[int, float]]:
        """Generates recommendations for a given target song.

        Args:
            song_id: Database primary key ID of the target song.
            limit: Maximum number of recommendations to return.
            db_session: Optional SQLAlchemy database session.

        Returns:
            A list of tuples: (song_id, similarity_score) sorted by score descending.
            Similarity scores should be scaled between -1.0 and 1.0 (or 0.0 and 1.0).
        """
        pass
