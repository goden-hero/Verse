"""Recommendation Engine package for the local AI Music Recommendation System."""

from app.recommendations.base import BaseRecommender
from app.recommendations.content import ContentRecommender
from app.recommendations.hybrid import HybridRecommender
from app.recommendations.registry import RecommenderRegistry, get_recommender, register_recommender
from app.recommendations.vector import VectorRecommender

__all__ = [
    "BaseRecommender",
    "VectorRecommender",
    "ContentRecommender",
    "HybridRecommender",
    "RecommenderRegistry",
    "register_recommender",
    "get_recommender",
]
