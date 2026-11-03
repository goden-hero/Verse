"""Bounded, blob-free projections shared by playlist read endpoints."""

from sqlalchemy import func
from app.database.models import Playlist, PlaylistSong, PlaybackSession, Song


def song_totals(session):
    return (
        session.query(
            PlaylistSong.playlist_id.label("playlist_id"),
            func.count(PlaylistSong.song_id).label("songs_count"),
            func.sum(Song.duration).label("total_duration"),
        )
        .join(Song, Song.id == PlaylistSong.song_id)
        .group_by(PlaylistSong.playlist_id).subquery()
    )


def playlist_metadata_query(session, user_id):
    # Aggregate separately: joining raw sessions to raw memberships multiplies
    # rows and produces incorrect counts/durations.
    totals = song_totals(session)
    plays = session.query(
        PlaybackSession.playlist_id.label("playlist_id"),
        func.count(PlaybackSession.id).label("play_count"),
        func.max(PlaybackSession.started_at).label("last_played_at"),
    ).group_by(PlaybackSession.playlist_id).subquery()
    return session.query(
        Playlist,
        func.coalesce(totals.c.songs_count, 0).label("songs_count"),
        func.coalesce(totals.c.total_duration, 0.0).label("total_duration"),
        func.coalesce(plays.c.play_count, 0).label("play_count"),
        plays.c.last_played_at,
    ).outerjoin(totals, totals.c.playlist_id == Playlist.id).outerjoin(
        plays, plays.c.playlist_id == Playlist.id
    ).filter(Playlist.user_id == user_id)


def playlist_metadata_dict(row):
    playlist, count, duration, plays, last = row
    result = {column.name: getattr(playlist, column.name) for column in Playlist.__table__.columns}
    result.pop("user_id", None)
    for name in ("created_at", "updated_at"):
        value = result[name]
        result[name] = value.isoformat() if value else None
    result.update(songs_count=count, total_duration=duration, play_count=plays,
                  last_played_at=last.isoformat() if last else None)
    return result


def song_metadata_query(session):
    return session.query(
        Song.id, Song.title, Song.artist, Song.album, Song.duration,
        Song.original_genre.label("genre"),
        Song.cover_art.isnot(None).label("artwork_available"),
    )
