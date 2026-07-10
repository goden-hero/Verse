"""LibraryService managing files retrieval and scanning operations."""

import logging
from pathlib import Path
from sqlalchemy.orm import Session
from app.database.models import Song

logger = logging.getLogger("music_rec.services.library")


class LibraryService:
    """Service handling library listings, scans, and metadata lookups."""

    @staticmethod
    def get_all_songs(session: Session) -> list[dict]:
        """Retrieves all songs registered in the library."""
        songs = session.query(Song).order_by(Song.title).all()
        return [
            {
                "id": s.id,
                "title": s.title,
                "artist": s.artist,
                "album": s.album,
                "duration": s.duration,
                "original_genre": s.original_genre,
                "path": s.path,
            }
            for s in songs
        ]

    @staticmethod
    def get_song_by_title(title: str, session: Session) -> dict | None:
        """Finds a song by title matching (case-insensitive substring)."""
        term = f"%{title}%"
        s = session.query(Song).filter(Song.title.ilike(term)).first()
        if not s:
            s = session.query(Song).filter(Song.title.like(f"%{title}%")).first()
        if s:
            return {
                "id": s.id,
                "title": s.title,
                "artist": s.artist,
                "album": s.album,
                "duration": s.duration,
                "original_genre": s.original_genre,
                "path": s.path,
            }
        return None

    @staticmethod
    def scan_library(folder_path: str, session: Session) -> int:
        """Executes a library folder scanning task."""
        from app.ui.workers import ScanWorker
        from app.config.settings import settings
        
        logger.info("Triggering scan on folder: %s", folder_path)
        # Run ScanWorker synchronously since we're already in a QThread background context
        worker = ScanWorker(folder_path=folder_path, vector_index_path=settings.PROJECT_ROOT / "data" / "vector_index.bin")
        # Run it synchronously
        worker.run()
        return 0
