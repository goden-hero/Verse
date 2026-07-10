"""Unit tests for Phase 12 Listening History Tracking."""

import pytest
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import ListeningHistory, Song
from app.history import get_history, record_play, record_skip, set_like_status


@pytest.fixture
def test_song(db_session: Session) -> Song:
    """Fixture to create a test song in the DB."""
    song = Song(
        path="/path/track.mp3",
        hash="trackhash123",
        title="Track Title",
        artist="Track Artist",
        album="Track Album",
        duration=200.0,
    )
    db_session.add(song)
    db_session.commit()
    return song


def test_record_play(db_session: Session, test_song: Song) -> None:
    """Verifies recording plays initializes stats and accumulates duration and play counts."""
    # First play
    record_play(song_id=test_song.id, duration=45.5, db_session=db_session)

    history = db_session.get(ListeningHistory, test_song.id)
    assert history is not None
    assert history.play_count == 1
    assert history.play_duration == 45.5
    assert history.skips == 0
    assert history.likes is False
    assert isinstance(history.last_played, datetime)

    # Second play
    record_play(song_id=test_song.id, duration=15.0, db_session=db_session)
    db_session.expire(history)
    history = db_session.get(ListeningHistory, test_song.id)
    assert history.play_count == 2
    assert history.play_duration == 60.5


def test_record_play_negative_duration_raises_error(db_session: Session, test_song: Song) -> None:
    """Verifies that recording play with a negative duration raises a ValueError."""
    with pytest.raises(ValueError, match="duration cannot be negative"):
        record_play(song_id=test_song.id, duration=-5.0, db_session=db_session)


def test_record_play_invalid_song_raises_error(db_session: Session) -> None:
    """Verifies that recording play on a non-existent song raises a ValueError."""
    with pytest.raises(ValueError, match="does not exist"):
        record_play(song_id=99999, duration=10.0, db_session=db_session)


def test_record_skip(db_session: Session, test_song: Song) -> None:
    """Verifies that recording a skip increments skips count."""
    # First skip
    record_skip(song_id=test_song.id, db_session=db_session)
    history = db_session.get(ListeningHistory, test_song.id)
    assert history is not None
    assert history.skips == 1
    assert history.play_count == 0

    # Second skip
    record_skip(song_id=test_song.id, db_session=db_session)
    db_session.expire(history)
    history = db_session.get(ListeningHistory, test_song.id)
    assert history.skips == 2


def test_set_like_status(db_session: Session, test_song: Song) -> None:
    """Verifies set_like_status updates the boolean field in the database."""
    # Like
    set_like_status(song_id=test_song.id, liked=True, db_session=db_session)
    history = db_session.get(ListeningHistory, test_song.id)
    assert history is not None
    assert history.likes is True

    # Unlike
    set_like_status(song_id=test_song.id, liked=False, db_session=db_session)
    db_session.expire(history)
    history = db_session.get(ListeningHistory, test_song.id)
    assert history.likes is False


def test_get_history(db_session: Session, test_song: Song) -> None:
    """Verifies get_history retrieves formatted listening statistics dictionary or None."""
    # None when no history records exist
    history_dict = get_history(song_id=test_song.id, db_session=db_session)
    assert history_dict is None

    # Retrieve history after a play and skip
    record_play(song_id=test_song.id, duration=100.0, db_session=db_session)
    record_skip(song_id=test_song.id, db_session=db_session)

    history_dict = get_history(song_id=test_song.id, db_session=db_session)
    assert history_dict is not None
    assert history_dict["song_id"] == test_song.id
    assert history_dict["play_count"] == 1
    assert history_dict["skips"] == 1
    assert history_dict["play_duration"] == 100.0
    assert history_dict["likes"] is False
    assert history_dict["last_played"] is not None

    # None for invalid song ID
    assert get_history(song_id=99999, db_session=db_session) is None


def test_listening_history_cascade_delete(db_session: Session, test_song: Song) -> None:
    """Verifies cascading delete rules: deleting a Song removes its ListeningHistory record."""
    record_play(song_id=test_song.id, duration=10.0, db_session=db_session)
    assert db_session.get(ListeningHistory, test_song.id) is not None

    # Delete the song
    db_session.delete(test_song)
    db_session.commit()

    # ListeningHistory record should be gone
    assert db_session.get(ListeningHistory, test_song.id) is None
