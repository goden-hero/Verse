"""PlaybackSessionService to manage user-scoped playback sessions, progress, and history."""

import logging
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database.models import PlaybackSession, Playlist
from app.identity import CurrentUser
from app.services.playlist_metadata import song_totals, playlist_metadata_query, playlist_metadata_dict

logger = logging.getLogger("music_rec.services.playback_session")


class PlaybackSessionService:
    """Manages active and historical user-scoped playback sessions for playlists."""

    @staticmethod
    def start_session(
        current_user: CurrentUser,
        playlist_id: int | None = None,
        song_index: int = 0,
        position: float = 0.0,
        session: Session = None,
    ) -> PlaybackSession:
        """Starts a new playback session when playback begins."""
        user_id = current_user.id or 1

        if playlist_id is not None:
            playlist = (
                session.query(Playlist)
                .filter_by(id=playlist_id, user_id=user_id)
                .first()
            )
            if not playlist:
                raise ValueError(f"Playlist {playlist_id} not found for user {user_id}.")

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
            "Started playback session %d for playlist %s (user %s) at song_index %d",
            psession.id,
            playlist_id,
            user_id,
            song_index,
        )
        return psession

    @staticmethod
    def update_progress(
        current_user: CurrentUser,
        session_id: int = 0,
        song_index: int = 0,
        position: float = 0.0,
        completed: bool = False,
        session: Session = None,
    ) -> PlaybackSession | None:
        """Updates active playback position and track index for a session."""
        user_id = current_user.id or 1
        psession = session.get(PlaybackSession, session_id)
        if not psession:
            logger.warning("Playback session %d not found", session_id)
            return None

        if psession.playlist and psession.playlist.user_id != user_id:
            logger.warning("User %s attempted to update session %d owned by user %s", user_id, session_id, psession.playlist.user_id)
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
    def finish_session(
        current_user: CurrentUser,
        session_id: int = 0,
        session: Session = None,
    ) -> PlaybackSession | None:
        """Marks a session as finished."""
        return PlaybackSessionService.update_progress(
            current_user=current_user,
            session_id=session_id,
            song_index=0,
            position=0.0,
            completed=True,
            session=session,
        )

    @staticmethod
    def get_continue_listening(
        current_user: CurrentUser,
        limit: int = 10,
        session: Session = None,
    ) -> list[dict]:
        """Retrieves list of active unfinished playback sessions for current_user's playlists."""
        user_id = current_user.id or 1
        subquery = (
            session.query(
                PlaybackSession.playlist_id,
                func.max(PlaybackSession.updated_at).label("max_updated"),
            )
            .join(Playlist, PlaybackSession.playlist_id == Playlist.id)
            .filter(
                PlaybackSession.playlist_id.isnot(None),
                PlaybackSession.completed == False,
                Playlist.user_id == user_id,
            )
            .group_by(PlaybackSession.playlist_id)
            .subquery()
        )

        totals = song_totals(session)
        latest_sessions = (
            session.query(PlaybackSession, Playlist.name,
                          func.coalesce(totals.c.songs_count, 0),
                          func.coalesce(totals.c.total_duration, 0.0))
            .join(Playlist, Playlist.id == PlaybackSession.playlist_id)
            .outerjoin(totals, totals.c.playlist_id == Playlist.id)
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
        for s, name, count, total_duration in latest_sessions:
            results.append({
                "session_id": s.id,
                "playlist_id": s.playlist_id,
                "playlist_name": name,
                "song_count": count,
                "total_duration": total_duration,
                "current_song_index": s.current_song_index,
                "current_position": s.current_position,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "started_at": s.started_at.isoformat() if s.started_at else None,
            })
        return results

    @staticmethod
    def get_recently_played_playlists(
        current_user: CurrentUser,
        limit: int = 10,
        session: Session = None,
    ) -> list[dict]:
        """Retrieves playlists owned by current_user ordered by MAX(started_at) across sessions."""
        user_id = current_user.id or 1
        subquery = (
            session.query(
                PlaybackSession.playlist_id,
                func.max(PlaybackSession.started_at).label("last_played"),
            )
            .join(Playlist, PlaybackSession.playlist_id == Playlist.id)
            .filter(
                PlaybackSession.playlist_id.isnot(None),
                Playlist.user_id == user_id,
            )
            .group_by(PlaybackSession.playlist_id)
            .subquery()
        )

        recent = (
            playlist_metadata_query(session, user_id)
            .join(subquery, Playlist.id == subquery.c.playlist_id)
            .filter(Playlist.user_id == user_id)
            .order_by(subquery.c.last_played.desc())
            .limit(limit)
            .all()
        )

        return [dict(playlist_metadata_dict(row), song_count=row.songs_count) for row in recent]

    @staticmethod
    def get_playlist_stats(
        current_user: CurrentUser,
        playlist_id: int = 0,
        session: Session = None,
    ) -> dict:
        """Computes dynamic statistics (play_count, last_played_at) for a user-owned playlist."""
        user_id = current_user.id or 1

        row = playlist_metadata_query(session, user_id).filter(Playlist.id == playlist_id).first()
        if not row:
            return {"play_count": 0, "last_played_at": None}
        return {
            "play_count": row.play_count,
            "last_played_at": row.last_played_at.isoformat() if row.last_played_at else None,
        }
