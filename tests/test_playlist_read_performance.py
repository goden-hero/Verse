"""Read contracts, bounded SQL and real request-session lifetimes."""
import asyncio
import time

import httpx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Base, Playlist, PlaylistSong, PlaybackSession, Song, User
from app.identity import CurrentUser
from app.services.playlist import PlaylistService
from app.services.playback_session import PlaybackSessionService
from app.services.playlist_artwork import PlaylistArtworkService, _COVER_CACHE


def test_metadata_queries_stay_bounded_and_do_not_load_artwork(db_engine, db_session):
    user = CurrentUser(id=1, username="Verse Owner")
    db_session.add_all([Song(id=i, path=f"/{i}.mp3", hash=str(i), title=f"Song {i}",
                             duration=60 if i < 5 else None, cover_art=b"x" * 100_000) for i in range(1, 6)])
    db_session.commit()
    statements, loaded = [], []
    def sql(conn, cursor, statement, *args):
        statements.append(statement)
    def on_load(session, obj):
        if isinstance(obj, Song):
            loaded.append(obj.id)
    event.listen(db_engine, "before_cursor_execute", sql)
    event.listen(Session, "loaded_as_persistent", on_load)
    try:
        for count in (5, 50):
            for i in range(count):
                p = Playlist(name=f"Mix {count}-{i}", user_id=1)
                db_session.add(p)
                db_session.flush()
                if i:
                    db_session.add_all([PlaylistSong(playlist_id=p.id, song_id=j, position=j-1) for j in range(1, 6)])
                db_session.add_all([PlaybackSession(playlist_id=p.id), PlaybackSession(playlist_id=p.id)])
            db_session.commit()
            with Session(db_engine) as session:
                statements.clear(); loaded.clear()
                rows = PlaylistService.get_playlists(user, session, limit=100)
                assert len(statements) == 1 and not loaded
                assert all(r["play_count"] == 2 for r in rows)
                assert any(r["songs_count"] == 0 and r["total_duration"] == 0 for r in rows)
                assert all(r["total_duration"] == 240 for r in rows if r["songs_count"])
                statements.clear()
                recent = PlaybackSessionService.get_recently_played_playlists(user, session=session)
                assert len(statements) == 1 and all("songs_count" in r for r in recent)
                statements.clear()
                PlaybackSessionService.get_continue_listening(user, session=session)
                assert len(statements) == 1 and not loaded
                statements.clear()
                detail = PlaylistService.get_playlist_details(user, p.id, session)
                assert len(statements) <= 3 and len(detail["songs"]) == 5 and not loaded
    finally:
        event.remove(db_engine, "before_cursor_execute", sql)
        event.remove(Session, "loaded_as_persistent", on_load)


def test_cover_warm_cache_avoids_artwork_and_membership_updates_invalidate(db_session, db_engine):
    user = CurrentUser(id=1, username="Verse Owner")
    songs = [Song(path=f"/{i}", hash=str(i), title=str(i)) for i in range(10)]
    db_session.add_all(songs); db_session.commit()
    pid = PlaylistService.create_playlist(user, name="Cover", session=db_session)
    PlaylistService.add_songs_to_playlist(user, pid, [s.id for s in songs], db_session)
    _COVER_CACHE.clear()
    statements = []
    def sql(conn, cursor, statement, *args): statements.append(statement)
    event.listen(db_engine, "before_cursor_execute", sql)
    try:
        cold = PlaylistArtworkService.generate_cover(pid, db_session)
        assert len(statements) == 2
        assert "LIMIT" in statements[0]
        statements.clear()
        assert PlaylistArtworkService.generate_cover(pid, db_session) == cold
        assert len(statements) == 1
        assert "songs.cover_art AS" not in statements[0]
        PlaylistService.add_songs_to_playlist(user, pid, [], db_session)
        statements.clear()
        assert PlaylistArtworkService.generate_cover(pid, db_session) != cold
        assert len(statements) == 1
    finally:
        event.remove(db_engine, "before_cursor_execute", sql)


@pytest.mark.parametrize("clients", [1, 5])
def test_production_dependencies_overlap_without_sharing_sessions(tmp_path, monkeypatch, clients):
    from app.database import connection
    from app.api.server import app
    from app.auth.sessions import SessionService, SESSION_COOKIE

    engine = create_engine(f"sqlite:///{tmp_path / 'requests.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    collisions = []
    class TrackedSession(Session):
        def execute(self, *args, **kwargs):
            if getattr(self, "executing", False): collisions.append("shared execute")
            self.executing = True
            try:
                time.sleep(0.001)
                return super().execute(*args, **kwargs)
            finally:
                self.executing = False
        def close(self):
            if getattr(self, "executing", False): collisions.append("closed during execute")
            return super().close()
    factory = sessionmaker(bind=engine, class_=TrackedSession)
    # Replace only the DB factory, not get_db, get_session or the middleware.
    monkeypatch.setattr(connection, "SessionFactory", factory)
    assert not app.dependency_overrides
    with factory() as session:
        user = session.get(User, 1); user.password_hash = "fixture-password-hash"
        session.add(Song(id=1, path="/fixture", hash="fixture", title="Fixture", duration=60))
        session.add(Playlist(id=1, user_id=1, name="One")); session.flush()
        session.add(PlaylistSong(playlist_id=1, song_id=1, position=0))
        session.add(PlaybackSession(id=1, playlist_id=1)); session.commit()
        token = SessionService.create(user, session)

    async def exercise():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async def browser():
            async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={SESSION_COOKIE: token}) as client:
                for step in range(12):
                    responses = await asyncio.gather(
                        client.get("/api/v1/playlists"),
                        client.get("/api/v1/playlists?section=recently_played"),
                        client.get("/api/v1/playlists/continue-listening"),
                        client.get("/api/v1/playlists/1"),
                        client.put("/api/v1/playlists/1/progress?session_id=1", json={"song_index":0,"position":step}),
                    )
                    for r in responses: assert r.status_code == 200, r.text
                    assert responses[1].json()[0]["songs_count"] == 1
                art = await client.get("/api/v1/playlists/1/cover")
                assert art.status_code == 200
                cached = await client.get("/api/v1/playlists/1/cover", headers={"If-None-Match":art.headers["etag"]})
                assert cached.status_code == 304 and not cached.content
        await asyncio.gather(*(browser() for _ in range(clients)))
    try:
        asyncio.run(exercise())
        assert not collisions
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()
