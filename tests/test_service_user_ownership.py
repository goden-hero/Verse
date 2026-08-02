"""Comprehensive unit tests for Service Layer User Ownership Refactor and Multi-User Isolation."""

import pytest
from sqlalchemy.orm import Session
from app.database.models import User, Song
from app.identity import CurrentUser
from app.services.playlist import PlaylistService
from app.services.playback_session import PlaybackSessionService
from app.services.history import HistoryService
from app.services.queue import QueueService
from app.services.preferences import UserPreferencesService


@pytest.fixture
def users_and_song(db_session: Session) -> tuple[CurrentUser, CurrentUser, Song]:
    """Fixture initializing two distinct users and a shared library song."""
    u1 = User(id=10, username="user_alpha", display_name="User Alpha")
    u2 = User(id=20, username="user_beta", display_name="User Beta")
    song = Song(
        path="/music/synthwave.mp3",
        hash="hash_synth_123",
        title="Synthwave Midnight",
        artist="Retro Wave",
        duration=210.0,
    )
    db_session.add_all([u1, u2, song])
    db_session.commit()

    user_a = CurrentUser.from_user_model(u1)
    user_b = CurrentUser.from_user_model(u2)

    return user_a, user_b, song


def test_playlist_user_isolation(db_session: Session, users_and_song: tuple[CurrentUser, CurrentUser, Song]) -> None:
    """Verifies that playlists are completely isolated between users."""
    user_a, user_b, song = users_and_song

    # User A creates a playlist
    p_a_id = PlaylistService.create_playlist(
        current_user=user_a,
        name="User A Playlist",
        description="Private to A",
        session=db_session,
    )
    PlaylistService.add_songs_to_playlist(
        current_user=user_a,
        playlist_id=p_a_id,
        song_ids=[song.id],
        session=db_session,
    )

    # User B creates a playlist with the exact same name
    p_b_id = PlaylistService.create_playlist(
        current_user=user_b,
        name="User A Playlist",
        description="Private to B",
        session=db_session,
    )

    # 1. Verify User A sees only A's playlist
    playlists_a = PlaylistService.get_playlists(current_user=user_a, session=db_session)
    assert len(playlists_a) == 1
    assert playlists_a[0]["id"] == p_a_id

    # 2. Verify User B sees only B's playlist
    playlists_b = PlaylistService.get_playlists(current_user=user_b, session=db_session)
    assert len(playlists_b) == 1
    assert playlists_b[0]["id"] == p_b_id

    # 3. Verify User B CANNOT fetch details of User A's playlist (returns None)
    assert PlaylistService.get_playlist_details(current_user=user_b, playlist_id=p_a_id, session=db_session) is None

    # 4. Verify User B CANNOT update User A's playlist (returns False)
    updated = PlaylistService.update_playlist(
        current_user=user_b,
        playlist_id=p_a_id,
        name="Hacked Name",
        session=db_session,
    )
    assert updated is False

    # 5. Verify User B CANNOT delete User A's playlist
    PlaylistService.delete_playlist(current_user=user_b, playlist_id=p_a_id, session=db_session)
    assert PlaylistService.get_playlist_details(current_user=user_a, playlist_id=p_a_id, session=db_session) is not None


def test_liked_songs_isolation(db_session: Session, users_and_song: tuple[CurrentUser, CurrentUser, Song]) -> None:
    """Verifies liked songs are stored and retrieved per user."""
    user_a, user_b, song = users_and_song

    # User A likes the song
    HistoryService.set_like_status(current_user=user_a, song_id=song.id, liked=True, session=db_session)

    # User A's history indicates liked=True
    hist_a = HistoryService.get_history(current_user=user_a, song_id=song.id, session=db_session)
    assert hist_a["likes"] is True

    # User B's history indicates liked=False
    hist_b = HistoryService.get_history(current_user=user_b, song_id=song.id, session=db_session)
    assert hist_b["likes"] is False

    # Check user liked songs lists
    liked_a = HistoryService.get_user_liked_songs(current_user=user_a, session=db_session)
    liked_b = HistoryService.get_user_liked_songs(current_user=user_b, session=db_session)
    assert len(liked_a) == 1
    assert liked_a[0]["id"] == song.id
    assert len(liked_b) == 0


def test_playback_history_isolation(db_session: Session, users_and_song: tuple[CurrentUser, CurrentUser, Song]) -> None:
    """Verifies listening play events are logged strictly per user."""
    user_a, user_b, song = users_and_song

    # Record play for User A
    HistoryService.record_play(current_user=user_a, song_id=song.id, duration=120.0, session=db_session)

    events_a = HistoryService.get_user_playback_history(current_user=user_a, session=db_session)
    events_b = HistoryService.get_user_playback_history(current_user=user_b, session=db_session)

    assert len(events_a) == 1
    assert events_a[0]["song_id"] == song.id
    assert len(events_b) == 0


def test_queue_isolation(db_session: Session, users_and_song: tuple[CurrentUser, CurrentUser, Song]) -> None:
    """Verifies playback queue is isolated per user."""
    user_a, user_b, song = users_and_song

    QueueService.enqueue(current_user=user_a, song_id=song.id, session=db_session)

    q_a = QueueService.get_queue(current_user=user_a, session=db_session)
    q_b = QueueService.get_queue(current_user=user_b, session=db_session)

    assert len(q_a) == 1
    assert q_a[0]["song_id"] == song.id
    assert len(q_b) == 0

    QueueService.clear_queue(current_user=user_a, session=db_session)
    assert len(QueueService.get_queue(current_user=user_a, session=db_session)) == 0


def test_preferences_isolation(db_session: Session, users_and_song: tuple[CurrentUser, CurrentUser, Song]) -> None:
    """Verifies user settings and preferences are isolated."""
    user_a, user_b, _ = users_and_song

    UserPreferencesService.save_preferences(
        current_user=user_a,
        prefs={"theme": "cyberpunk", "volume": 0.85},
        session=db_session,
    )

    prefs_a = UserPreferencesService.get_preferences(current_user=user_a, session=db_session)
    prefs_b = UserPreferencesService.get_preferences(current_user=user_b, session=db_session)

    assert prefs_a["theme"] == "cyberpunk"
    assert prefs_a["volume"] == 0.85

    assert prefs_b["theme"] == "dark"
    assert prefs_b["volume"] == 1.0


def test_e2e_user_ownership_api_isolation(db_session: Session) -> None:
    """End-to-End API User Ownership Isolation Test:
    User A -> Creates playlist -> User B -> GET playlist -> 404
    User B -> Creates playlist with same name -> Success
    User A -> List playlists -> Only A's playlist
    """
    from fastapi.testclient import TestClient
    from app.api.server import app
    from app.api.dependencies import get_db, get_current_user

    u1 = User(id=101, username="user_a", display_name="User A")
    u2 = User(id=102, username="user_b", display_name="User B")
    song = Song(path="/e2e.mp3", hash="e2e_hash", title="E2E Track", artist="E2E Artist", duration=180.0)
    db_session.add_all([u1, u2, song])
    db_session.commit()

    user_a = CurrentUser.from_user_model(u1)
    user_b = CurrentUser.from_user_model(u2)

    app.dependency_overrides[get_db] = lambda: db_session

    # Client A acting as User A
    app.dependency_overrides[get_current_user] = lambda: user_a
    client_a = TestClient(app)

    # 1. User A creates a playlist
    resp_a = client_a.post("/api/v1/playlists", json={"name": "Night Vibes", "song_ids": [song.id]})
    assert resp_a.status_code == 201
    pl_a_id = resp_a.json()["id"]

    # Client B acting as User B
    app.dependency_overrides[get_current_user] = lambda: user_b
    client_b = TestClient(app)

    # 2. User B tries to GET User A's playlist -> 404
    resp_get_b = client_b.get(f"/api/v1/playlists/{pl_a_id}")
    assert resp_get_b.status_code == 404

    # 3. User B creates playlist with the same name -> 201 Success
    resp_create_b = client_b.post("/api/v1/playlists", json={"name": "Night Vibes", "song_ids": [song.id]})
    assert resp_create_b.status_code == 201
    pl_b_id = resp_create_b.json()["id"]
    assert pl_b_id != pl_a_id

    # 4. User A lists playlists -> sees only A's playlist
    app.dependency_overrides[get_current_user] = lambda: user_a
    resp_list_a = client_a.get("/api/v1/playlists")
    assert resp_list_a.status_code == 200
    list_a = resp_list_a.json()
    assert len(list_a) == 1
    assert list_a[0]["id"] == pl_a_id
    assert list_a[0]["name"] == "Night Vibes"

    app.dependency_overrides.clear()


def test_playback_session_multi_user_isolation(db_session: Session, users_and_song: tuple[CurrentUser, CurrentUser, Song]) -> None:
    """Verifies playback sessions remain strictly independent between users."""
    user_a, user_b, song = users_and_song

    pl_a = PlaylistService.create_playlist(current_user=user_a, name="A Session PL", session=db_session)
    pl_b = PlaylistService.create_playlist(current_user=user_b, name="B Session PL", session=db_session)

    # User A starts session
    sess_a = PlaybackSessionService.start_session(
        current_user=user_a,
        playlist_id=pl_a,
        song_index=0,
        position=10.0,
        session=db_session,
    )

    # User B starts session
    sess_b = PlaybackSessionService.start_session(
        current_user=user_b,
        playlist_id=pl_b,
        song_index=2,
        position=45.0,
        session=db_session,
    )

    assert sess_a.id != sess_b.id

    # User B attempts to update User A's session -> returns None
    hacked_update = PlaybackSessionService.update_progress(
        current_user=user_b,
        session_id=sess_a.id,
        song_index=99,
        position=999.0,
        session=db_session,
    )
    assert hacked_update is None

    # Verify User A's session was unaffected
    reloaded_a = PlaybackSessionService.get_continue_listening(current_user=user_a, session=db_session)
    assert len(reloaded_a) == 1
    assert reloaded_a[0]["current_song_index"] == 0
    assert reloaded_a[0]["current_position"] == 10.0


def test_assistant_multi_user_isolation(db_session: Session, users_and_song: tuple[CurrentUser, CurrentUser, Song]) -> None:
    """Verifies AI Assistant generates independent user-owned playlists for different users."""
    from unittest.mock import patch
    from app.services.assistant import AssistantService

    user_a, user_b, song = users_and_song

    mock_plan = {
        "plan": [
            {
                "action": "generate_playlist",
                "playlist_name": "Chill Evening",
                "strategy": "automatic",
                "filters": {"moods": ["chill"]},
                "target_length": 5,
            }
        ]
    }

    with patch("app.assistant.parser.LLMParser.parse_intent", return_value=mock_plan):
        res_a = AssistantService.process_chat(current_user=user_a, message="Make a chill mix", session=db_session)
        res_b = AssistantService.process_chat(current_user=user_b, message="Make a chill mix", session=db_session)

    assert res_a["success"] is True
    assert res_b["success"] is True

    # Both succeed with different playlist IDs
    pl_a = res_a["playlist"]
    pl_b = res_b["playlist"]
    assert pl_a is not None and pl_b is not None
    assert pl_a["id"] != pl_b["id"]

    # User A sees only A's playlist; User B sees only B's playlist
    lists_a = PlaylistService.get_playlists(current_user=user_a, session=db_session)
    lists_b = PlaylistService.get_playlists(current_user=user_b, session=db_session)
    assert len(lists_a) == 1
    assert lists_a[0]["id"] == pl_a["id"]
    assert len(lists_b) == 1
    assert lists_b[0]["id"] == pl_b["id"]


def test_queue_multi_user_distinct_songs_isolation(db_session: Session) -> None:
    """Verifies User A enqueues Song 1, User B enqueues Song 2 -> GET queue returns only their own."""
    u1 = User(id=301, username="user_q1", display_name="User Q1")
    u2 = User(id=302, username="user_q2", display_name="User Q2")
    s1 = Song(path="/q1.mp3", hash="q1_hash", title="Song 1", artist="Artist 1", duration=180.0)
    s2 = Song(path="/q2.mp3", hash="q2_hash", title="Song 2", artist="Artist 2", duration=200.0)
    db_session.add_all([u1, u2, s1, s2])
    db_session.commit()

    user_a = CurrentUser.from_user_model(u1)
    user_b = CurrentUser.from_user_model(u2)

    QueueService.enqueue(current_user=user_a, song_id=s1.id, session=db_session)
    QueueService.enqueue(current_user=user_b, song_id=s2.id, session=db_session)

    q_a = QueueService.get_queue(current_user=user_a, session=db_session)
    q_b = QueueService.get_queue(current_user=user_b, session=db_session)

    assert len(q_a) == 1
    assert q_a[0]["song_id"] == s1.id
    assert len(q_b) == 1
    assert q_b[0]["song_id"] == s2.id


def test_history_multi_user_isolation_empty_check(db_session: Session) -> None:
    """Verifies User A plays song, User B plays nothing -> User B history remains empty."""
    u1 = User(id=401, username="user_h1", display_name="User H1")
    u2 = User(id=402, username="user_h2", display_name="User H2")
    song = Song(path="/h1.mp3", hash="h1_hash", title="History Track", artist="Artist H", duration=190.0)
    db_session.add_all([u1, u2, song])
    db_session.commit()

    user_a = CurrentUser.from_user_model(u1)
    user_b = CurrentUser.from_user_model(u2)

    HistoryService.record_play(current_user=user_a, song_id=song.id, duration=190.0, session=db_session)

    hist_a = HistoryService.get_user_playback_history(current_user=user_a, session=db_session)
    hist_b = HistoryService.get_user_playback_history(current_user=user_b, session=db_session)

    assert len(hist_a) == 1
    assert len(hist_b) == 0


def test_recommendation_shared_library_user_ownership(db_session: Session, users_and_song: tuple[CurrentUser, CurrentUser, Song]) -> None:
    """Verifies recommendations search global shared library, but generated playlists are user-owned."""
    import json
    from app.database.models import SemanticTags

    user_a, user_b, song = users_and_song

    tag = SemanticTags(song_id=song.id, moods=json.dumps(["synthwave"]), energy="high")
    db_session.add(tag)
    db_session.commit()

    # Both users generate playlist from shared global library song
    pl_a_id = PlaylistService.generate_playlist(
        current_user=user_a,
        name="Shared Rec A",
        strategy="hybrid",
        filters={"moods": ["synthwave"]},
        target_length=1,
        session=db_session,
        enable_naming=False,
    )["id"]

    pl_b_id = PlaylistService.generate_playlist(
        current_user=user_b,
        name="Shared Rec B",
        strategy="hybrid",
        filters={"moods": ["synthwave"]},
        target_length=1,
        session=db_session,
        enable_naming=False,
    )["id"]

    assert pl_a_id != pl_b_id

    # Check that both playlists reference the same global song
    songs_a = PlaylistService.get_playlist_songs(current_user=user_a, playlist_id=pl_a_id, session=db_session)
    songs_b = PlaylistService.get_playlist_songs(current_user=user_b, playlist_id=pl_b_id, session=db_session)

    assert len(songs_a) == 1
    assert len(songs_b) == 1
    assert songs_a[0]["id"] == song.id
    assert songs_b[0]["id"] == song.id

