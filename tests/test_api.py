import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from app.api.server import app
from app.api.dependencies import get_db
from app.database.models import Base, Song

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

def test_get_songs_empty(api_client):
    """Tests GET /api/v1/songs when library is empty."""
    response = api_client.get("/api/v1/songs")
    assert response.status_code == 200
    data = response.json()
    assert data["songs"] == []
    assert data["total_count"] == 0
    assert data["page"] == 1
    assert data["page_size"] == 100

def test_get_songs_paginated(api_client, db_session):
    """Tests GET /api/v1/songs pagination and response fields."""
    # Insert mock songs
    song1 = Song(
        path="/path/to/song1.mp3",
        hash="hash1",
        title="Abc Song",
        artist="Artist A",
        album="Album X",
        duration=180.5,
        original_genre="Pop",
        cover_art=b"fake_artwork"
    )
    song2 = Song(
        path="/path/to/song2.mp3",
        hash="hash2",
        title="Xyz Song",
        artist="Artist B",
        album="Album Y",
        duration=210.2,
        original_genre="Rock",
        cover_art=None
    )
    db_session.add_all([song1, song2])
    db_session.commit()

    # Query page 1 with page_size 1
    response = api_client.get("/api/v1/songs?page=1&page_size=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["songs"]) == 1
    assert data["total_count"] == 2
    assert data["page"] == 1
    assert data["page_size"] == 1

    first_song = data["songs"][0]
    assert first_song["title"] == "Abc Song"
    assert first_song["artist"] == "Artist A"
    assert first_song["album"] == "Album X"
    assert first_song["duration"] == 180.5
    assert first_song["genre"] == "Pop"
    assert first_song["artwork_available"] is True

    # Query page 2 with page_size 1
    response = api_client.get("/api/v1/songs?page=2&page_size=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["songs"]) == 1
    assert data["total_count"] == 2
    assert data["page"] == 2
    assert data["page_size"] == 1

    second_song = data["songs"][0]
    assert second_song["title"] == "Xyz Song"
    assert second_song["artist"] == "Artist B"
    assert second_song["artwork_available"] is False

def test_search_empty_query(api_client):
    """Tests GET /api/v1/search with an empty or whitespace query."""
    response = api_client.get("/api/v1/search?q=  ")
    assert response.status_code == 200
    assert response.json() == []

def test_search_priority_ranking(api_client, db_session):
    """Tests that search results are ranked according to specifications."""
    # Create songs to match the 5 priorities for search query "blue"
    # Priority 5: Partial artist match
    song_p5 = Song(path="/p5.mp3", hash="h5", title="Some Song", artist="Blue Oyster Cult")
    # Priority 3: Partial title match
    song_p3 = Song(path="/p3.mp3", hash="h3", title="Out of the Blue", artist="Artist C")
    # Priority 1: Exact title match
    song_p1 = Song(path="/p1.mp3", hash="h1", title="Blue", artist="Artist A")
    # Priority 4: Exact artist match
    song_p4 = Song(path="/p4.mp3", hash="h4", title="Another Song", artist="Blue")
    # Priority 2: Title prefix match
    song_p2 = Song(path="/p2.mp3", hash="h2", title="Blue Moon", artist="Artist B")

    db_session.add_all([song_p5, song_p3, song_p1, song_p4, song_p2])
    db_session.commit()

    response = api_client.get("/api/v1/search?q=blue")
    assert response.status_code == 200
    results = response.json()
    
    # We expect 5 results ordered as: P1, P2, P3, P4, P5
    assert len(results) == 5
    assert results[0]["title"] == "Blue"             # P1
    assert results[1]["title"] == "Blue Moon"        # P2
    assert results[2]["title"] == "Out of the Blue"  # P3
    assert results[3]["artist"] == "Blue"            # P4
    assert results[4]["artist"] == "Blue Oyster Cult" # P5

def test_playlists_flow(api_client, db_session):
    """Tests the full playlist workflow: preview generation, saving, listing, and fetching songs."""
    # 1. Add mock songs and semantic tags
    song1 = Song(path="/s1.mp3", hash="hash1", title="Happy Song", artist="Artist A", duration=120)
    song2 = Song(path="/s2.mp3", hash="hash2", title="Sad Song", artist="Artist B", duration=150)
    db_session.add_all([song1, song2])
    db_session.commit()

    from app.database.models import SemanticTags
    tag1 = SemanticTags(song_id=song1.id, moods='["happy"]', activities='["studying"]', energy="high")
    tag2 = SemanticTags(song_id=song2.id, moods='["sad"]', activities='["sleeping"]', energy="low")
    db_session.add_all([tag1, tag2])
    db_session.commit()

    # 2. POST /api/v1/playlists/generate (Preview)
    req_payload = {
        "strategy": "content",
        "seed_type": "mood",
        "seed_value": "happy",
        "limit": 10
    }
    response = api_client.post("/api/v1/playlists/generate", json=req_payload)
    assert response.status_code == 200
    songs_preview = response.json()
    # It should match 'Happy Song' due to happy mood filter
    assert len(songs_preview) >= 1
    assert songs_preview[0]["title"] == "Happy Song"

    # 3. POST /api/v1/playlists (Save)
    save_payload = {
        "name": "My Happy List",
        "song_ids": [song1.id]
    }
    response = api_client.post("/api/v1/playlists", json=save_payload)
    assert response.status_code == 201
    save_data = response.json()
    playlist_id = save_data["id"]
    assert playlist_id is not None
    assert save_data["name"] == "My Happy List"

    # 4. GET /api/v1/playlists (List)
    response = api_client.get("/api/v1/playlists")
    assert response.status_code == 200
    playlists_list = response.json()
    assert len(playlists_list) >= 1
    target = next(p for p in playlists_list if p["id"] == playlist_id)
    assert target["name"] == "My Happy List"
    assert target["songs_count"] == 1

    # 5. GET /api/v1/playlists/{id}/songs (Get songs)
    response = api_client.get(f"/api/v1/playlists/{playlist_id}/songs")
    assert response.status_code == 200
    playlist_songs = response.json()
    assert len(playlist_songs) == 1
    assert playlist_songs[0]["title"] == "Happy Song"

def test_song_artwork(api_client, db_session):
    """Tests the GET /api/v1/songs/{id}/artwork endpoint."""
    # 1. Song with no artwork
    song_no_art = Song(path="/no_art.mp3", hash="no_art_hash", title="No Art", artist="A", cover_art=None)
    # 2. Song with mock artwork bytes
    mock_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    song_with_art = Song(path="/with_art.mp3", hash="with_art_hash", title="With Art", artist="B", cover_art=mock_bytes)
    db_session.add_all([song_no_art, song_with_art])
    db_session.commit()

    # Get artwork for song without art -> 404
    resp_no_art = api_client.get(f"/api/v1/songs/{song_no_art.id}/artwork")
    assert resp_no_art.status_code == 404

    # Get artwork for song with art -> 200 and correct bytes
    resp_with_art = api_client.get(f"/api/v1/songs/{song_with_art.id}/artwork")
    assert resp_with_art.status_code == 200
    assert resp_with_art.content == mock_bytes
    assert resp_with_art.headers["content-type"] == "image/jpeg"
