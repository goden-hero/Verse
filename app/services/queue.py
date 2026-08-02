"""QueueService to manage user-scoped playback queues."""

import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import QueueItem, Song
from app.identity import CurrentUser

logger = logging.getLogger("music_rec.services.queue")


class QueueService:
    """Manages user-scoped playback queue items."""

    @staticmethod
    def get_queue(current_user: CurrentUser, session: Session) -> list[dict]:
        """Retrieves queue items for the current user ordered by position."""
        if not current_user.id:
            return []

        items = (
            session.query(QueueItem)
            .filter(QueueItem.user_id == current_user.id)
            .order_by(QueueItem.position.asc())
            .all()
        )

        results = []
        for item in items:
            song = session.get(Song, item.song_id)
            if song:
                results.append({
                    "id": item.id,
                    "song_id": item.song_id,
                    "position": item.position,
                    "title": song.title,
                    "artist": song.artist,
                    "album": song.album,
                    "duration": song.duration,
                    "added_at": item.added_at.isoformat() if item.added_at else None,
                })
        return results

    @staticmethod
    def enqueue(current_user: CurrentUser, song_id: int, session: Session) -> dict:
        """Appends a song to the current user's queue."""
        if not current_user.id:
            raise ValueError("User must be authenticated to enqueue songs.")

        song = session.get(Song, song_id)
        if not song:
            raise ValueError(f"Song with ID {song_id} not found.")

        # Find next available position
        max_pos = (
            session.query(QueueItem.position)
            .filter(QueueItem.user_id == current_user.id)
            .order_by(QueueItem.position.desc())
            .first()
        )
        next_pos = (max_pos[0] + 1) if max_pos else 0

        item = QueueItem(
            user_id=current_user.id,
            song_id=song_id,
            position=next_pos,
            added_at=datetime.utcnow(),
        )
        session.add(item)
        session.commit()

        logger.info("User %s enqueued song %d at position %d", current_user.id, song_id, next_pos)
        return {
            "id": item.id,
            "song_id": song_id,
            "position": next_pos,
            "title": song.title,
            "artist": song.artist,
        }

    @staticmethod
    def dequeue(current_user: CurrentUser, position: int, session: Session) -> bool:
        """Removes a song from the current user's queue at a given position."""
        if not current_user.id:
            return False

        item = (
            session.query(QueueItem)
            .filter_by(user_id=current_user.id, position=position)
            .first()
        )
        if not item:
            return False

        session.delete(item)
        session.commit()
        logger.info("User %s dequeued position %d", current_user.id, position)
        return True

    @staticmethod
    def clear_queue(current_user: CurrentUser, session: Session) -> None:
        """Clears all queued items for the current user."""
        if not current_user.id:
            return

        session.query(QueueItem).filter_by(user_id=current_user.id).delete()
        session.commit()
        logger.info("User %s cleared queue", current_user.id)
