"""HistoryService facade providing static access to listening history tracking logic."""

import logging
from sqlalchemy.orm import Session
from app.history.tracker import (
    get_history as tracker_get_history,
    get_user_liked_songs as tracker_get_user_liked_songs,
    get_user_playback_history as tracker_get_user_playback_history,
    record_play as tracker_record_play,
    record_skip as tracker_record_skip,
    set_like_status as tracker_set_like_status,
)
from app.identity import CurrentUser

logger = logging.getLogger("music_rec.services.history")


class HistoryService:
    """Service facade for user-scoped and aggregate listening history."""

    @staticmethod
    def record_play(
        current_user: CurrentUser,
        song_id: int,
        duration: float,
        session: Session,
    ) -> None:
        """Records a user play event."""
        tracker_record_play(
            current_user=current_user,
            song_id=song_id,
            duration=duration,
            db_session=session,
        )

    @staticmethod
    def record_skip(
        current_user: CurrentUser,
        song_id: int,
        session: Session,
    ) -> None:
        """Records a user skip event."""
        tracker_record_skip(
            current_user=current_user,
            song_id=song_id,
            db_session=session,
        )

    @staticmethod
    def set_like_status(
        current_user: CurrentUser,
        song_id: int,
        liked: bool,
        session: Session,
    ) -> None:
        """Sets liked status of a song for current_user."""
        tracker_set_like_status(
            current_user=current_user,
            song_id=song_id,
            liked=liked,
            db_session=session,
        )

    @staticmethod
    def get_history(
        current_user: CurrentUser,
        song_id: int,
        session: Session,
    ) -> dict | None:
        """Fetches history statistics for a song for current_user."""
        return tracker_get_history(
            current_user=current_user,
            song_id=song_id,
            db_session=session,
        )

    @staticmethod
    def get_user_liked_songs(
        current_user: CurrentUser,
        session: Session,
        limit: int = 50,
    ) -> list[dict]:
        """Retrieves liked songs for current_user."""
        return tracker_get_user_liked_songs(
            current_user=current_user,
            db_session=session,
            limit=limit,
        )

    @staticmethod
    def get_user_playback_history(
        current_user: CurrentUser,
        session: Session,
        limit: int = 50,
    ) -> list[dict]:
        """Retrieves playback history entries for current_user."""
        return tracker_get_user_playback_history(
            current_user=current_user,
            db_session=session,
            limit=limit,
        )
