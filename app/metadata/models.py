"""Metadata models for songs."""

from dataclasses import dataclass


@dataclass
class SongMetadata:
    """Dataclass representing extracted audio file metadata tags."""

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    genre: str | None = None
    year: int | None = None
    duration: float | None = None  # Duration in seconds
    track_number: int | None = None
    disc_number: int | None = None
    cover_art: bytes | None = None  # Binary image data
