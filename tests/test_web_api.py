import pytest
import sys
from fastapi.testclient import TestClient
from app.api.server import app
from app.api.dependencies import get_db
from app.database.models import Song
from app.main import main

from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from app.database.models import Base

@pytest.fixture(scope="function")
def db_engine():
    """Local fixture overriding conftest.py to set check_same_thread=False and StaticPool for FastAPI compatibility."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def api_client(db_session):
    """Overrides the database dependency and returns a FastAPI TestClient."""
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()

def test_openapi_docs(api_client):
    """Tests that OpenAPI docs endpoints are mounted and accessible."""
    resp = api_client.get("/docs")
    assert resp.status_code == 200
    resp = api_client.get("/redoc")
    assert resp.status_code == 200

def test_cli_command_aliases(mocker):
    """Tests that CLI parser registers both 'web' and 'serve' commands."""
    # Mock the uvicorn.run call in app.main
    mock_run = mocker.patch("uvicorn.run")
    
    # Save original argv
    orig_argv = sys.argv
    
    try:
        # Check 'web' command
        sys.argv = ["app.main", "web", "--port", "9000"]
        main()
        mock_run.assert_called_with("app.api.server:app", host="127.0.0.1", port=9000, reload=False)
        
        # Check 'serve' command
        mock_run.reset_mock()
        sys.argv = ["app.main", "serve", "--port", "9500"]
        main()
        mock_run.assert_called_with("app.api.server:app", host="127.0.0.1", port=9500, reload=False)
    finally:
        sys.argv = orig_argv

def test_playback_history_endpoints(api_client, db_session):
    """Tests recording play, skip, and like events via API routes."""
    # Create a dummy song
    song = Song(
        path="/some/song.mp3",
        hash="hash123",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        duration=120.0
    )
    db_session.add(song)
    db_session.commit()
    
    # Test play history
    resp = api_client.post("/api/v1/history/play", json={"song_id": song.id, "duration": 50.0})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    
    # Test skip history
    resp = api_client.post("/api/v1/history/skip", json={"song_id": song.id})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    
    # Test like status
    resp = api_client.post("/api/v1/history/like", json={"song_id": song.id, "liked": True})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    
    # Verify in DB
    from app.database.models import ListeningHistory
    lh = db_session.query(ListeningHistory).filter_by(song_id=song.id).first()
    assert lh is not None
    assert lh.play_count == 1
    assert lh.skips == 1
    assert lh.likes is True

def test_assistant_chat_skeleton(api_client, monkeypatch):
    """Tests the assistant chat endpoint returns structured output."""
    from app.assistant import LLMParser
    def mock_parse_intent(self, prompt, session):
        return {
            "intent": "search",
            "confidence": 0.9,
            "plan": [{"action": "search_library", "query": "hello"}]
        }
    monkeypatch.setattr(LLMParser, "parse_intent", mock_parse_intent)

    resp = api_client.post("/api/v1/assistant/chat", json={"message": "hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True

def test_assistant_playlist_regeneration_skeleton(api_client):
    """Tests the assistant playlist regeneration endpoint."""
    resp = api_client.post("/api/v1/playlists/123/regenerate")
    assert resp.status_code == 200
    data = resp.json()
    assert "Fresh" in data["name"]
    assert "songs" in data


def test_get_single_song(api_client, db_session):
    """Tests GET /api/v1/songs/{id} metadata lookup."""
    song = Song(path="/file.mp3", hash="h123", title="Single Song", artist="Artist S", album="Album S", duration=150.0)
    db_session.add(song)
    db_session.commit()

    # Valid ID
    resp = api_client.get(f"/api/v1/songs/{song.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == song.id
    assert data["title"] == "Single Song"
    assert data["artist"] == "Artist S"
    assert "path" not in data  # Path must be hidden from frontend

    # Invalid ID
    resp_invalid = api_client.get("/api/v1/songs/999999")
    assert resp_invalid.status_code == 404

def test_stream_song(api_client, db_session, tmp_path):
    """Tests GET /api/v1/songs/{id}/stream for full responses and HTTP Range Requests (206 Partial Content)."""
    # Create dummy audio file
    audio_file = tmp_path / "test_audio.mp3"
    content = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    audio_file.write_bytes(content)

    song = Song(path=str(audio_file), hash="stream_hash", title="Stream Song", artist="Artist Str", duration=10.0)
    db_session.add(song)
    db_session.commit()

    # 1. Full stream request without Range header
    resp_full = api_client.get(f"/api/v1/songs/{song.id}/stream")
    assert resp_full.status_code == 200
    assert resp_full.content == content
    assert resp_full.headers["Accept-Ranges"] == "bytes"

    # 2. HTTP Range Request for bytes 0-9
    resp_range = api_client.get(f"/api/v1/songs/{song.id}/stream", headers={"Range": "bytes=0-9"})
    assert resp_range.status_code == 206
    assert resp_range.content == content[:10]
    assert resp_range.headers["Content-Range"] == f"bytes 0-9/{len(content)}"
    assert resp_range.headers["Content-Length"] == "10"

def test_search_empty_query_via_api(api_client):
    """Tests GET /api/v1/search with empty query returns empty list."""
    resp = api_client.get("/api/v1/search?q=   ")
    assert resp.status_code == 200
    assert resp.json() == []

def test_search_priority_ranking_via_api(api_client, db_session):
    """Tests GET /api/v1/search returns ranked results matching the 5 priority levels."""
    song_p5 = Song(path="/p5.mp3", hash="h5", title="Another Track", artist="Rock Star")
    song_p3 = Song(path="/p3.mp3", hash="h3", title="We Will Rock You", artist="Artist B")
    song_p1 = Song(path="/p1.mp3", hash="h1", title="Rock", artist="Artist A")
    song_p4 = Song(path="/p4.mp3", hash="h4", title="Some Title", artist="Rock")
    song_p2 = Song(path="/p2.mp3", hash="h2", title="Rock and Roll", artist="Artist C")

    db_session.add_all([song_p5, song_p3, song_p1, song_p4, song_p2])
    db_session.commit()

    resp = api_client.get("/api/v1/search?q=rock")
    assert resp.status_code == 200
    results = resp.json()

    assert len(results) == 5
    assert results[0]["title"] == "Rock"             # P1: Exact title
    assert results[1]["title"] == "Rock and Roll"    # P2: Title prefix
    assert results[2]["title"] == "We Will Rock You"  # P3: Partial title
    assert results[3]["artist"] == "Rock"            # P4: Exact artist
    assert results[4]["artist"] == "Rock Star"       # P5: Partial artist

def test_generate_playlist_preview_endpoint(api_client, db_session):
    """Tests POST /api/v1/playlists/generate preview generation."""
    song = Song(path="/s1.mp3", hash="h1", title="Sample Song", artist="Artist S", duration=120.0)
    db_session.add(song)
    db_session.commit()

    payload = {
        "strategy": "automatic",
        "seed_type": "current song",
        "seed_value": "",
        "limit": 10
    }
    resp = api_client.post("/api/v1/playlists/generate", json=payload)
    assert resp.status_code == 200
    songs = resp.json()
    assert isinstance(songs, list)
    assert len(songs) >= 1
    assert songs[0]["title"] == "Sample Song"

def test_assistant_chat_structured_response(api_client, db_session, monkeypatch):
    """Tests POST /api/v1/assistant/chat returning structured JSON with playlist preview."""
    import json
    from app.database.models import SemanticTags
    song = Song(path="/rain.mp3", hash="hr", title="Rainy Days", artist="Chill Artist", duration=180.0)
    db_session.add(song)
    db_session.commit()

    tag = SemanticTags(song_id=song.id, moods=json.dumps(["calm"]), energy="low")
    db_session.add(tag)
    db_session.commit()


    # Mock LLMParser to simulate intent parsing without needing a running Ollama server
    from app.assistant import LLMParser
    def mock_parse_intent(self, prompt, session):
        return {
            "intent": "playlist_generation",
            "confidence": 0.95,
            "plan": [
                {
                    "action": "generate_playlist",
                    "playlist_name": "Rainy Evening Mix",
                    "strategy": "hybrid",
                    "filters": {"moods": ["calm"]},
                    "target_length": 10
                }
            ]
        }
    monkeypatch.setattr(LLMParser, "parse_intent", mock_parse_intent)

    resp = api_client.post("/api/v1/assistant/chat", json={"message": "Songs for a rainy evening"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "playlist" in data and data["playlist"] is not None
    assert data["playlist"]["name"] == "Rainy Evening Mix"
    assert data["playlist"]["songs_count"] == 1
    assert data["playlist"]["songs"][0]["title"] == "Rainy Days"

def test_playlist_management_full_flow(api_client, db_session):
    """Tests POST /api/v1/playlists, GET /api/v1/playlists, and GET /api/v1/playlists/{id}/songs."""
    song = Song(path="/track.mp3", hash="htrack", title="Track One", artist="Artist One", duration=210.0)
    db_session.add(song)
    db_session.commit()

    # 1. Create Playlist
    create_resp = api_client.post("/api/v1/playlists", json={"name": "Chill Beats", "song_ids": [song.id]})
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    playlist_id = created_data["id"]

    # 2. List Playlists
    list_resp = api_client.get("/api/v1/playlists")
    assert list_resp.status_code == 200
    playlists = list_resp.json()
    target_pl = next((p for p in playlists if p["id"] == playlist_id), None)
    assert target_pl is not None
    assert target_pl["name"] == "Chill Beats"
    assert target_pl["songs_count"] == 1

    # 3. Fetch Playlist Songs
    songs_resp = api_client.get(f"/api/v1/playlists/{playlist_id}/songs")
    assert songs_resp.status_code == 200
    p_songs = songs_resp.json()
    assert len(p_songs) == 1
    assert p_songs[0]["id"] == song.id
    assert p_songs[0]["title"] == "Track One"





