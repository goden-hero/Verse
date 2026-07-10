"""Service layer exposing operations for the UI and AI Assistant."""

from app.services.library import LibraryService
from app.services.playback import PlaybackService
from app.services.recommendation import RecommendationService
from app.services.search import SearchService
from app.services.history import HistoryService
from app.services.playlist import PlaylistService

__all__ = [
    "LibraryService",
    "PlaybackService",
    "RecommendationService",
    "SearchService",
    "HistoryService",
    "PlaylistService",
]
