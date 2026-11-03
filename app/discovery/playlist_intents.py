"""Persisted append work, independent of acquisition failures and browser lifetime."""
import logging
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from app.database.connection import get_session
from app.database.models import Playlist, SongRequest, SongRequestPlaylist
from app.identity import CurrentUser
from app.services.playlist import PlaylistService

logger = logging.getLogger('music_rec.request_playlists')


def attach_intent(db, job, playlist_id, user):
    # Lock/validate using the same existing owner scope as normal playlist append.
    row = db.execute(update(Playlist).where(Playlist.id == playlist_id, Playlist.user_id == user.id)
        .values(updated_at=Playlist.updated_at).returning(Playlist.name, Playlist.created_at)).first()
    if not row: raise LookupError('Destination playlist is no longer available. Choose another playlist.')
    now = datetime.utcnow()
    statement = insert(SongRequestPlaylist).values(request_id=job.id, playlist_id=playlist_id,
        playlist_name=row.name, playlist_created_at=row.created_at, user_id=user.id, state='pending', error=None, added_count=0, skipped_count=0,
        created_at=now, updated_at=now)
    db.execute(statement.on_conflict_do_update(index_elements=['request_id', 'playlist_id'],
        set_={'state':'pending', 'error':None, 'updated_at':now, 'playlist_name':row.name, 'playlist_created_at':row.created_at,
              'user_id':user.id, 'added_count':0, 'skipped_count':0},
        where=(SongRequestPlaylist.state == 'failed') | (SongRequestPlaylist.playlist_created_at != row.created_at)))
    job.updated_at = now


def intent_dict(row):
    return {key:getattr(row, key) for key in ('id', 'playlist_id', 'playlist_name', 'state', 'error', 'added_count', 'skipped_count')} | {
        'updated_at':row.updated_at.isoformat()}


def fulfill_ready_intents(job_id=None):
    with get_session() as db:
        query = select(SongRequestPlaylist.id).join(SongRequest, SongRequest.id == SongRequestPlaylist.request_id).where(
            SongRequest.state == 'ready', SongRequestPlaylist.state == 'pending')
        if job_id: query = query.where(SongRequest.id == job_id)
        ids = db.scalars(query.order_by(SongRequestPlaylist.id).limit(20)).all()
    for intent_id in ids:
        try:
            with get_session() as db:
                locked = db.execute(update(SongRequestPlaylist).where(SongRequestPlaylist.id == intent_id,
                    SongRequestPlaylist.state == 'pending').values(updated_at=SongRequestPlaylist.updated_at)
                    .returning(SongRequestPlaylist.id)).first()
                if not locked: continue
                intent = db.get(SongRequestPlaylist, intent_id)
                job = db.get(SongRequest, intent.request_id)
                if job.state != 'ready': continue
                if not job.song_id:
                    job.state = 'failed'; job.error = 'The library entry was removed. Retry to reacquire it; the playlist destination is retained.'
                    job.updated_at = datetime.utcnow()
                    continue
                destination = db.get(Playlist, intent.playlist_id)
                if not destination or destination.created_at != intent.playlist_created_at:
                    # SQLite can reuse an ID after deletion. Never add to a new,
                    # unrelated playlist that inherited the same integer ID.
                    raise LookupError('The original destination was deleted.')
                intent.playlist_name = destination.name
                result = PlaylistService.append_songs_to_playlist(
                    CurrentUser(id=intent.user_id, username='request-worker'), intent.playlist_id, [job.song_id], db, commit=False)
                intent.state = 'added'; intent.error = None
                intent.added_count = result['added_count']; intent.skipped_count = result['skipped_count']
                intent.updated_at = job.updated_at = datetime.utcnow()
                # Membership + completed intent commit atomically. After a crash,
                # a pending intent can safely repeat the idempotent append.
        except Exception as error:
            logger.exception('Playlist intent %s could not be appended', intent_id)
            with get_session() as db:
                intent = db.get(SongRequestPlaylist, intent_id)
                if not intent or intent.state != 'pending': continue
                intent.state = 'failed'
                intent.error = ('The destination playlist is no longer available. The song is ready in your library.'
                    if isinstance(error, LookupError) else 'The song is ready, but adding it failed. Retry the playlist addition.')
                intent.updated_at = datetime.utcnow()
                db.get(SongRequest, intent.request_id).updated_at = intent.updated_at
    return bool(ids)
