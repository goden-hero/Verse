import os
from pathlib import Path
from fastapi import APIRouter, Depends, Query, Request, Response, HTTPException, Header
from app.api.images import default_artwork, image_response, now_playing_artwork
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from app.api.dependencies import get_db
from app.api.schemas import SongListResponse, SongResponse
from app.services.library import LibraryService
from app.database.models import Song

router = APIRouter(tags=["Songs"])


@router.get("/artwork/default")
def get_default_artwork(request: Request):
    """Same-origin system-player fallback, with exactly 512×512 PNG pixels."""
    return image_response(default_artwork(), request, "image/png")

def _get_media_type(path_str: str) -> str:
    ext = Path(path_str).suffix.lower()
    mapping = {
        ".mp3": "audio/mpeg",
        ".flac": "audio/flac",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
    }
    return mapping.get(ext, "application/octet-stream")

@router.get("/songs", response_model=SongListResponse)
def get_songs(
    page: int = Query(default=1, ge=1, description="Page number starting from 1"),
    page_size: int = Query(default=100, ge=1, le=1000, description="Number of items per page"),
    db: Session = Depends(get_db)
):
    """Retrieves a paginated list of songs in the music library."""
    songs, total_count = LibraryService.get_songs_paginated(
        page=page,
        page_size=page_size,
        session=db
    )
    return SongListResponse(
        songs=songs,
        total_count=total_count,
        page=page,
        page_size=page_size
    )

@router.get("/songs/{song_id}", response_model=SongResponse)
def get_song(song_id: int, db: Session = Depends(get_db)):
    """Retrieves metadata of a single song by ID."""
    song = LibraryService.get_song_by_id(song_id, db)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    return song

@router.get("/songs/{song_id}/artwork")
def get_song_artwork(song_id: int, request: Request, fallback: bool = False, db: Session = Depends(get_db)):
    """Original cover by default; opt-in system artwork is always a valid image."""
    artwork_bytes = LibraryService.get_song_artwork(song_id, db)
    if fallback:
        data, media_type = now_playing_artwork(artwork_bytes)
        return image_response(data, request, media_type)
    if not artwork_bytes:
        raise HTTPException(status_code=404, detail="Artwork not found")
    return image_response(artwork_bytes, request)

@router.get("/songs/{song_id}/stream")
def stream_song(
    song_id: int,
    range_header: str | None = Header(default=None, alias="Range"),
    db: Session = Depends(get_db)
):
    """Streams the audio binary for a song with HTTP Range Requests support."""
    song_obj = db.query(Song.path).filter(Song.id == song_id).first()
    # The response needs only this immutable row. End the read transaction now
    # rather than holding a pool checkout for the duration of an audio stream.
    db.rollback()
    if not song_obj or not song_obj.path:
        raise HTTPException(status_code=404, detail="Song or file not found")
    
    file_path = Path(song_obj.path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file path does not exist on disk")

    file_size = file_path.stat().st_size
    media_type = _get_media_type(str(file_path))

    if not range_header:
        return FileResponse(
            path=str(file_path),
            media_type=media_type,
            headers={"Accept-Ranges": "bytes"}
        )

    try:
        # Range header format: bytes=start-end
        range_val = range_header.strip().replace("bytes=", "")
        parts = range_val.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Range header format")

    if start >= file_size or end >= file_size or start > end:
        raise HTTPException(
            status_code=416,
            detail="Requested Range Not Satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"}
        )

    chunk_size = (end - start) + 1

    def iterfile():
        with open(file_path, "rb") as f:
            f.seek(start)
            bytes_left = chunk_size
            while bytes_left > 0:
                read_len = min(65536, bytes_left)
                data = f.read(read_len)
                if not data:
                    break
                bytes_left -= len(data)
                yield data

    return StreamingResponse(
        iterfile(),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size),
        }
    )
