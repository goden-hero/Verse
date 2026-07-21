"""API Integration tests for Playlist Management System REST endpoints."""

import io
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.api.server import app
from app.database.models import Song
from app.services.playlist import PlaylistService

from app.api.dependencies import get_db

client = TestClient(app)


def test_playlist_api_endpoints_full_flow(db_session: Session):
    """Integration test covering playlist CRUD, session tracking, resume, stats, and cover streaming."""
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    # 1. Create test song
    img = Image.new("RGB", (100, 100), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    song = Song(
        path="/fake/path/song_api.mp3",
        hash="hash_api_1",
        title="API Song Title",
        artist="API Artist",
        album="API Album",
        duration=180.0,
        cover_art=buf.getvalue(),
    )
    db_session.add(song)
    db_session.commit()

    # 2. Create playlist via POST /api/v1/playlists
    create_resp = client.post("/api/v1/playlists", json={
        "name": "API Test Playlist",
        "song_ids": [song.id]
    })
    assert create_resp.status_code == 201, f"Response text: {create_resp.text}"
    playlist_id = create_resp.json()["id"]

    # 3. Get list via GET /api/v1/playlists
    list_resp = client.get("/api/v1/playlists")
    assert list_resp.status_code == 200
    playlists = list_resp.json()
    assert any(p["id"] == playlist_id for p in playlists)

    # 4. Get detail via GET /api/v1/playlists/{id}
    detail_resp = client.get(f"/api/v1/playlists/{playlist_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["name"] == "API Test Playlist"
    assert len(detail["songs"]) == 1
    assert detail["songs"][0]["title"] == "API Song Title"

    # 5. Get stats via GET /api/v1/playlists/{id}/stats
    stats_resp = client.get(f"/api/v1/playlists/{playlist_id}/stats")
    assert stats_resp.status_code == 200
    assert stats_resp.json()["play_count"] == 0

    # 6. Stream cover via GET /api/v1/playlists/{id}/cover
    cover_resp = client.get(f"/api/v1/playlists/{playlist_id}/cover")
    assert cover_resp.status_code == 200
    assert cover_resp.headers["content-type"] == "image/jpeg"
    assert len(cover_resp.content) > 0

    # 7. Start playback session via POST /api/v1/playlists/{id}/play
    play_resp = client.post(f"/api/v1/playlists/{playlist_id}/play", json={
        "song_index": 0,
        "position": 12.5
    })
    assert play_resp.status_code == 200
    session_data = play_resp.json()
    session_id = session_data["session_id"]
    assert session_data["current_song_index"] == 0
    assert session_data["current_position"] == 12.5

    # 8. Sync progress via PUT /api/v1/playlists/{id}/progress
    prog_resp = client.put(f"/api/v1/playlists/{playlist_id}/progress?session_id={session_id}", json={
        "song_index": 0,
        "position": 60.0,
        "completed": False
    })
    assert prog_resp.status_code == 200

    # 9. Get Continue Listening via GET /api/v1/playlists/continue-listening
    cont_resp = client.get("/api/v1/playlists/continue-listening")
    assert cont_resp.status_code == 200
    cont_list = cont_resp.json()
    assert len(cont_list) >= 1
    assert cont_list[0]["playlist_id"] == playlist_id
    assert cont_list[0]["current_position"] == 60.0

    # 10. Resume playback via POST /api/v1/playlists/{id}/resume
    resume_resp = client.post(f"/api/v1/playlists/{playlist_id}/resume")
    assert resume_resp.status_code == 200
    assert resume_resp.json()["current_position"] == 60.0

    # 11. Update playlist via PUT /api/v1/playlists/{id}
    update_resp = client.put(f"/api/v1/playlists/{playlist_id}", json={
        "name": "Updated Playlist Title",
        "description": "Updated description"
    })
    assert update_resp.status_code == 200

    # 12. Delete playlist via DELETE /api/v1/playlists/{id}
    del_resp = client.delete(f"/api/v1/playlists/{playlist_id}")
    assert del_resp.status_code == 204

    app.dependency_overrides.clear()
