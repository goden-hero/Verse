"""Centralized registry for registering and retrieving recommender strategies."""

import logging
from app.recommendations.base import BaseRecommender

logger = logging.getLogger("music_rec.recommendations.registry")


class RecommenderRegistry:
    """Manages registered recommendation strategies to support extension without modifying core logic."""

    def __init__(self) -> None:
        self._recommenders: dict[str, BaseRecommender] = {}

    def register(self, name: str, recommender: BaseRecommender) -> None:
        """Registers a new recommender strategy.

        Args:
            name: Unique name key for the recommender.
            recommender: BaseRecommender instance.
        """
        if not name:
            raise ValueError("Recommender name cannot be empty.")
        if not isinstance(recommender, BaseRecommender):
            raise TypeError("Recommender must inherit from BaseRecommender.")

        self._recommenders[name.lower()] = recommender
        logger.info("Successfully registered recommender: %s", name)

    def get(self, name: str) -> BaseRecommender:
        """Retrieves a registered recommender strategy.

        Args:
            name: Name of the recommender to retrieve.

        Returns:
            The registered BaseRecommender instance.
        """
        key = name.lower()
        if key not in self._recommenders:
            raise KeyError(f"No recommender strategy registered under name: '{name}'.")
        return self._recommenders[key]

    def list_strategies(self) -> list[str]:
        """Returns a list of all registered recommender names."""
        return list(self._recommenders.keys())


# Singleton instance for simple module-level access
_global_registry = RecommenderRegistry()


def register_recommender(name: str, recommender: BaseRecommender) -> None:
    """Convenience helper to register a recommender with the global registry."""
    _global_registry.register(name, recommender)


def get_recommender(name: str) -> BaseRecommender:
    """Convenience helper to retrieve a recommender from the global registry."""
    return _global_registry.get(name)
