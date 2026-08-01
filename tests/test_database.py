"""Unit tests for the database schema and operations."""

from datetime import datetime
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database.models import (
    AudioFeatures,
    Embeddings,
    LikedSong,
    ListeningHistory,
    MusicBrainzMetadata,
    PlaybackHistory,
    Playlist,
    QueueItem,
    SemanticTags,
    Song,
    TechnicalMetadata,
    User,
    UserPreferences,
)


def test_insert_song(db_session: Session) -> None:
    """Tests inserting a song and retrieving it."""
    song = Song(
        path="/music/song.mp3",
        hash="sha256-hash-value-12345",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        duration=180.0,
        original_genre="Pop",
    )
    db_session.add(song)
    db_session.commit()

    # Query the song
    retrieved = db_session.query(Song).filter_by(hash="sha256-hash-value-12345").first()
    assert retrieved is not None
    assert retrieved.title == "Test Song"
    assert retrieved.artist == "Test Artist"
    assert retrieved.path == "/music/song.mp3"


def test_duplicate_path_prevention(db_session: Session) -> None:
    """Verifies that inserting songs with duplicate paths raises an error."""
    song1 = Song(
        path="/music/song.mp3",
        hash="hash1",
        title="Song 1",
    )
    song2 = Song(
        path="/music/song.mp3",  # Duplicate path
        hash="hash2",
        title="Song 2",
    )

    db_session.add(song1)
    db_session.commit()

    db_session.add(song2)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_duplicate_hash_prevention(db_session: Session) -> None:
    """Verifies that inserting songs with duplicate file hashes raises an error."""
    song1 = Song(
        path="/music/song1.mp3",
        hash="duplicate_hash",
        title="Song 1",
    )
    song2 = Song(
        path="/music/song2.mp3",
        hash="duplicate_hash",  # Duplicate hash
        title="Song 2",
    )

    db_session.add(song1)
    db_session.commit()

    db_session.add(song2)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_song_relationships_and_cascade_delete(db_session: Session) -> None:
    """Tests that related metadata tables can be inserted and are cascadingly deleted."""
    song = Song(
        path="/music/cascade_test.mp3",
        hash="cascade_hash",
        title="Cascade Test Title",
    )
    db_session.add(song)
    db_session.commit()

    # Create associated entries
    tech = TechnicalMetadata(
        song_id=song.id,
        codec="mp3",
        bitrate=320,
        sample_rate=44100,
        channels=2,
        format="mp3",
    )
    features = AudioFeatures(
        song_id=song.id,
        bpm=120.0,
        mfcc=b"numpy_mfcc_bytes",
    )
    mb_meta = MusicBrainzMetadata(
        song_id=song.id,
        canonical_artist="Canonical Artist",
        musicbrainz_id="mb-id-1234",
    )
    embed = Embeddings(
        song_id=song.id,
        vector=b"embedding_vector_bytes",
    )
    semantic = SemanticTags(
        song_id=song.id,
        moods='["calm", "happy"]',
        energy="medium",
    )
    history = ListeningHistory(
        song_id=song.id,
        play_count=5,
        likes=True,
        last_played=datetime(2026, 7, 8, 12, 0, 0),
    )

    db_session.add_all([tech, features, mb_meta, embed, semantic, history])
    db_session.commit()

    # Refresh and verify relationship loading
    db_session.expire_all()
    song_db = db_session.get(Song, song.id)

    assert song_db.technical_metadata.codec == "mp3"
    assert song_db.audio_features.bpm == 120.0
    assert song_db.musicbrainz_metadata.canonical_artist == "Canonical Artist"
    assert song_db.embeddings.vector == b"embedding_vector_bytes"
    assert song_db.semantic_tags.energy == "medium"
    assert song_db.listening_history.play_count == 5

    # Verify rows exist in database
    assert db_session.query(TechnicalMetadata).filter_by(song_id=song.id).first() is not None
    assert db_session.query(ListeningHistory).filter_by(song_id=song.id).first() is not None

    # Delete the song and verify cascading deletes on child tables
    db_session.delete(song_db)
    db_session.commit()

    assert db_session.query(Song).filter_by(id=song.id).first() is None
    assert db_session.query(TechnicalMetadata).filter_by(song_id=song.id).first() is None
    assert db_session.query(AudioFeatures).filter_by(song_id=song.id).first() is None
    assert db_session.query(MusicBrainzMetadata).filter_by(song_id=song.id).first() is None
    assert db_session.query(Embeddings).filter_by(song_id=song.id).first() is None
    assert db_session.query(SemanticTags).filter_by(song_id=song.id).first() is None
    assert db_session.query(ListeningHistory).filter_by(song_id=song.id).first() is None


def test_user_creation_and_unique_username(db_session: Session) -> None:
    """Tests creating a User and verifying unique username constraint."""
    user1 = User(username="alice", display_name="Alice")
    db_session.add(user1)
    db_session.commit()

    retrieved = db_session.query(User).filter_by(username="alice").first()
    assert retrieved is not None
    assert retrieved.display_name == "Alice"
    assert retrieved.password_hash is None
    assert retrieved.is_active is True

    # Duplicate username check
    user2 = User(username="alice", display_name="Alice 2")
    db_session.add(user2)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_user_owned_entities_and_cascade_delete(db_session: Session) -> None:
    """Tests creating user-owned playlists, liked songs, history, queue, preferences and cascade delete."""
    user = User(username="bob", display_name="Bob")
    song = Song(path="/music/bob_song.mp3", hash="bob_hash", title="Bob Song")
    db_session.add_all([user, song])
    db_session.commit()

    # Create user-owned items
    playlist = Playlist(name="Bob's Jams", user_id=user.id)
    liked = LikedSong(user_id=user.id, song_id=song.id)
    history = PlaybackHistory(user_id=user.id, song_id=song.id, duration_played=120.5)
    queue = QueueItem(user_id=user.id, song_id=song.id, position=1)
    prefs = UserPreferences(user_id=user.id, theme="dark", volume=0.8)

    db_session.add_all([playlist, liked, history, queue, prefs])
    db_session.commit()

    db_session.expire_all()
    user_db = db_session.get(User, user.id)

    assert len(user_db.playlists) == 1
    assert user_db.playlists[0].name == "Bob's Jams"
    assert len(user_db.liked_songs) == 1
    assert user_db.liked_songs[0].song_id == song.id
    assert len(user_db.playback_history) == 1
    assert user_db.playback_history[0].duration_played == 120.5
    assert len(user_db.queue) == 1
    assert user_db.queue[0].position == 1
    assert user_db.preferences.theme == "dark"

    # Delete user and verify cascading deletes of user-owned state
    db_session.delete(user_db)
    db_session.commit()

    assert db_session.query(User).filter_by(id=user.id).first() is None
    assert db_session.query(Playlist).filter_by(user_id=user.id).first() is None
    assert db_session.query(LikedSong).filter_by(user_id=user.id).first() is None
    assert db_session.query(PlaybackHistory).filter_by(user_id=user.id).first() is None
    assert db_session.query(QueueItem).filter_by(user_id=user.id).first() is None
    assert db_session.query(UserPreferences).filter_by(user_id=user.id).first() is None

    # Global song must remain intact!
    assert db_session.query(Song).filter_by(id=song.id).first() is not None

