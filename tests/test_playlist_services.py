"""Unit tests for Phase 2: PlaylistService, PlaybackSessionService, and PlaylistArtworkService."""

import io
import pytest
from PIL import Image
from sqlalchemy.orm import Session
from app.database.models import Base, Playlist, PlaybackSession, Song
from app.services.playlist import PlaylistService
from app.services.playback_session import PlaybackSessionService
from app.services.playlist_artwork import PlaylistArtworkService


def test_playback_session_lifecycle(db_session: Session):
    """Test starting, updating progress, completing, and fetching stats for playback sessions."""
    # 1. Create a playlist
    playlist_id = PlaylistService.create_playlist(
        name="Session Test Playlist",
        generated_by="MANUAL",
        session=db_session,
    )

    # 2. Start session
    psession = PlaybackSessionService.start_session(
        playlist_id=playlist_id,
        song_index=0,
        position=10.5,
        session=db_session,
    )
    assert psession.id is not None
    assert psession.playlist_id == playlist_id
    assert psession.current_song_index == 0
    assert psession.current_position == 10.5
    assert psession.completed is False

    # 3. Update progress
    updated = PlaybackSessionService.update_progress(
        session_id=psession.id,
        song_index=2,
        position=45.0,
        completed=False,
        session=db_session,
    )
    assert updated.current_song_index == 2
    assert updated.current_position == 45.0
    assert updated.completed is False

    # 4. Check Continue Listening
    continue_list = PlaybackSessionService.get_continue_listening(limit=5, session=db_session)
    assert len(continue_list) >= 1
    latest_continue = continue_list[0]
    assert latest_continue["playlist_id"] == playlist_id
    assert latest_continue["current_song_index"] == 2
    assert latest_continue["current_position"] == 45.0

    # 5. Check Recently Played
    recently_played = PlaybackSessionService.get_recently_played_playlists(limit=5, session=db_session)
    assert len(recently_played) >= 1
    assert recently_played[0]["id"] == playlist_id

    # 6. Finish session
    finished = PlaybackSessionService.finish_session(session_id=psession.id, session=db_session)
    assert finished.completed is True
    assert finished.finished_at is not None

    # 7. Check stats computation
    stats = PlaybackSessionService.get_playlist_stats(playlist_id=playlist_id, session=db_session)
    assert stats["play_count"] == 1
    assert stats["last_played_at"] is not None

    # Continue Listening should no longer return finished session
    continue_list_after = PlaybackSessionService.get_continue_listening(limit=5, session=db_session)
    assert not any(c["session_id"] == psession.id for c in continue_list_after)


def test_playlist_artwork_generation(db_session: Session):
    """Test dynamic cover art composition for 1, 2, 3, and 4+ song playlists."""
    # Create test songs with fake JPEG cover art
    songs = []
    for i in range(5):
        img = Image.new("RGB", (100, 100), color=(i * 40, 100, 200 - i * 30))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        song = Song(
            path=f"/fake/path/song_{i}.mp3",
            hash=f"hash_{i}",
            title=f"Test Song {i}",
            artist="Test Artist",
            cover_art=buf.getvalue(),
        )
        db_session.add(song)
        songs.append(song)
    db_session.commit()

    # 1. Test 1-song cover
    p1 = PlaylistService.create_playlist(name="1 Song Playlist", session=db_session)
    PlaylistService.add_songs_to_playlist(p1, [songs[0].id], db_session)
    cover1_bytes = PlaylistArtworkService.generate_cover(p1, db_session)
    assert len(cover1_bytes) > 0
    img1 = Image.open(io.BytesIO(cover1_bytes))
    assert img1.size == (500, 500)

    # 2. Test 2-song cover (1x2 split)
    p2 = PlaylistService.create_playlist(name="2 Song Playlist", session=db_session)
    PlaylistService.add_songs_to_playlist(p2, [songs[0].id, songs[1].id], db_session)
    cover2_bytes = PlaylistArtworkService.generate_cover(p2, db_session)
    assert len(cover2_bytes) > 0
    img2 = Image.open(io.BytesIO(cover2_bytes))
    assert img2.size == (500, 500)

    # 3. Test 3-song cover (2x2 grid with Verse logo)
    p3 = PlaylistService.create_playlist(name="3 Song Playlist", session=db_session)
    PlaylistService.add_songs_to_playlist(p3, [songs[0].id, songs[1].id, songs[2].id], db_session)
    cover3_bytes = PlaylistArtworkService.generate_cover(p3, db_session)
    assert len(cover3_bytes) > 0
    img3 = Image.open(io.BytesIO(cover3_bytes))
    assert img3.size == (500, 500)

    # 4. Test 4-song cover (2x2 grid)
    p4 = PlaylistService.create_playlist(name="4 Song Playlist", session=db_session)
    PlaylistService.add_songs_to_playlist(p4, [s.id for s in songs[:4]], db_session)
    cover4_bytes = PlaylistArtworkService.generate_cover(p4, db_session)
    assert len(cover4_bytes) > 0
    img4 = Image.open(io.BytesIO(cover4_bytes))
    assert img4.size == (500, 500)


def test_playlist_extended_metadata(db_session: Session):
    """Test creating and retrieving rich AI and manual metadata."""
    pid = PlaylistService.create_playlist(
        name="AI Vibe Mix",
        prompt="Songs for midnight code review",
        strategy="vector",
        seed_type="mood",
        generated_by="AI",
        generator_version="Verse AI v1.0",
        llm_model="Ollama Llama3",
        created_from="AI Assistant",
        description="Late night ambient coding tunes",
        session=db_session,
    )

    details = PlaylistService.get_playlist_details(pid, db_session)
    assert details is not None
    assert details["name"] == "AI Vibe Mix"
    assert details["description"] == "Late night ambient coding tunes"
    assert details["prompt"] == "Songs for midnight code review"
    assert details["strategy"] == "vector"
    assert details["seed_type"] == "mood"
    assert details["generated_by"] == "AI"
    assert details["generator_version"] == "Verse AI v1.0"
    assert details["llm_model"] == "Ollama Llama3"
    assert details["created_from"] == "AI Assistant"
