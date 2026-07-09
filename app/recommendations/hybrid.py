"""Hybrid recommender fusing results from multiple underlying recommender strategies."""

import logging
from sqlalchemy.orm import Session
from app.recommendations.base import BaseRecommender

logger = logging.getLogger("music_rec.recommendations.hybrid")


class HybridRecommender(BaseRecommender):
    """Combines recommendations from multiple strategies using weighted linear score fusion."""

    def __init__(
        self,
        recommenders: list[BaseRecommender],
        weights: list[float] | None = None,
    ) -> None:
        """Initializes the HybridRecommender.

        Args:
            recommenders: List of BaseRecommender instances to combine.
            weights: List of weights corresponding to each recommender.
                     If None, equal weights will be assigned.
        """
        if not recommenders:
            raise ValueError("HybridRecommender requires at least one underlying recommender.")

        self.recommenders = recommenders

        if weights is None:
            # Assign equal weights
            self.weights = [1.0 / len(recommenders)] * len(recommenders)
        else:
            if len(weights) != len(recommenders):
                raise ValueError("The number of weights must match the number of recommenders.")
            # Normalize weights to sum to 1.0
            total_weight = sum(weights)
            if total_weight <= 0:
                raise ValueError("Sum of weights must be greater than zero.")
            self.weights = [w / total_weight for w in weights]

    def recommend(
        self, song_id: int, limit: int = 10, db_session: Session | None = None
    ) -> list[tuple[int, float]]:
        """Fuses recommendations from all registered recommenders.

        Runs each underlying recommender, multiplies their similarity scores by
        their respective normalized weights, and aggregates scores for identical songs.

        Args:
            song_id: Database key of the target song.
            limit: Maximum recommendations to return.
            db_session: Database session.

        Returns:
            List of (song_id, similarity_score) sorted descending by combined score.
        """
        combined_scores: dict[int, float] = {}

        # Query each recommender. Requesting slightly more items (limit * 2) from
        # each recommender increases candidate overlap and boosts fusion accuracy.
        candidate_limit = max(limit * 2, 20)

        for rec, weight in zip(self.recommenders, self.weights):
            try:
                results = rec.recommend(song_id, limit=candidate_limit, db_session=db_session)
                for rec_song_id, score in results:
                    weighted_score = score * weight
                    combined_scores[rec_song_id] = (
                        combined_scores.get(rec_song_id, 0.0) + weighted_score
                    )
            except Exception as e:
                logger.error(
                    "Error querying underlying recommender %s in hybrid fusion: %s",
                    rec.__class__.__name__,
                    e,
                )

        # Sort the aggregated recommendations by score descending
        sorted_recommendations = sorted(
            combined_scores.items(), key=lambda item: item[1], reverse=True
        )

        return sorted_recommendations[:limit]
