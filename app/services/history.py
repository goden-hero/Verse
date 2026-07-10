"""HistoryService wrapping the listening history tracking operations."""

from sqlalchemy.orm import Session
from app.history import get_history, record_play, record_skip, set_like_status


class HistoryService:
    """Delegates listening events (play count, skips, likes) to history module trackers."""

    @staticmethod
    def record_play(song_id: int, duration: float, session: Session) -> None:
        """Records playback completion and duration metrics."""
        record_play(song_id=song_id, duration=duration, db_session=session)

    @staticmethod
    def record_skip(song_id: int, session: Session) -> None:
        """Records skip event increment."""
        record_skip(song_id=song_id, db_session=session)

    @staticmethod
    def set_like_status(song_id: int, liked: bool, session: Session) -> None:
        """Applies/toggles song favorite/liked status."""
        set_like_status(song_id=song_id, liked=liked, db_session=session)

    @staticmethod
    def get_history(song_id: int, session: Session) -> dict | None:
        """Retrieves formatted history details dictionary."""
        return get_history(song_id=song_id, db_session=session)
