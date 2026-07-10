"""PlaylistService to manage playlist CRUD, ordering, and AI generation logic."""

import json
import logging
import random
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import Playlist, PlaylistSong, Song, SemanticTags
from app.services.search import SearchService, _expand_terms
from app.services.recommendation import RecommendationService

logger = logging.getLogger("music_rec.services.playlist")


def _song_matches_semantic(
    song_id: int,
    moods: list[str],
    activities: list[str],
    energy_min: float | None,
    energy_max: float | None,
    session: Session,
) -> bool:
    """Helper to check if a song matches semantic tag criteria."""
    if not moods and not activities and energy_min is None and energy_max is None:
        return True

    tag = session.get(SemanticTags, song_id)
    if not tag:
        return False

    moods_expanded = _expand_terms(moods or [])
    activities_expanded = _expand_terms(activities or [])

    # Match moods
    if moods_expanded:
        tag_moods = [m.lower().strip() for m in json.loads(tag.moods or "[]")]
        if not any(m in tag_moods for m in moods_expanded):
            return False

    # Match activities
    if activities_expanded:
        tag_acts = [a.lower().strip() for a in json.loads(tag.activities or "[]")]
        if not any(a in tag_acts for a in activities_expanded):
            return False

    # Match energy
    if energy_min is not None or energy_max is not None:
        energy_map = {"low": 0.2, "medium": 0.5, "high": 0.8}
        numeric_val = energy_map.get(tag.energy or "medium", 0.5)
        if energy_min is not None and numeric_val < energy_min:
            return False
        if energy_max is not None and numeric_val > energy_max:
            return False

    return True


class PlaylistService:
    """Manages manual, AI, and hybrid playlists, including automatic content selection."""

    @staticmethod
    def create_playlist(
        name: str,
        prompt: str | None,
        strategy: str | None,
        generated_by: str,
        session: Session,
    ) -> int:
        """Creates a new playlist record in the database."""
        playlist = Playlist(
            name=name,
            prompt=prompt,
            strategy=strategy,
            generated_by=generated_by,
            created_at=datetime.utcnow(),
        )
        session.add(playlist)
        session.commit()
        logger.info("Created playlist: %s (id: %s)", name, playlist.id)
        return playlist.id

    @staticmethod
    def add_songs_to_playlist(playlist_id: int, song_ids: list[int], session: Session) -> None:
        """Appends a list of song IDs to the playlist with positional ordering."""
        # Clear existing songs if any
        session.query(PlaylistSong).filter_by(playlist_id=playlist_id).delete()
        
        # Add new songs
        for pos, song_id in enumerate(song_ids):
            ps = PlaylistSong(
                playlist_id=playlist_id,
                song_id=song_id,
                position=pos,
            )
            session.add(ps)
        session.commit()
        logger.info("Added %d songs to playlist id %d", len(song_ids), playlist_id)

    @staticmethod
    def get_playlists(session: Session) -> list[dict]:
        """Retrieves metadata of all playlists."""
        playlists = session.query(Playlist).order_by(Playlist.created_at.desc()).all()
        results = []
        for p in playlists:
            songs_count = len(p.songs)
            total_duration = sum((ps.song.duration or 0.0) for ps in p.songs)
            results.append({
                "id": p.id,
                "name": p.name,
                "created_at": p.created_at.isoformat(),
                "prompt": p.prompt,
                "strategy": p.strategy,
                "generated_by": p.generated_by,
                "songs_count": songs_count,
                "total_duration": total_duration,
            })
        return results

    @staticmethod
    def get_playlist_songs(playlist_id: int, session: Session) -> list[dict]:
        """Retrieves all songs belonging to a playlist ordered by position."""
        playlist = session.get(Playlist, playlist_id)
        if not playlist:
            return []
        
        results = []
        for ps in playlist.songs:
            s = ps.song
            results.append({
                "id": s.id,
                "title": s.title,
                "artist": s.artist,
                "album": s.album,
                "duration": s.duration,
                "position": ps.position,
            })
        return results

    @staticmethod
    def delete_playlist(playlist_id: int, session: Session) -> None:
        """Deletes a playlist by ID (cascades deletes to playlist_songs)."""
        playlist = session.get(Playlist, playlist_id)
        if playlist:
            session.delete(playlist)
            session.commit()
            logger.info("Deleted playlist id %d", playlist_id)

    @staticmethod
    def rename_playlist(playlist_id: int, new_name: str, session: Session) -> None:
        """Renames a playlist."""
        playlist = session.get(Playlist, playlist_id)
        if playlist:
            playlist.name = new_name
            session.commit()
            logger.info("Renamed playlist id %d to '%s'", playlist_id, new_name)

    @staticmethod
    def generate_playlist(
        name: str,
        strategy: str,
        filters: dict,
        target_length: int,
        session: Session,
        prompt: str | None = None,
    ) -> dict:
        """AI-orchestrated playlist generator delegating to search and recommendation engines."""
        candidate_ids = []

        # 1. Parse filters (moods, activities, energy)
        moods = filters.get("moods", [])
        activities = filters.get("activities", [])
        energy_min = filters.get("energy_min")
        energy_max = filters.get("energy_max")
        seed_song_title = filters.get("seed_song_title")

        # 2. Retrieve initial match pool using semantic search if parameters are present
        if moods or activities or (energy_min is not None) or (energy_max is not None):
            semantic_matches = SearchService.semantic_search(
                moods=moods,
                activities=activities,
                energy_min=energy_min,
                energy_max=energy_max,
                session=session,
            )
            candidate_ids.extend([s["id"] for s in semantic_matches])

        # 3. If seed song is specified, expand matching candidates list
        if seed_song_title:
            seed_song = session.query(Song).filter(Song.title.ilike(f"%{seed_song_title}%")).first()
            if not seed_song:
                seed_song = session.query(Song).filter(Song.title.like(f"%{seed_song_title}%")).first()
            if seed_song:
                candidate_ids.append(seed_song.id)
                # Fetch recommendations using specified strategy
                try:
                    recs = RecommendationService.recommend(
                        song_id=seed_song.id,
                        strategy=strategy or "hybrid",
                        limit=target_length * 2,  # Fetch more to allow post-filtering
                        session=session,
                    )
                    filtered_recs = [
                        r["id"] for r in recs
                        if _song_matches_semantic(r["id"], moods, activities, energy_min, energy_max, session)
                    ]
                    candidate_ids.extend(filtered_recs)
                except Exception as e:
                    logger.warning("Failed to fetch recommendations for seed: %s", e)

        # 4. De-duplicate list preserving initial sequence order
        seen = set()
        unique_candidates = []
        for cid in candidate_ids:
            if cid not in seen:
                seen.add(cid)
                unique_candidates.append(cid)

        # 5. Fallback check: if list is empty or shorter than 5 tracks, relax constraints step-by-step
        if len(unique_candidates) < 5:
            logger.info("Fewer than 5 candidates found. Relaxing semantic constraints...")

            # Step 5a: Drop energy constraint
            if (energy_min is not None) or (energy_max is not None):
                logger.info("Relaxing constraints: Dropping energy filters.")
                matches = SearchService.semantic_search(moods=moods, activities=activities, session=session)
                for s in matches:
                    if s["id"] not in seen:
                        seen.add(s["id"])
                        unique_candidates.append(s["id"])

            # Step 5b: Drop activities constraint
            if len(unique_candidates) < 5 and activities:
                logger.info("Relaxing constraints: Dropping activities filters.")
                matches = SearchService.semantic_search(moods=moods, energy_min=energy_min, energy_max=energy_max, session=session)
                for s in matches:
                    if s["id"] not in seen:
                        seen.add(s["id"])
                        unique_candidates.append(s["id"])

            # Step 5c: Drop both energy and activities
            if len(unique_candidates) < 5 and activities and ((energy_min is not None) or (energy_max is not None)):
                logger.info("Relaxing constraints: Dropping both activities and energy filters.")
                matches = SearchService.semantic_search(moods=moods, session=session)
                for s in matches:
                    if s["id"] not in seen:
                        seen.add(s["id"])
                        unique_candidates.append(s["id"])

            # Step 5d: Absolute fallback to random library padding
            if len(unique_candidates) < 5:
                logger.warning("Still fewer than 5 candidates. Padding with random library songs.")
                all_songs = session.query(Song).all()
                random.shuffle(all_songs)
                for s in all_songs:
                    if s.id not in seen:
                        seen.add(s.id)
                        unique_candidates.append(s.id)

        # 6. Truncate to target length
        final_song_ids = unique_candidates[:target_length]

        # 7. Persist generated playlist to database
        playlist_id = PlaylistService.create_playlist(
            name=name,
            prompt=prompt,
            strategy=strategy,
            generated_by="AI",
            session=session,
        )
        PlaylistService.add_songs_to_playlist(playlist_id, final_song_ids, session)

        # 8. Return summary dictionary
        playlist = session.get(Playlist, playlist_id)
        songs_count = len(playlist.songs)
        total_duration = sum((ps.song.duration or 0.0) for ps in playlist.songs)

        return {
            "id": playlist_id,
            "name": name,
            "songs_count": songs_count,
            "total_duration": total_duration,
            "strategy": strategy,
            "songs": [
                {
                    "id": ps.song.id,
                    "title": ps.song.title,
                    "artist": ps.song.artist,
                }
                for ps in playlist.songs
            ]
        }
