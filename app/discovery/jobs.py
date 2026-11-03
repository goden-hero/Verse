"""SQLite queue operations; no provider/network calls on the request path."""
import json
import math
from pathlib import Path
from datetime import datetime
import uuid
from sqlalchemy import case, update
from sqlalchemy.dialects.sqlite import insert
from app.database.connection import get_session
from app.database.models import Song, SongRequest, SongSource, SongRequestPlaylist
from app.services.library import LibraryService
from app.services.playlist_metadata import song_metadata_query
from .catalogue import DiscoveryError, cache_get
from .config import DiscoveryConfig
from .resolution import resolved_candidate


def source_song(db, key):
    row = db.query(Song.id, Song.path, Song.duration).join(SongSource, SongSource.song_id == Song.id).filter(SongSource.identity_key == key).first()
    if row and row.duration and math.isfinite(row.duration) and row.duration > 0 and Path(row.path).is_file():
        return row.id
    return None


def job_dict(job, db, songs=None, intents=None):
    song = (songs.get(job.song_id) if songs is not None else LibraryService.get_song_by_id(job.song_id, db)) if job.state == 'ready' and job.song_id else None
    if job.state == 'ready' and song is None:
        # A later library scan/delete may remove the original Song row. Do not
        # emit an invalid ready payload that poisons every other status result.
        job.state = 'failed'; job.song_id = None
        job.error = 'This library entry is no longer available. Retry to reindex or reacquire it.'
        job.updated_at = datetime.utcnow()
    resolved = json.loads(job.resolved_json) if job.resolved_json else {}
    return {"id": job.id, "key": job.identity_key, "track": json.loads(job.metadata_json), "state": job.state,
        "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(),
        "next_attempt_at": job.next_attempt_at.isoformat(), "attempts": job.attempts, "error": job.error,
        "song": song, "resolution": resolved.get('resolution'),
        "candidates": resolved.get('candidates', []) if job.state == 'awaiting_choice' else [],
        'playlist_intents': intents if intents is not None else _job_intents(job.id, db)}


def _job_intents(job_id, db):
    from .playlist_intents import intent_dict
    return [intent_dict(row) for row in db.query(SongRequestPlaylist).filter_by(request_id=job_id).order_by(SongRequestPlaylist.id).all()]


def find_recording_job(db, key):
    query = db.query(SongRequest)
    if key.startswith('musicbrainz:'):
        query = query.filter(SongRequest.identity_key.like(':'.join(key.split(':')[:2]) + ':%'))
    else: query = query.filter_by(identity_key=key)
    return query.order_by(case((SongRequest.state == 'ready', 0), else_=1), SongRequest.created_at.desc()).first()


def request_song(key, playlist_id=None, current_user=None):
    if DiscoveryConfig.load().music_dir is None:
        raise DiscoveryError("Set VERSE_MUSIC_DIR and start the request worker before requesting songs.")
    selected = cache_get("selection:" + key)
    with get_session() as db:
        # Serialize the recording-level read/insert across release variants on
        # SQLite. Existing distinct recordings/legacy jobs are never merged/deleted.
        db.execute(update(SongRequest).where(SongRequest.id == '').values(updated_at=SongRequest.updated_at))
        job = find_recording_job(db, key)
        # Existing IDs remain usable after cache expiry or a server restart.
        # INSERT first avoids SQLite read-to-write transaction upgrades.
        if selected is None:
            if not job: raise DiscoveryError("This search result expired. Search again before requesting it.", status_code=409)
        now = datetime.utcnow()
        if not job:
            prepared = cache_get('resolved-selection:' + key)
            db.execute(insert(SongRequest).values(id=str(uuid.uuid4()), identity_key=key,
                metadata_json=json.dumps(selected), state='awaiting_choice' if prepared and prepared.get('selection_required') else 'queued',
                resolved_json=json.dumps(prepared) if prepared else None, created_at=now, updated_at=now,
                next_attempt_at=now, attempts=0).on_conflict_do_nothing(index_elements=[SongRequest.identity_key]))
            job = db.query(SongRequest).filter_by(identity_key=key).one()
        song_id = source_song(db, key)
        if song_id and job.state not in ("resolving", "downloading", "indexing"):
            job.state = "ready"; job.song_id = song_id; job.error = None; job.updated_at = now
        if playlist_id is not None:
            from .playlist_intents import attach_intent
            attach_intent(db, job, playlist_id, current_user)
            if job.state == 'failed':
                job.state = 'queued'; job.attempts = 0; job.error = None; job.next_attempt_at = now
        job_id = job.id
    if playlist_id is not None:
        from .playlist_intents import fulfill_ready_intents
        fulfill_ready_intents(job_id)
    with get_session() as db: return job_dict(db.get(SongRequest, job_id), db)


def list_jobs(limit=100):
    with get_session() as db:
        jobs = db.query(SongRequest).order_by(case((SongRequest.state.in_(["queued", "resolving", "downloading", "indexing", "awaiting_choice"]), 0), else_=1), SongRequest.created_at.desc()).limit(limit).all()
        ids = [job.song_id for job in jobs if job.state == "ready" and job.song_id]
        songs = {row.id: dict(row._mapping) for row in song_metadata_query(db).filter(Song.id.in_(ids)).all()} if ids else {}
        from .playlist_intents import intent_dict
        intents = {}
        for row in db.query(SongRequestPlaylist).filter(SongRequestPlaylist.request_id.in_([job.id for job in jobs])).all():
            intents.setdefault(row.request_id, []).append(intent_dict(row))
        return [job_dict(job, db, songs, intents.get(job.id, [])) for job in jobs]


def retry_job(job_id):
    with get_session() as db:
        # A requested rediscovery discards only unresolved options, never a
        # completed acquisition retained for an indexing retry.
        db.execute(update(SongRequest).where(SongRequest.id == job_id, SongRequest.state == 'awaiting_choice').values(
            state='failed', resolved_json=None))
        db.execute(update(SongRequest).where(SongRequest.id == job_id, SongRequest.state == "failed").values(
            state="queued", attempts=0, error=None, next_attempt_at=datetime.utcnow(), updated_at=datetime.utcnow()))
        job = db.get(SongRequest, job_id)
        if not job: raise LookupError("Song request not found.")
        return job_dict(job, db)


def choose_version(job_id, candidate_key):
    """Choose only a persisted server candidate, atomically and idempotently."""
    with get_session() as db:
        job = db.get(SongRequest, job_id)
        if not job: raise LookupError('Song request not found.')
        snapshot = job.resolved_json
        resolved = json.loads(snapshot) if snapshot else {}
        if job.state != 'awaiting_choice':
            if resolved.get('key') == candidate_key:
                return job_dict(job, db)  # repeated submit/lost response
            raise DiscoveryError('This request no longer awaits a version. Refresh its status.', status_code=409)
        candidate = next((track for track in resolved.get('candidates', []) if track['key'] == candidate_key), None)
        if not candidate:
            raise DiscoveryError('That version is not one of this request’s saved candidates. Refresh versions.', status_code=422)
        selected = resolved['selected']
        chosen = resolved_candidate(selected, candidate, 'user_selected_' + resolved['method'], user_selected=True)
        now = datetime.utcnow()
        db.execute(update(SongRequest).where(SongRequest.id == job_id,
            SongRequest.state == 'awaiting_choice', SongRequest.resolved_json == snapshot).values(
                state='queued', attempts=0, error=None, next_attempt_at=now, updated_at=now,
                resolved_json=json.dumps(chosen), downloaded_path=None))
        db.expire_all()
        current = db.get(SongRequest, job_id)
        actual = json.loads(current.resolved_json or '{}')
        if actual.get('key') != candidate_key:
            raise DiscoveryError('Another version was chosen. Refresh before continuing.', status_code=409)
        return job_dict(current, db)
