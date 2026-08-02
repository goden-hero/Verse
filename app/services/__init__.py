"""Service layer exposing operations for the UI and AI Assistant."""

from app.services.library import LibraryService
from app.services.playback import PlaybackService
from app.services.recommendation import RecommendationService
from app.services.search import SearchService
from app.services.history import HistoryService
from app.services.playlist import PlaylistService
from app.services.playback_session import PlaybackSessionService
from app.services.queue import QueueService
from app.services.preferences import UserPreferencesService

__all__ = [
    "LibraryService",
    "PlaybackService",
    "RecommendationService",
    "SearchService",
    "HistoryService",
    "PlaylistService",
    "PlaybackSessionService",
    "QueueService",
    "UserPreferencesService",
]
