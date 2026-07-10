"""Service layer for tracking song listening history statistics."""

import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import ListeningHistory, Song

logger = logging.getLogger("music_rec.history.tracker")


def _get_or_create_history(song_id: int, db_session: Session) -> ListeningHistory:
    """Helper to fetch or create a ListeningHistory record for a song.

    Raises:
        ValueError: If the song_id does not exist in the database.
    """
    song = db_session.get(Song, song_id)
    if not song:
        logger.error("Attempted to record history for non-existent song_id %d", song_id)
        raise ValueError(f"Song with ID {song_id} does not exist.")

    history = db_session.get(ListeningHistory, song_id)
    if not history:
        logger.debug("Creating new ListeningHistory record for song_id %d", song_id)
        history = ListeningHistory(
            song_id=song_id,
            play_count=0,
            skips=0,
            likes=False,
            last_played=None,
            play_duration=0.0,
        )
        db_session.add(history)

    return history


def record_play(song_id: int, duration: float, db_session: Session) -> None:
    """Records a song play event.

    Increments the play count, updates the last played timestamp,
    and adds the duration to the total play duration.

    Args:
        song_id: Database key of the song.
        duration: Play duration in seconds.
        db_session: Database session.
    """
    if duration < 0:
        raise ValueError("Play duration cannot be negative.")

    history = _get_or_create_history(song_id, db_session)
    history.play_count += 1
    history.last_played = datetime.now()
    history.play_duration += duration

    db_session.commit()
    logger.info(
        "Recorded play for song %d. Total plays: %d, Total duration: %.2f sec.",
        song_id,
        history.play_count,
        history.play_duration,
    )


def record_skip(song_id: int, db_session: Session) -> None:
    """Records a song skip event.

    Increments the skips count.

    Args:
        song_id: Database key of the song.
        db_session: Database session.
    """
    history = _get_or_create_history(song_id, db_session)
    history.skips += 1

    db_session.commit()
    logger.info("Recorded skip for song %d. Total skips: %d.", song_id, history.skips)


def set_like_status(song_id: int, liked: bool, db_session: Session) -> None:
    """Sets the liked state of a song.

    Args:
        song_id: Database key of the song.
        liked: True to like, False to unlike.
        db_session: Database session.
    """
    history = _get_or_create_history(song_id, db_session)
    history.likes = liked

    db_session.commit()
    logger.info("Recorded like status for song %d: %s.", song_id, liked)


def get_history(song_id: int, db_session: Session) -> dict | None:
    """Fetches listening history statistics for a song.

    Args:
        song_id: Database key of the song.
        db_session: Database session.

    Returns:
        Dict of history attributes, or None if the song has no history record.
    """
    song = db_session.get(Song, song_id)
    if not song:
        logger.error("Requested history for non-existent song_id %d", song_id)
        return None

    history = db_session.get(ListeningHistory, song_id)
    if not history:
        return None

    return {
        "song_id": history.song_id,
        "play_count": history.play_count,
        "skips": history.skips,
        "likes": history.likes,
        "last_played": history.last_played.isoformat() if history.last_played else None,
        "play_duration": history.play_duration,
    }
