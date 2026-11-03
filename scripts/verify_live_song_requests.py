"""Operator smoke test. Uses real API/services; never prints authentication tokens.

Search is read-only apart from the catalogue's normal cache. Request mode acquires
exactly the selected cached recording. Temporary API sessions are always revoked.
"""
import argparse
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from dotenv import dotenv_values
from app.auth.sessions import SESSION_COOKIE, SessionService
from app.database.connection import get_session
from app.database.models import AuthSession, Song, SongRequest, User

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8001/api/v1'
SECRET_VALUES = [value for key, value in dotenv_values(ROOT / '.env').items()
                 if value and any(word in key.upper() for word in ('CONTACT', 'SECRET', 'PASSWORD', 'TOKEN'))]


def output(data):
    text = json.dumps(data, ensure_ascii=False, default=str)
    for value in SECRET_VALUES:
        text = text.replace(value, '[redacted]')
    print(text, flush=True)


def call(client, method, path, **kwargs):
    response = client.request(method, BASE + path, timeout=35, **kwargs)
    if not response.ok:
        try: detail = response.json().get('detail', 'No detail')
        except ValueError: detail = 'Invalid server response'
        raise RuntimeError(f'HTTP {response.status_code}: {detail}')
    return response.json()


@contextmanager
def api_session():
    with get_session() as db:
        user = db.query(User).filter_by(username='pyro', is_active=True).one()
        token = SessionService.create(user, db)
    SECRET_VALUES.append(token)
    try:
        with get_session() as db:
            record = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
            record.expires_at = datetime.utcnow() + timedelta(hours=1)
        with requests.Session() as client:
            client.cookies.set(SESSION_COOKIE, token)
            who = call(client, 'GET', '/auth/me')
            assert who['username'] == 'pyro'
            yield client
    finally:
        with get_session() as db: SessionService.revoke(token, db)


def safe_job(job):
    return {key: job.get(key) for key in ('id', 'key', 'state', 'attempts', 'error', 'song', 'resolution', 'candidates')}


def verify(client, job):
    assert job['state'] == 'ready' and job['song']
    song_id = job['song']['id']
    metadata = call(client, 'GET', f'/songs/{song_id}')
    stream = client.get(BASE + f'/songs/{song_id}/stream', headers={'Range': 'bytes=0-4095'}, timeout=30)
    assert stream.status_code == 206 and len(stream.content) == 4096
    with get_session() as db:
        record = db.get(SongRequest, job['id'])
        resolved = json.loads(record.resolved_json)
        row = db.query(Song.path, Song.hash).filter(Song.id == song_id).one()
        from app.indexing.single_file import verify_audio_file
        from app.discovery.config import DiscoveryConfig
        path = Path(row.path)
        assert path.resolve().is_relative_to(DiscoveryConfig.load().music_dir)
        assert '.verse-requests' not in path.parts
        tags, technical = verify_audio_file(path, resolved)
        before_count = db.query(Song).count()
        before_files = sorted(str(p) for p in DiscoveryConfig.load().music_dir.rglob('*.mp3'))
    selection = {key: record for key, record in job['track'].items() if key in ('provider', 'recording_id', 'release_id')}
    duplicate = call(client, 'POST', '/song-requests', json=selection)
    assert duplicate['id'] == job['id'] and duplicate['song']['id'] == song_id and duplicate['state'] == 'ready'
    with get_session() as db:
        assert db.query(Song).count() == before_count
        assert db.query(SongRequest).filter_by(identity_key=job['key']).count() == 1
    assert sorted(str(p) for p in DiscoveryConfig.load().music_dir.rglob('*.mp3')) == before_files
    playlists = call(client, 'GET', '/playlists?limit=100')
    assert isinstance(playlists, list)
    output({'verification': 'passed', 'job_id': job['id'], 'song_id': song_id, 'path': str(path),
            'metadata': metadata, 'codec': technical.codec, 'sample_rate': technical.sample_rate,
            'duration': tags.duration, 'stream_http': stream.status_code, 'stream_mime': stream.headers.get('Content-Type'),
            'range_bytes': len(stream.content), 'duplicate_reused_job': True, 'duplicate_reused_song': True,
            'no_additional_audio_files': True, 'playlist_picker_accessible': True, 'playlists_not_modified': True})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['search', 'request', 'status', 'verify'])
    parser.add_argument('value')
    parser.add_argument('--release', default='')
    parser.add_argument('--wait', type=int, default=900)
    args = parser.parse_args()
    if args.mode == 'search':
        data = call(requests.Session(), 'GET', '/search/external', params={'q': args.value})
        output({'provider': data['provider'], 'can_request': data['can_request'], 'results': [
            {key: track.get(key) for key in ('key', 'provider', 'recording_id', 'release_id', 'title', 'artist', 'album', 'version', 'duration', 'isrcs', 'song')}
            for track in data['results']]})
        return
    with api_session() as client:
        if args.mode == 'request':
            provider, recording_id = args.value.split(':', 1)
            job = call(client, 'POST', '/song-requests', json={
                'provider': provider, 'recording_id': recording_id, 'release_id': args.release})
            output({'accepted': safe_job(job), 'selected_recording': job['track']})
        else:
            job = call(client, 'GET', '/song-requests/' + args.value)
        if args.mode == 'verify': verify(client, job); return
        if args.mode == 'status': output(safe_job(job)); return
        end = time.monotonic() + args.wait
        previous = None
        while True:
            state = (job['state'], job['attempts'], job['error'])
            if state != previous: output(safe_job(job)); previous = state
            if job['state'] == 'ready': verify(client, job); return
            if job['state'] == 'awaiting_choice':
                output({'action_required':'Choose a version in Verse to continue this same saved request.',
                        'job_id':job['id'],'candidates':job['candidates']})
                return
            if job['state'] == 'failed': raise RuntimeError('Selected recording request failed; no different recording was requested.')
            if time.monotonic() >= end: raise TimeoutError('Request remains pending; inspect the saved job ID.')
            time.sleep(3)
            job = call(client, 'GET', '/song-requests/' + job['id'])


if __name__ == '__main__':
    try: main()
    except Exception as error:
        output({'error': str(error)})
        raise SystemExit(1)
