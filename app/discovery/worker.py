"""One persistent worker; file lock also covers its acquisition subprocesses."""
import fcntl
import json
import logging
from pathlib import Path
import signal
import time
from datetime import datetime, timedelta
from sqlalchemy import case, exists, select, update
from sqlalchemy.dialects.sqlite import insert

from app.database.connection import get_session
from app.database.models import Song, SongRequest, SongSource
from app.indexing.single_file import InvalidAudio, index_single_file, spotify_id_from_file
from .acquisition import SpotDLAdapter
from .catalogue import DiscoveryError
from .config import DiscoveryConfig
from .jobs import source_song
from .resolution import ChooseRecording

logger = logging.getLogger("music_rec.requests")


def checkpoint(job_id, **values):
    with get_session() as db:
        db.execute(update(SongRequest).where(SongRequest.id == job_id).values(updated_at=datetime.utcnow(), **values))


def recover_interrupted():
    with get_session() as db:
        db.execute(update(SongRequest).where(SongRequest.state.in_(["resolving", "downloading", "indexing"])).values(
            state="queued", next_attempt_at=datetime.utcnow(), updated_at=datetime.utcnow(),
            attempts=case((SongRequest.attempts > 0, SongRequest.attempts - 1), else_=0),
            error="Worker restarted; resuming from the last saved checkpoint."))


def backfill_identities():
    """Explicit one-time tag-only import for pre-existing spotDL library files."""
    with get_session() as db:
        rows = db.query(Song.id, Song.path).filter(~exists().where(SongSource.song_id == Song.id)).order_by(Song.id).all()
    count = 0
    for song_id, path in rows:
        try:
            track_id = spotify_id_from_file(path)
            if track_id:
                with get_session() as db:
                    db.execute(insert(SongSource).values(identity_key="spotify:" + track_id, song_id=song_id).on_conflict_do_nothing())
                count += 1
        except (OSError, ValueError):
            logger.warning("Cannot read source tag for library song %s", song_id)
    return count


class RequestWorker:
    def __init__(self, config=None, adapter=None, indexer=index_single_file):
        self.config = config or DiscoveryConfig.load()
        self.adapter = adapter or SpotDLAdapter(self.config)
        self.indexer = indexer

    def run_once(self):
        from .playlist_intents import fulfill_ready_intents
        if fulfill_ready_intents(): return True
        now = datetime.utcnow()
        with get_session() as db:
            oldest = select(SongRequest.id).where(SongRequest.state == "queued", SongRequest.next_attempt_at <= now).order_by(SongRequest.created_at, SongRequest.id).limit(1).scalar_subquery()
            claimed = db.execute(update(SongRequest).where(SongRequest.id == oldest, SongRequest.state == "queued").values(
                state="resolving", attempts=SongRequest.attempts + 1, error=None, updated_at=now).returning(SongRequest.id)).first()
            if not claimed: return False
            job = db.get(SongRequest, claimed[0])
            job_id, metadata_json, attempts = job.id, job.metadata_json, job.attempts
            resolved_json = job.resolved_json
            downloaded = job.downloaded_path
        path = None
        try:
            selected = json.loads(metadata_json)
            resolved = json.loads(resolved_json) if resolved_json else None
            with get_session() as db:
                existing = source_song(db, selected["key"])
                if existing:
                    db.execute(update(SongRequest).where(SongRequest.id == job_id).values(state="ready", song_id=existing, error=None, updated_at=datetime.utcnow()))
                    return True
            if resolved is None:
                resolved = self.adapter.resolve(selected)
                checkpoint(job_id, resolved_json=json.dumps(resolved))
            # Metadata similarity/user choice is not an exact MusicBrainz ↔
            # Spotify identity assertion. Keep the mapping/provenance on the
            # persistent job, and only index the real Spotify source identity.
            keys = list(dict.fromkeys(([selected['key']] if resolved.get('resolution', {}).get('verified_identity', True) else []) + [resolved['key']]))
            with get_session() as db:
                existing = source_song(db, resolved["key"])
                if existing:
                    for key in keys:
                        db.execute(insert(SongSource).values(identity_key=key, song_id=existing).on_conflict_do_nothing())
                    db.execute(update(SongRequest).where(SongRequest.id == job_id).values(state="ready", song_id=existing, error=None, updated_at=datetime.utcnow()))
                    return True
            checkpoint(job_id, state="downloading")
            path = self.adapter.bounded_path(downloaded) if downloaded and Path(downloaded).is_file() else self.adapter.download(resolved)
            path = self.adapter.bounded_path(path)
            checkpoint(job_id, state="indexing", downloaded_path=str(path), resolved_json=json.dumps(resolved))
            path = self.adapter.publish(path, resolved)
            checkpoint(job_id, downloaded_path=str(path))
            with get_session() as db:
                song_id = self.indexer(path, resolved, keys, db)
                db.execute(update(SongRequest).where(SongRequest.id == job_id).values(state="ready", song_id=song_id, error=None, updated_at=datetime.utcnow()))
            logger.info("Song request %s ready (song %s)", job_id, song_id)
            fulfill_ready_intents(job_id)
        except ChooseRecording as choice:
            checkpoint(job_id, state='awaiting_choice', error=None, downloaded_path=None,
                resolved_json=json.dumps(choice.options))
            logger.info('Song request %s needs version selection (%s candidates)', job_id, len(choice.options['candidates']))
        except Exception as error:
            logger.exception("Song request %s failed during processing", job_id)
            message = str(error) if isinstance(error, (DiscoveryError, ValueError)) else "Song acquisition or indexing failed. Check worker logs and retry."
            retry = getattr(error, 'retryable', True) and attempts < self.config.attempts
            if isinstance(error, InvalidAudio) and path and Path(path).is_file() and Path(path).is_relative_to(self.config.music_dir / '.verse-requests'):
                # Completed-but-invalid acquisitions may be reacquired; ordinary
                # DB/indexing/tool failures retain the completed file for retry.
                Path(path).replace(Path(path).with_name('invalid-' + str(time.time_ns()) + Path(path).suffix))
                checkpoint(job_id, downloaded_path=None)
            delay = max(getattr(error, "retry_after", 0), min(300, 5 * 2 ** (attempts - 1)))
            checkpoint(job_id, state="queued" if retry else "failed", error=message,
                next_attempt_at=datetime.utcnow() + timedelta(seconds=delay))
        return True


def run_worker(*, once=False, backfill=False):
    config = DiscoveryConfig.load()
    adapter = SpotDLAdapter(config)
    if config.music_dir is None: raise DiscoveryError("Set VERSE_MUSIC_DIR before starting request-worker.")
    with get_session() as db:
        url = db.get_bind().url
    if url.get_backend_name() != 'sqlite' or not url.database or url.database == ':memory:':
        raise DiscoveryError('The persistent request worker needs a file-backed SQLite database.')
    # Lock by database, not music directory: two differently configured workers
    # must still never process this SQLite queue simultaneously.
    lock_path = Path(url.database).resolve().with_name(Path(url.database).name + '.requests.lock')
    with open(lock_path, "a") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise DiscoveryError("A request worker or its downloader is already running.") from error
        adapter.lock_fd = lock.fileno()
        directory = adapter.bounded_path(config.music_dir / ".verse-requests")
        directory.mkdir(parents=True, exist_ok=True)
        recover_interrupted()
        if backfill: logger.info("Imported source tags from %s library files", backfill_identities())
        worker = RequestWorker(config, adapter)
        def stop(*_): raise KeyboardInterrupt()
        old = signal.signal(signal.SIGTERM, stop)
        try:
            while True:
                processed = worker.run_once()
                if once: break
                if not processed: time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Request worker stopped; interrupted jobs will resume on startup.")
        finally:
            signal.signal(signal.SIGTERM, old)
