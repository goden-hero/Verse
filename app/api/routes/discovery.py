import logging
from dataclasses import replace
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError
from app.api.dependencies import CurrentUser, get_current_user
from app.database.connection import get_session
from app.database.models import SongRequest
from app.services.library import LibraryService
from app.discovery.catalogue import Catalogue, DiscoveryError, identity
from app.discovery.config import DiscoveryConfig
from app.discovery.jobs import choose_version, job_dict, list_jobs, request_song, retry_job, source_song

router = APIRouter(tags=["Discovery and song requests"])
logger = logging.getLogger('music_rec.discovery')


def unavailable(error):
    if isinstance(error, OperationalError):
        if 'no such table' in str(error.orig).lower():
            return HTTPException(503, "Song requests need the database migration. Run alembic upgrade head on the configured database.")
        logger.error('Discovery database request failed', exc_info=error)
        return HTTPException(503, "Request storage is temporarily unavailable. Try again; existing jobs are retained.", headers={'Retry-After':'2'})
    return HTTPException(error.status_code, str(error), headers={"Retry-After": str(error.retry_after)} if error.retry_after else None)


@router.get("/search/external")
def external_search(q: str = Query(default="", max_length=200)):
    # The public search catalogue is MusicBrainz regardless of acquisition's
    # optional Spotify credentials. No songs/sources/jobs are queried here.
    config = replace(DiscoveryConfig.load(), provider='musicbrainz')
    if len(q.strip()) < 2: return {"provider": config.catalogue, "results": [], "can_request": config.music_dir is not None}
    try:
        tracks = Catalogue(config).search(q.strip())
        return {"provider": config.catalogue, "results": tracks, "can_request": config.music_dir is not None}
    except (DiscoveryError, OperationalError) as error:
        raise unavailable(error) from error


class RequestSelection(BaseModel):
    provider: Literal["spotify", "musicbrainz"]
    recording_id: str = Field(min_length=1, max_length=36)
    release_id: str = Field(default="", max_length=36)


class RequestIntent(RequestSelection):
    playlist_id: int | None = Field(default=None, gt=0)


def require_signed_in(user):
    if not user.is_authenticated: raise HTTPException(401, "Sign in to request songs.")


@router.post("/song-requests", status_code=202)
def create_request(payload: RequestIntent, user: CurrentUser = Depends(get_current_user)):
    require_signed_in(user)
    try:
        key = identity(payload.provider, payload.recording_id, payload.release_id)
        return request_song(key, payload.playlist_id, user)
    except LookupError as error: raise HTTPException(404, str(error)) from error
    except (DiscoveryError, OperationalError) as error:
        raise unavailable(error) from error


@router.get('/catalogue/recordings/{recording_id}')
def catalogue_selection(recording_id: str, release_id: str = '', user: CurrentUser = Depends(get_current_user)):
    require_signed_in(user)
    from app.discovery.selection import selected_recording
    try: return selected_recording(identity('musicbrainz', recording_id, release_id))
    except (DiscoveryError, OperationalError) as error: raise unavailable(error) from error


@router.get("/song-requests")
def requests_status(user: CurrentUser = Depends(get_current_user)):
    require_signed_in(user)
    try: return list_jobs()
    except OperationalError as error: raise unavailable(error) from error


@router.post("/song-requests/{job_id}/retry")
def retry_request(job_id: str, user: CurrentUser = Depends(get_current_user)):
    require_signed_in(user)
    try: return retry_job(job_id)
    except LookupError as error: raise HTTPException(404, str(error)) from error
    except OperationalError as error: raise unavailable(error) from error


class VersionChoice(BaseModel):
    candidate_key: str = Field(min_length=1, max_length=80)


@router.post('/song-requests/{job_id}/choose-version', status_code=202)
def choose_request_version(job_id: str, payload: VersionChoice, user: CurrentUser = Depends(get_current_user)):
    require_signed_in(user)
    try: return choose_version(job_id, payload.candidate_key)
    except LookupError as error: raise HTTPException(404, str(error)) from error
    except (DiscoveryError, OperationalError) as error: raise unavailable(error) from error


@router.get("/song-requests/{job_id}")
def request_status(job_id: str, user: CurrentUser = Depends(get_current_user)):
    require_signed_in(user)
    try:
        with get_session() as db:
            job = db.get(SongRequest, job_id)
            if not job: raise HTTPException(404, "Song request not found.")
            return job_dict(job, db)
    except OperationalError as error: raise unavailable(error) from error
