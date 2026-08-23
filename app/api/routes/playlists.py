from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session
from typing import List, Optional
from app.api.dependencies import get_db, get_current_user, CurrentUser
from app.api.schemas import (
    SongResponse,
    PlaylistGenerateRequest,
    PlaylistCreateRequest,
    PlaylistUpdateRequest,
    PlaylistResponse,
    PlaylistDetailResponse,
    PlaylistStatsResponse,
    PlaySessionStartRequest,
    PlaySessionProgressRequest,
    PlaybackSessionResponse,
    ContinueListeningResponse,
)
from app.database.models import Song
from app.services.playlist import PlaylistService
from app.services.playback_session import PlaybackSessionService
from app.services.playlist_artwork import PlaylistArtworkService

router = APIRouter(tags=["Playlists"])

@router.post("/playlists/generate", response_model=List[SongResponse])
def generate_playlist_preview(
    payload: PlaylistGenerateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Generates a list of recommended songs based on strategy and seeds without persisting to the database."""
    strategy_mapping = {
        "automatic": "hybrid",
        "similar vibe": "vector",
        "similar sound": "content",
        "balanced": "hybrid"
    }
    backend_strategy = strategy_mapping.get(payload.strategy.lower().strip(), payload.strategy.lower().strip())

    filters = {}
    stype = payload.seed_type.lower().strip()
    sval = payload.seed_value.strip()

    if stype in ["current song", "current queue"]:
        # The web player supplies library IDs, not titles.  Resolving a value
        # such as "42" through a title search caused the previous UI fix to
        # choose arbitrary titles containing that number.
        seed_song_ids = list(dict.fromkeys(payload.seed_song_ids))
        if not seed_song_ids and sval:
            try:
                seed_song_ids = [int(sval)]
            except ValueError:
                # Preserve compatibility with older clients that supplied a
                # title for these modes.
                filters["seed_song_title"] = sval

        if seed_song_ids:
            found_song_ids = {
                song_id
                for (song_id,) in db.query(Song.id).filter(Song.id.in_(seed_song_ids)).all()
            }
            missing_song_ids = [song_id for song_id in seed_song_ids if song_id not in found_song_ids]
            if missing_song_ids:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"One or more seed songs no longer exist: {missing_song_ids}.",
                )
            filters["seed_song_ids"] = seed_song_ids
        elif stype == "current queue":
            # The browser queue is session-local; an empty queue must not
            # silently become another user's/global last-played song.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current queue is empty. Add songs to the queue before generating a playlist.",
            )
        elif "seed_song_title" not in filters:
            from app.database.models import ListeningHistory
            last_played_rec = db.query(ListeningHistory).filter(ListeningHistory.last_played != None).order_by(ListeningHistory.last_played.desc()).first()
            if last_played_rec:
                song = db.get(Song, last_played_rec.song_id)
                if song:
                    filters["seed_song_title"] = song.title
            if "seed_song_title" not in filters:
                first_song = db.query(Song).first()
                if first_song:
                    filters["seed_song_title"] = first_song.title
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="No seed song found. Please specify a title or scan music."
                    )
    elif stype == "favourites":
        if sval:
            filters["seed_song_title"] = sval
        else:
            from app.database.models import ListeningHistory
            import random
            favs = db.query(ListeningHistory).filter(ListeningHistory.likes == True).all()
            if favs:
                chosen = random.choice(favs)
                song = db.get(Song, chosen.song_id)
                if song:
                    filters["seed_song_title"] = song.title
            
            if "seed_song_title" not in filters:
                last_played_rec = db.query(ListeningHistory).filter(ListeningHistory.last_played != None).order_by(ListeningHistory.last_played.desc()).first()
                if last_played_rec:
                    song = db.get(Song, last_played_rec.song_id)
                    if song:
                        filters["seed_song_title"] = song.title
            
            if "seed_song_title" not in filters:
                first_song = db.query(Song).first()
                if first_song:
                    filters["seed_song_title"] = first_song.title
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="No favorite or seed songs found."
                    )
    elif stype == "song":
        if not sval:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Seed value is required when seed type is 'song'."
            )
        filters["seed_song_title"] = sval
    elif stype == "mood":
        if not sval:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Seed value is required when seed type is 'mood'."
            )
        filters["moods"] = [sval]
    elif stype == "activity":
        if not sval:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Seed value is required when seed type is 'activity'."
            )
        filters["activities"] = [sval]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported seed type: {payload.seed_type}."
        )

    try:
        results = PlaylistService.generate_playlist_preview(
            current_user=current_user,
            strategy=backend_strategy,
            filters=filters,
            target_length=payload.limit or 20,
            session=db
        )
        return results
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate playlist recommendations: {str(e)}"
        )

@router.post("/playlists", status_code=status.HTTP_201_CREATED)
def create_playlist(
    payload: PlaylistCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Creates a new playlist for the current user and associates it with song IDs."""
    if not payload.name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Playlist name cannot be empty."
        )

    song_ids = list(dict.fromkeys(payload.song_ids))
    found_song_ids = {
        song_id
        for (song_id,) in db.query(Song.id).filter(Song.id.in_(song_ids)).all()
    }
    missing_song_ids = [song_id for song_id in song_ids if song_id not in found_song_ids]
    if missing_song_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"One or more songs no longer exist: {missing_song_ids}.",
        )

    try:
        playlist_id = PlaylistService.create_playlist(
            current_user=current_user,
            name=payload.name.strip(),
            prompt=None,
            strategy="custom",
            generated_by="User",
            session=db,
            commit=False,
        )
        PlaylistService.add_songs_to_playlist(
            current_user=current_user,
            playlist_id=playlist_id,
            song_ids=song_ids,
            session=db,
            commit=False,
        )
        db.commit()
        return {"id": playlist_id, "name": payload.name, "message": "Playlist saved successfully."}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save playlist: {str(e)}"
        )

@router.get("/playlists/continue-listening", response_model=List[ContinueListeningResponse])
def get_continue_listening(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Retrieves list of active unfinished playback sessions for the current user."""
    try:
        return PlaybackSessionService.get_continue_listening(current_user=current_user, limit=limit, session=db)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch continue listening sessions: {str(e)}"
        )

@router.get("/playlists", response_model=List[PlaylistResponse])
def list_playlists(
    section: str = Query("all", description="Section filter: 'recently_played', 'recently_added', or 'all'"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Retrieves metadata of playlists for the current user."""
    try:
        return PlaylistService.get_playlists(current_user=current_user, session=db, section=section, limit=limit)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve playlists: {str(e)}"
        )

@router.get("/playlists/{playlist_id}", response_model=PlaylistDetailResponse)
def get_playlist(
    playlist_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Retrieves complete details of a single user-owned playlist."""
    playlist_details = PlaylistService.get_playlist_details(current_user, playlist_id, db)
    if not playlist_details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Playlist with ID {playlist_id} not found."
        )
    return playlist_details

@router.get("/playlists/{playlist_id}/stats", response_model=PlaylistStatsResponse)
def get_playlist_stats(
    playlist_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Retrieves dynamic statistics for a user-owned playlist."""
    details = PlaylistService.get_playlist_details(current_user, playlist_id, db)
    if not details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Playlist with ID {playlist_id} not found."
        )
    return {
        "play_count": details["play_count"],
        "last_played_at": details["last_played_at"],
        "song_count": details["songs_count"],
        "total_duration": details["total_duration"],
    }

@router.put("/playlists/{playlist_id}")
def update_playlist(
    playlist_id: int,
    payload: PlaylistUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Updates name, description, or track ordering for a user-owned playlist."""
    success = PlaylistService.update_playlist(
        current_user=current_user,
        playlist_id=playlist_id,
        name=payload.name,
        description=payload.description,
        song_ids=payload.song_ids,
        session=db
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Playlist with ID {playlist_id} not found."
        )
    return {"id": playlist_id, "message": "Playlist updated successfully."}

@router.delete("/playlists/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_playlist(
    playlist_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Deletes a user-owned playlist by ID."""
    PlaylistService.delete_playlist(current_user, playlist_id, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/playlists/{playlist_id}/songs", response_model=List[SongResponse])
def get_playlist_songs(
    playlist_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Retrieves all songs belonging to a user-owned playlist."""
    try:
        playlist_songs = PlaylistService.get_playlist_songs(current_user, playlist_id, db)
        if not playlist_songs:
            return []
        
        detailed_songs = []
        for ps in playlist_songs:
            song = db.get(Song, ps["id"])
            if song:
                detailed_songs.append({
                    "id": song.id,
                    "title": song.title,
                    "artist": song.artist,
                    "album": song.album,
                    "duration": song.duration,
                    "genre": song.original_genre or "Unknown",
                    "artwork_available": song.cover_art is not None
                })
        return detailed_songs
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch songs for playlist {playlist_id}: {str(e)}"
        )

@router.post("/playlists/{playlist_id}/play", response_model=PlaybackSessionResponse)
def start_playlist_playback(
    playlist_id: int,
    payload: Optional[PlaySessionStartRequest] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Triggers playback start for a playlist and creates a new PlaybackSession."""
    playlist = PlaylistService.get_playlist_details(current_user, playlist_id, db)
    if not playlist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Playlist with ID {playlist_id} not found."
        )

    song_index = payload.song_index if payload else 0
    position = payload.position if payload else 0.0

    psession = PlaybackSessionService.start_session(
        current_user=current_user,
        playlist_id=playlist_id,
        song_index=song_index,
        position=position,
        session=db
    )
    return {
        "session_id": psession.id,
        "playlist_id": psession.playlist_id,
        "current_song_index": psession.current_song_index,
        "current_position": psession.current_position,
        "started_at": psession.started_at.isoformat(),
        "updated_at": psession.updated_at.isoformat(),
        "finished_at": psession.finished_at.isoformat() if psession.finished_at else None,
        "completed": psession.completed,
    }

@router.post("/playlists/{playlist_id}/resume", response_model=PlaybackSessionResponse)
def resume_playlist_playback(
    playlist_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Resumes active playback session for a playlist."""
    playlist = PlaylistService.get_playlist_details(current_user, playlist_id, db)
    if not playlist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Playlist with ID {playlist_id} not found."
        )

    continue_sessions = PlaybackSessionService.get_continue_listening(current_user=current_user, limit=50, session=db)
    target_session = next((s for s in continue_sessions if s["playlist_id"] == playlist_id), None)

    if target_session:
        return {
            "session_id": target_session["session_id"],
            "playlist_id": target_session["playlist_id"],
            "current_song_index": target_session["current_song_index"],
            "current_position": target_session["current_position"],
            "started_at": target_session["started_at"],
            "updated_at": target_session["updated_at"],
            "finished_at": None,
            "completed": False,
        }
    else:
        psession = PlaybackSessionService.start_session(
            current_user=current_user,
            playlist_id=playlist_id,
            song_index=0,
            position=0.0,
            session=db
        )
        return {
            "session_id": psession.id,
            "playlist_id": psession.playlist_id,
            "current_song_index": psession.current_song_index,
            "current_position": psession.current_position,
            "started_at": psession.started_at.isoformat(),
            "updated_at": psession.updated_at.isoformat(),
            "finished_at": None,
            "completed": False,
        }

@router.put("/playlists/{playlist_id}/progress")
def update_playlist_playback_progress(
    playlist_id: int,
    session_id: int = Query(..., description="PlaybackSession ID to update"),
    payload: PlaySessionProgressRequest = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Syncs active session track index, position, and completion status."""
    if not payload:
        raise HTTPException(status_code=400, detail="Progress payload required.")

    updated = PlaybackSessionService.update_progress(
        current_user=current_user,
        session_id=session_id,
        song_index=payload.song_index,
        position=payload.position,
        completed=payload.completed or False,
        session=db
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Playback session {session_id} not found."
        )
    return {"session_id": session_id, "message": "Progress synced successfully."}

@router.get("/playlists/{playlist_id}/cover")
def get_playlist_cover(
    playlist_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Streams dynamic composite cover artwork JPEG binary for a playlist."""
    try:
        binary_cover = PlaylistArtworkService.generate_cover(playlist_id, db)
        return Response(content=binary_cover, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate cover art for playlist {playlist_id}: {str(e)}"
        )
