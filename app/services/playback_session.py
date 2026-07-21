"""PlaybackSessionService to manage playback sessions, progress, and history."""

import logging
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database.models import PlaybackSession, Playlist

logger = logging.getLogger("music_rec.services.playback_session")


class PlaybackSessionService:
    """Manages active and historical playback sessions for playlists."""

    @staticmethod
    def start_session(
        playlist_id: int | None,
        song_index: int = 0,
        position: float = 0.0,
        session: Session = None,
    ) -> PlaybackSession:
        """Starts a new playback session when playback begins."""
        now = datetime.utcnow()
        psession = PlaybackSession(
            playlist_id=playlist_id,
            started_at=now,
            updated_at=now,
            current_song_index=song_index,
            current_position=position,
            completed=False,
        )
        session.add(psession)
        session.commit()
        logger.info(
            "Started playback session %d for playlist %s at song_index %d",
            psession.id,
            playlist_id,
            song_index,
        )
        return psession

    @staticmethod
    def update_progress(
        session_id: int,
        song_index: int,
        position: float,
        completed: bool = False,
        session: Session = None,
    ) -> PlaybackSession | None:
        """Updates active playback position and track index for a session."""
        psession = session.get(PlaybackSession, session_id)
        if not psession:
            logger.warning("Playback session %d not found", session_id)
            return None

        psession.current_song_index = song_index
        psession.current_position = position
        psession.updated_at = datetime.utcnow()

        if completed:
            psession.completed = True
            psession.finished_at = datetime.utcnow()

        session.commit()
        return psession

    @staticmethod
    def finish_session(session_id: int, session: Session) -> PlaybackSession | None:
        """Marks a session as finished."""
        return PlaybackSessionService.update_progress(
            session_id=session_id,
            song_index=0,
            position=0.0,
            completed=True,
            session=session,
        )

    @staticmethod
    def get_continue_listening(limit: int = 10, session: Session = None) -> list[dict]:
        """Retrieves list of active unfinished playback sessions ordered by updated_at desc."""
        subquery = (
            session.query(
                PlaybackSession.playlist_id,
                func.max(PlaybackSession.updated_at).label("max_updated"),
            )
            .filter(
                PlaybackSession.playlist_id.isnot(None),
                PlaybackSession.completed == False,
            )
            .group_by(PlaybackSession.playlist_id)
            .subquery()
        )

        latest_sessions = (
            session.query(PlaybackSession)
            .join(
                subquery,
                (PlaybackSession.playlist_id == subquery.c.playlist_id)
                & (PlaybackSession.updated_at == subquery.c.max_updated),
            )
            .order_by(PlaybackSession.updated_at.desc())
            .limit(limit)
            .all()
        )

        results = []
        for s in latest_sessions:
            if not s.playlist:
                continue
            total_duration = sum((ps.song.duration or 0.0) for ps in s.playlist.songs)
            results.append({
                "session_id": s.id,
                "playlist_id": s.playlist_id,
                "playlist_name": s.playlist.name,
                "song_count": len(s.playlist.songs),
                "total_duration": total_duration,
                "current_song_index": s.current_song_index,
                "current_position": s.current_position,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "started_at": s.started_at.isoformat() if s.started_at else None,
            })
        return results

    @staticmethod
    def get_recently_played_playlists(limit: int = 10, session: Session = None) -> list[dict]:
        """Retrieves playlists ordered by MAX(started_at) across all sessions."""
        subquery = (
            session.query(
                PlaybackSession.playlist_id,
                func.max(PlaybackSession.started_at).label("last_played"),
            )
            .filter(PlaybackSession.playlist_id.isnot(None))
            .group_by(PlaybackSession.playlist_id)
            .subquery()
        )

        recent = (
            session.query(Playlist, subquery.c.last_played)
            .join(subquery, Playlist.id == subquery.c.playlist_id)
            .order_by(subquery.c.last_played.desc())
            .limit(limit)
            .all()
        )

        results = []
        for playlist, last_played in recent:
            total_duration = sum((ps.song.duration or 0.0) for ps in playlist.songs)
            results.append({
                "id": playlist.id,
                "name": playlist.name,
                "created_at": playlist.created_at.isoformat(),
                "last_played_at": last_played.isoformat() if last_played else None,
                "generated_by": playlist.generated_by,
                "song_count": len(playlist.songs),
                "total_duration": total_duration,
            })
        return results

    @staticmethod
    def get_playlist_stats(playlist_id: int, session: Session) -> dict:
        """Computes dynamic statistics (play_count, last_played_at) for a playlist."""
        play_count = (
            session.query(func.count(PlaybackSession.id))
            .filter(PlaybackSession.playlist_id == playlist_id)
            .scalar()
            or 0
        )
        last_played = (
            session.query(func.max(PlaybackSession.started_at))
            .filter(PlaybackSession.playlist_id == playlist_id)
            .scalar()
        )
        return {
            "play_count": play_count,
            "last_played_at": last_played.isoformat() if last_played else None,
        }
