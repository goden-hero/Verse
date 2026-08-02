"""Service layer for tracking user listening history and liked song statistics."""

import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import ListeningHistory, LikedSong, PlaybackHistory, Song
from app.identity import CurrentUser

logger = logging.getLogger("music_rec.history.tracker")


def _get_or_create_global_history(song_id: int, db_session: Session) -> ListeningHistory:
    """Helper to fetch or create a global ListeningHistory record for a song.

    Raises:
        ValueError: If the song_id does not exist in the database.
    """
    song = db_session.get(Song, song_id)
    if not song:
        logger.error("Attempted to record history for non-existent song_id %d", song_id)
        raise ValueError(f"Song with ID {song_id} does not exist.")

    history = db_session.get(ListeningHistory, song_id)
    if not history:
        logger.debug("Creating new global ListeningHistory record for song_id %d", song_id)
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


def record_play(
    current_user: CurrentUser,
    song_id: int,
    duration: float,
    db_session: Session,
) -> None:
    """Records a user song play event.

    Args:
        current_user: Active CurrentUser instance.
        song_id: Database key of the song.
        duration: Play duration in seconds.
        db_session: Database session.
    """
    if duration < 0:
        raise ValueError("Play duration cannot be negative.")

    # 1. Update global aggregates
    global_hist = _get_or_create_global_history(song_id, db_session)
    now = datetime.utcnow()
    global_hist.play_count += 1
    global_hist.last_played = now
    global_hist.play_duration += duration

    # 2. Record user-owned playback history event if user is authenticated
    if current_user and current_user.id:
        user_event = PlaybackHistory(
            user_id=current_user.id,
            song_id=song_id,
            played_at=now,
            duration_played=duration,
        )
        db_session.add(user_event)

    db_session.commit()
    logger.info(
        "Recorded play for song %d (user_id=%s). Total plays: %d, Total duration: %.2f sec.",
        song_id,
        current_user.id if current_user else None,
        global_hist.play_count,
        global_hist.play_duration,
    )


def record_skip(
    current_user: CurrentUser,
    song_id: int,
    db_session: Session,
) -> None:
    """Records a song skip event.

    Args:
        current_user: Active CurrentUser instance.
        song_id: Database key of the song.
        db_session: Database session.
    """
    global_hist = _get_or_create_global_history(song_id, db_session)
    global_hist.skips += 1

    db_session.commit()
    logger.info(
        "Recorded skip for song %d (user_id=%s). Total skips: %d.",
        song_id,
        current_user.id if current_user else None,
        global_hist.skips,
    )


def set_like_status(
    current_user: CurrentUser,
    song_id: int,
    liked: bool,
    db_session: Session,
) -> None:
    """Sets the user and global liked state of a song.

    Args:
        current_user: Active CurrentUser instance.
        song_id: Database key of the song.
        liked: True to like, False to unlike.
        db_session: Database session.
    """
    global_hist = _get_or_create_global_history(song_id, db_session)
    global_hist.likes = liked

    # Update user-owned LikedSong table if user is authenticated
    if current_user and current_user.id:
        existing = (
            db_session.query(LikedSong)
            .filter_by(user_id=current_user.id, song_id=song_id)
            .first()
        )
        if liked and not existing:
            new_like = LikedSong(
                user_id=current_user.id,
                song_id=song_id,
                liked_at=datetime.utcnow(),
            )
            db_session.add(new_like)
        elif not liked and existing:
            db_session.delete(existing)

    db_session.commit()
    logger.info(
        "Recorded like status for song %d (user_id=%s): %s.",
        song_id,
        current_user.id if current_user else None,
        liked,
    )


def get_history(
    current_user: CurrentUser,
    song_id: int,
    db_session: Session,
) -> dict | None:
    """Fetches listening history statistics for a song.

    Args:
        current_user: Active CurrentUser instance.
        song_id: Database key of the song.
        db_session: Database session.

    Returns:
        Dict of history attributes, or None if the song has no history record.
    """
    song = db_session.get(Song, song_id)
    if not song:
        logger.error("Requested history for non-existent song_id %d", song_id)
        return None

    global_hist = db_session.get(ListeningHistory, song_id)
    if not global_hist:
        return None

    user_liked = global_hist.likes
    if current_user and current_user.id:
        user_like_rec = (
            db_session.query(LikedSong)
            .filter_by(user_id=current_user.id, song_id=song_id)
            .first()
        )
        user_liked = user_like_rec is not None

    return {
        "song_id": global_hist.song_id,
        "play_count": global_hist.play_count,
        "skips": global_hist.skips,
        "likes": user_liked,
        "last_played": global_hist.last_played.isoformat() if global_hist.last_played else None,
        "play_duration": global_hist.play_duration,
    }


def get_user_liked_songs(
    current_user: CurrentUser,
    db_session: Session,
    limit: int = 50,
) -> list[dict]:
    """Retrieves list of liked songs for the active user."""
    if not current_user or not current_user.id:
        return []

    likes = (
        db_session.query(LikedSong)
        .filter(LikedSong.user_id == current_user.id)
        .order_by(LikedSong.liked_at.desc())
        .limit(limit)
        .all()
    )

    results = []
    for like in likes:
        song = db_session.get(Song, like.song_id)
        if song:
            results.append({
                "id": song.id,
                "title": song.title,
                "artist": song.artist,
                "album": song.album,
                "duration": song.duration,
                "liked_at": like.liked_at.isoformat() if like.liked_at else None,
            })
    return results


def get_user_playback_history(
    current_user: CurrentUser,
    db_session: Session,
    limit: int = 50,
) -> list[dict]:
    """Retrieves playback history entries for the active user."""
    if not current_user or not current_user.id:
        return []

    events = (
        db_session.query(PlaybackHistory)
        .filter(PlaybackHistory.user_id == current_user.id)
        .order_by(PlaybackHistory.played_at.desc())
        .limit(limit)
        .all()
    )

    results = []
    for evt in events:
        song = db_session.get(Song, evt.song_id)
        if song:
            results.append({
                "id": evt.id,
                "song_id": evt.song_id,
                "title": song.title,
                "artist": song.artist,
                "played_at": evt.played_at.isoformat() if evt.played_at else None,
                "duration_played": evt.duration_played,
            })
    return results
