"""Manual playlist contracts against production request/session dependencies."""
import asyncio
import io
from pathlib import Path
import subprocess
import sys

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.api.server import app
from app.auth.sessions import SESSION_COOKIE, SessionService
from app.database import connection
from app.database.models import Base, Playlist, PlaylistSong, Song, User
from app.services.playlist_artwork import _COVER_CACHE


@pytest.fixture
def manual_client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'manual.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(connection, "SessionFactory", factory)
    assert not app.dependency_overrides
    with factory() as db:
        user = db.get(User, 1)
        user.password_hash = "fixture-password-hash"
        for sid in range(1, 7):
            output = io.BytesIO()
            Image.new("RGB", (32, 32), (sid * 30, 20, 100)).save(output, format="PNG")
            db.add(Song(id=sid, path=f"/{sid}.mp3", hash=str(sid), title=f"Song {sid}",
                        artist=f"Artist {sid}", album=f"Album {sid}", duration=60, cover_art=output.getvalue()))
        db.commit()
        token = SessionService.create(user, db)
    try:
        with TestClient(app) as client:
            client.cookies.set(SESSION_COOKIE, token)
            yield client, factory
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def create(client, ids=None, **fields):
    response = client.post('/api/v1/playlists', json={"name": "Evening Mix", "song_ids": ids or [], **fields})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def ordered(client, pid):
    return [song['id'] for song in client.get(f'/api/v1/playlists/{pid}').json()['songs']]


def test_create_empty_playlist_with_description(manual_client):
    client, _ = manual_client
    response = client.post('/api/v1/playlists', json={"name": "  Empty Mix  ", "description": "  My evening songs  "})
    assert response.status_code == 201
    pid = response.json()['id']
    detail = client.get(f'/api/v1/playlists/{pid}').json()
    assert (detail['name'], detail['description'], detail['songs'], detail['songs_count'], detail['total_duration']) == (
        'Empty Mix', 'My evening songs', [], 0, 0)
    assert any(p['id'] == pid and p['songs_count'] == 0 for p in client.get('/api/v1/playlists').json())
    assert client.get(f'/api/v1/playlists/{pid}/cover').status_code == 200


@pytest.mark.parametrize('name', ['', '   ', '\n\t'])
def test_blank_name_does_not_create_playlist(manual_client, name):
    client, factory = manual_client
    assert client.post('/api/v1/playlists', json={"name": name}).status_code == 400
    with factory() as db:
        assert db.query(Playlist).count() == 0


def test_single_multiple_and_repeated_append_preserve_order(manual_client):
    client, factory = manual_client
    pid = create(client, [3, 1])
    before = client.get(f'/api/v1/playlists/{pid}').json()['updated_at']
    cover_before = client.get(f'/api/v1/playlists/{pid}/cover').content
    assert any(key[0] == pid for key in _COVER_CACHE)
    first = client.post(f'/api/v1/playlists/{pid}/songs', json={"song_ids": [5]})
    assert first.status_code == 200, first.text
    assert first.json() == {"playlist_id": pid, "added_count": 1, "skipped_count": 0, "songs_count": 3}
    assert not any(key[0] == pid for key in _COVER_CACHE)
    second = client.post(f'/api/v1/playlists/{pid}/songs', json={"song_ids": [4, 2, 4, 1]})
    assert second.json() == {"playlist_id": pid, "added_count": 2, "skipped_count": 2, "songs_count": 5}
    assert ordered(client, pid) == [3, 1, 5, 4, 2]
    after = client.get(f'/api/v1/playlists/{pid}').json()['updated_at']
    assert after > before
    assert client.get(f'/api/v1/playlists/{pid}/cover').content != cover_before
    repeated = client.post(f'/api/v1/playlists/{pid}/songs', json={"song_ids": [4, 2, 4, 1]})
    assert repeated.json()['added_count'] == 0 and repeated.json()['skipped_count'] == 4
    assert client.get(f'/api/v1/playlists/{pid}').json()['updated_at'] == after
    with factory() as db:
        assert db.query(PlaylistSong.position).filter_by(playlist_id=pid).order_by(PlaylistSong.position).all() == [(0,), (1,), (2,), (3,), (4,)]
    assert ordered(client, pid) == [3, 1, 5, 4, 2]


def test_append_uses_max_position_without_reordering_existing_gaps(manual_client):
    client, factory = manual_client
    pid = create(client, [1, 2])
    with factory() as db:
        db.get(PlaylistSong, (pid, 2)).position = 9
        db.commit()
    result = client.post(f'/api/v1/playlists/{pid}/songs', json={"song_ids": [3, 4]})
    assert result.status_code == 200
    with factory() as db:
        assert db.query(PlaylistSong.position).filter_by(playlist_id=pid).order_by(PlaylistSong.position).all() == [(0,), (9,), (10,), (11,)]


def test_append_to_empty_playlist(manual_client):
    client, _ = manual_client
    pid = create(client)
    result = client.post(f'/api/v1/playlists/{pid}/songs', json={"song_ids": [4]})
    assert result.json() == {"playlist_id": pid, "added_count": 1, "skipped_count": 0, "songs_count": 1}
    assert ordered(client, pid) == [4]


@pytest.mark.parametrize('ids', [[2, 99999], [0], [-1], [True], ['2'], [1.5], []])
def test_invalid_song_ids_never_partially_modify_playlist(manual_client, ids):
    client, _ = manual_client
    pid = create(client, [1])
    before = client.get(f'/api/v1/playlists/{pid}').json()
    result = client.post(f'/api/v1/playlists/{pid}/songs', json={"song_ids": ids})
    assert result.status_code == 422, result.text
    after = client.get(f'/api/v1/playlists/{pid}').json()
    assert after['songs'] == before['songs'] and after['updated_at'] == before['updated_at']


def test_missing_playlist_and_invalid_create_ids(manual_client):
    client, factory = manual_client
    assert client.post('/api/v1/playlists/9999/songs', json={"song_ids": [1]}).status_code == 404
    assert client.post('/api/v1/playlists/0/songs', json={"song_ids": [1]}).status_code == 422
    assert client.post('/api/v1/playlists/not-a-number/songs', json={"song_ids": [1]}).status_code == 422
    result = client.post('/api/v1/playlists', json={"name": "Invalid", "song_ids": [1, 9999]})
    assert result.status_code == 422
    with factory() as db:
        assert db.query(Playlist).count() == 0


def test_commit_failure_rolls_back_and_retry_succeeds(manual_client):
    client, _ = manual_client
    pid = create(client, [1, 2])
    before = client.get(f'/api/v1/playlists/{pid}').json()
    def fail_flush(db, *_):
        if any(isinstance(obj, PlaylistSong) and obj.song_id == 5 for obj in db.new):
            raise RuntimeError('Injected flush failure')
    event.listen(Session, 'before_flush', fail_flush)
    try:
        result = client.post(f'/api/v1/playlists/{pid}/songs', json={"song_ids": [4, 5]})
        assert result.status_code == 500
    finally:
        event.remove(Session, 'before_flush', fail_flush)
    after = client.get(f'/api/v1/playlists/{pid}').json()
    assert after['songs'] == before['songs'] and after['updated_at'] == before['updated_at']
    assert client.post(f'/api/v1/playlists/{pid}/songs', json={"song_ids": [4, 5]}).json()['added_count'] == 2
    assert ordered(client, pid) == [1, 2, 4, 5]


@pytest.mark.parametrize('clients', [1, 5])
def test_overlapping_appends_are_duplicate_safe(manual_client, clients):
    client, _ = manual_client
    pid = create(client, [1])
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                     cookies={SESSION_COOKIE: client.cookies.get(SESSION_COOKIE)}) as browser:
            results = await asyncio.gather(*(browser.post(f'/api/v1/playlists/{pid}/songs', json={"song_ids": [2, 3, 4, 5, 2]}) for _ in range(clients)))
            assert all(r.status_code == 200 for r in results), [r.text for r in results]
            assert sum(r.json()['added_count'] for r in results) == 4
            assert sum(r.json()['skipped_count'] for r in results) == clients * 5 - 4
    asyncio.run(exercise())
    assert ordered(client, pid) == [1, 2, 3, 4, 5]


def test_search_includes_album_and_songs_beyond_first_page(manual_client):
    client, factory = manual_client
    with factory() as db:
        db.add_all([Song(id=sid, path=f'/{sid}', hash=str(sid), title=f'Common {sid:04}',
                         artist=f'Performer {sid}', album=f'Album {sid}') for sid in range(7, 260)])
        db.commit()
    first_page = client.get('/api/v1/songs?page=1&page_size=100').json()['songs']
    assert 259 not in [song['id'] for song in first_page]
    for query in ['Common 0259', 'Performer 259', 'Album 259']:
        result = client.get('/api/v1/search', params={'q': query})
        assert result.status_code == 200
        assert result.json()[0]['id'] == 259
    assert len(client.get('/api/v1/search?q=Common').json()) == 253


def test_concurrent_distinct_batches_get_distinct_positions(manual_client):
    client, factory = manual_client
    pid = create(client, [1])
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                     cookies={SESSION_COOKIE: client.cookies.get(SESSION_COOKIE)}) as browser:
            responses = await asyncio.gather(*(browser.post(f'/api/v1/playlists/{pid}/songs', json={"song_ids": ids})
                                               for ids in ([2, 3], [4, 5])))
            assert all(r.status_code == 200 and r.json()['added_count'] == 2 for r in responses)
    asyncio.run(exercise())
    assert ordered(client, pid) in ([1, 2, 3, 4, 5], [1, 4, 5, 2, 3])
    with factory() as db:
        assert db.query(PlaylistSong.position).filter_by(playlist_id=pid).order_by(PlaylistSong.position).all() == [(0,), (1,), (2,), (3,), (4,)]


def test_manual_playlist_browser_flow():
    pytest.importorskip('PySide6.QtWebEngineWidgets')
    result = subprocess.run([sys.executable, str(Path(__file__).with_name('browser_manual_playlist_probe.py'))],
                            capture_output=True, text=True, timeout=55)
    assert result.returncode == 0, result.stdout + result.stderr
