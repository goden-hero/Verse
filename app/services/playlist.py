"""PlaylistService to manage playlist CRUD, ordering, and AI generation logic."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import Playlist, PlaylistSong, Song, SemanticTags
from app.identity import CurrentUser
from app.services.search import SearchService, _expand_terms
from app.services.recommendation import RecommendationService
from app.recommendations.selector import map_ui_to_backend_strategy

logger = logging.getLogger("music_rec.services.playlist")


@dataclass(frozen=True)
class PlaylistCandidate:
    """Internal playlist candidate used between retrieval and construction stages."""

    song_id: int
    source: str
    similarity_score: float = 0.0
    confidence: float = 0.0


BASE_CONFIDENCE_BY_SOURCE = {
    "semantic": 1.0,
    "seed": 1.0,
    "hybrid_recommendation": 0.95,
    "vector_recommendation": 0.90,
    "content_recommendation": 0.85,
}

SEMANTIC_BOOST = 0.02
MIN_PLAYLIST_CONFIDENCE = 0.85


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

    if moods_expanded:
        tag_moods = [m.lower().strip() for m in json.loads(tag.moods or "[]")]
        if not any(m in tag_moods for m in moods_expanded):
            return False

    if activities_expanded:
        tag_acts = [a.lower().strip() for a in json.loads(tag.activities or "[]")]
        if not any(a in tag_acts for a in activities_expanded):
            return False

    if energy_min is not None or energy_max is not None:
        energy_map = {"low": 0.2, "medium": 0.5, "high": 0.8}
        numeric_val = energy_map.get(tag.energy or "medium", 0.5)
        if energy_min is not None and numeric_val < energy_min:
            return False
        if energy_max is not None and numeric_val > energy_max:
            return False

    return True


def _song_to_preview_dict(song: Song) -> dict:
    return {
        "id": song.id,
        "title": song.title,
        "artist": song.artist,
        "album": song.album,
        "duration": song.duration,
        "genre": song.original_genre,
        "artwork_available": song.cover_art is not None,
    }


def _find_seed_song(seed_song_title: str | None, session: Session) -> Song | None:
    if not seed_song_title:
        return None

    seed_song = session.query(Song).filter(Song.title.ilike(f"%{seed_song_title}%")).first()
    if not seed_song:
        seed_song = session.query(Song).filter(Song.title.like(f"%{seed_song_title}%")).first()
    return seed_song


def _dedupe_candidates(candidates: list[PlaylistCandidate]) -> list[PlaylistCandidate]:
    by_song_id = {}
    for candidate in candidates:
        existing = by_song_id.get(candidate.song_id)
        if not existing or candidate.confidence > existing.confidence:
            by_song_id[candidate.song_id] = candidate
    return list(by_song_id.values())


def _candidate_source_for_strategy(strategy: str | None) -> str:
    strategy_name = (strategy or "hybrid").lower().strip()
    if strategy_name not in {"hybrid", "vector", "content"}:
        strategy_name = "hybrid"
    return f"{strategy_name}_recommendation"


def _semantic_match_count(
    song_id: int,
    moods: list[str],
    activities: list[str],
    energy_min: float | None,
    energy_max: float | None,
    session: Session,
) -> int:
    tag = session.get(SemanticTags, song_id)
    if not tag:
        return 0

    count = 0
    moods_expanded = _expand_terms(moods or [])
    activities_expanded = _expand_terms(activities or [])

    if moods_expanded:
        tag_moods = [m.lower().strip() for m in json.loads(tag.moods or "[]")]
        count += sum(1 for mood in moods_expanded if mood in tag_moods)

    if activities_expanded:
        tag_acts = [a.lower().strip() for a in json.loads(tag.activities or "[]")]
        count += sum(1 for activity in activities_expanded if activity in tag_acts)

    if energy_min is not None or energy_max is not None:
        energy_map = {"low": 0.2, "medium": 0.5, "high": 0.8}
        numeric_val = energy_map.get(tag.energy or "medium", 0.5)
        if (energy_min is None or numeric_val >= energy_min) and (energy_max is None or numeric_val <= energy_max):
            count += 1

    return count


def _score_candidate_confidence(
    candidate: PlaylistCandidate,
    filters: dict,
    session: Session,
) -> PlaylistCandidate:
    base_confidence = BASE_CONFIDENCE_BY_SOURCE.get(candidate.source, 0.70)
    match_count = _semantic_match_count(
        song_id=candidate.song_id,
        moods=filters.get("moods", []),
        activities=filters.get("activities", []),
        energy_min=filters.get("energy_min"),
        energy_max=filters.get("energy_max"),
        session=session,
    )
    final_confidence = min(1.0, base_confidence + (match_count * SEMANTIC_BOOST))
    return PlaylistCandidate(
        song_id=candidate.song_id,
        source=candidate.source,
        similarity_score=candidate.similarity_score,
        confidence=final_confidence,
    )


def _rank_candidates(candidates: list[PlaylistCandidate], session: Session) -> list[PlaylistCandidate]:
    artist_counts = {}
    ranked = []

    sorted_candidates = sorted(
        candidates,
        key=lambda c: (c.confidence, c.similarity_score),
        reverse=True,
    )

    for candidate in sorted_candidates:
        song = session.get(Song, candidate.song_id)
        artist = song.artist if song and song.artist else "Unknown Artist"
        count = artist_counts.get(artist, 0)
        adjusted_score = candidate.confidence - (count * 0.05)
        ranked.append((adjusted_score, candidate))
        artist_counts[artist] = count + 1

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in ranked]


def _apply_confidence_threshold(
    candidates: list[PlaylistCandidate],
    min_confidence: float = MIN_PLAYLIST_CONFIDENCE,
) -> list[PlaylistCandidate]:
    confident = []
    for candidate in candidates:
        if candidate.confidence >= min_confidence:
            confident.append(candidate)
        else:
            break
    return confident


def _build_shortfall_metadata(requested_length: int, found_length: int) -> dict:
    if found_length >= requested_length:
        return {
            "requested_length": requested_length,
            "found_length": found_length,
            "shortfall_reason": None,
            "feedback_message": None,
        }

    reason = (
        f"Only {found_length} song(s) strongly matched your constraints out of {requested_length} requested. "
        "Relaxing filters or scanning more songs will increase match size."
    )
    feedback = (
        f"Found {found_length} high-quality match(es) matching your request (requested {requested_length})."
    )
    return {
        "requested_length": requested_length,
        "found_length": found_length,
        "shortfall_reason": reason,
        "feedback_message": feedback,
    }


def _retrieve_initial_candidates(filters: dict, session: Session) -> list[PlaylistCandidate]:
    seed_song_ids = filters.get("seed_song_ids", [])
    seed_candidates = [
        PlaylistCandidate(song_id=song_id, source="seed", similarity_score=1.0, confidence=1.0)
        for song_id in seed_song_ids
        if session.get(Song, song_id)
    ]
    if not seed_candidates:
        seed_song = _find_seed_song(filters.get("seed_song_title"), session)
        seed_candidates = (
            [PlaylistCandidate(song_id=seed_song.id, source="seed", similarity_score=1.0, confidence=1.0)]
            if seed_song
            else []
        )

    semantic_songs = SearchService.semantic_search(
        moods=filters.get("moods", []),
        activities=filters.get("activities", []),
        energy_min=filters.get("energy_min"),
        energy_max=filters.get("energy_max"),
        session=session,
    )
    semantic_candidates = [
        PlaylistCandidate(song_id=song["id"], source="semantic", similarity_score=1.0, confidence=1.0)
        for song in semantic_songs
    ]

    return _dedupe_candidates([*seed_candidates, *semantic_candidates])


def _retrieve_fallback_seeds(filters: dict, session: Session) -> list[PlaylistCandidate]:
    moods = filters.get("moods", [])
    activities = filters.get("activities", [])
    query_terms = [*moods, *activities]

    fallback_songs = []
    for term in query_terms:
        matches = SearchService.metadata_search(query=term, session=session)
        for m in matches:
            if not any(fs["id"] == m["id"] for fs in fallback_songs):
                fallback_songs.append(m)

    return [
        PlaylistCandidate(song_id=song["id"], source="semantic", similarity_score=0.8, confidence=0.90)
        for song in fallback_songs
    ]


def _validate_candidates_semantically(
    candidates: list[PlaylistCandidate],
    filters: dict,
    session: Session,
) -> list[PlaylistCandidate]:
    valid = []
    for candidate in candidates:
        if _song_matches_semantic(
            song_id=candidate.song_id,
            moods=filters.get("moods", []),
            activities=filters.get("activities", []),
            energy_min=filters.get("energy_min"),
            energy_max=filters.get("energy_max"),
            session=session,
        ):
            valid.append(candidate)
    return valid


def _expand_candidates_from_recommendations(
    seeds: list[PlaylistCandidate],
    strategy: str,
    filters: dict,
    target_length: int,
    session: Session,
) -> list[PlaylistCandidate]:
    source_name = _candidate_source_for_strategy(strategy)
    rec_candidates = []
    seed_song_ids = [candidate.song_id for candidate in seeds[:3]]

    for seed_id in seed_song_ids:
        recs = RecommendationService.recommend(
            song_id=seed_id,
            strategy=strategy,
            limit=target_length,
            session=session,
        )
        for rec in recs:
            if _song_matches_semantic(
                song_id=rec["id"],
                moods=filters.get("moods", []),
                activities=filters.get("activities", []),
                energy_min=filters.get("energy_min"),
                energy_max=filters.get("energy_max"),
                session=session,
            ):
                candidate = PlaylistCandidate(
                    song_id=rec["id"],
                    source=source_name,
                    similarity_score=rec.get("score", 0.0),
                )
                rec_candidates.append(_score_candidate_confidence(candidate, filters, session))

    return rec_candidates


def _construct_playlist_candidates(
    strategy: str,
    filters: dict,
    target_length: int,
    session: Session,
) -> list[PlaylistCandidate]:
    if not filters.get("seed_song_ids") and not filters.get("seed_song_title") and not filters.get("moods") and not filters.get("activities") and filters.get("energy_min") is None and filters.get("energy_max") is None:
        return []

    strategy = map_ui_to_backend_strategy(strategy, session)

    initial_candidates = _validate_candidates_semantically(
        _retrieve_initial_candidates(filters, session),
        filters,
        session,
    )
    logger.info("[PlaylistService] Direct semantic seeds found: %d matches", len(initial_candidates))

    if not initial_candidates:
        fallback_seeds = _retrieve_fallback_seeds(filters, session)
        logger.info("[PlaylistService] Using fallback seeds: %d candidates", len(fallback_seeds))
        initial_candidates = fallback_seeds

    if len(initial_candidates) >= target_length:
        ranked_candidates = _rank_candidates(initial_candidates, session)
        confident_candidates = _apply_confidence_threshold(ranked_candidates)
        logger.info("[PlaylistService] Direct matches sufficient: returning %d tracks", len(confident_candidates[:target_length]))
        return confident_candidates[:target_length]

    expanded_candidates = _expand_candidates_from_recommendations(
        seeds=initial_candidates,
        strategy=strategy,
        filters=filters,
        target_length=target_length,
        session=session,
    )
    logger.info("[PlaylistService] Expanded recommendation candidates: %d matches", len(expanded_candidates))

    candidates = _dedupe_candidates([*initial_candidates, *expanded_candidates])
    ranked_candidates = _rank_candidates(candidates, session)
    confident_candidates = _apply_confidence_threshold(ranked_candidates)
    logger.info("[PlaylistService] Final candidates after ranking: %d matches", len(confident_candidates[:target_length]))
    return confident_candidates[:target_length]


class PlaylistService:
    """Manages manual, AI, and hybrid playlists, including automatic content selection."""

    @staticmethod
    def create_playlist(
        current_user: CurrentUser,
        name: str = "",
        prompt: str | None = None,
        strategy: str | None = None,
        generated_by: str = "MANUAL",
        session: Session = None,
        description: str | None = None,
        seed_type: str | None = None,
        seed_song_id: int | None = None,
        generator_version: str | None = None,
        llm_model: str | None = None,
        created_from: str | None = None,
        commit: bool = True,
    ) -> int:
        """Creates a new playlist record in the database for the current user."""
        user_id = current_user.id or 1
        now = datetime.utcnow()

        playlist = Playlist(
            user_id=user_id,
            name=name,
            description=description,
            prompt=prompt,
            strategy=strategy,
            seed_type=seed_type,
            seed_song_id=seed_song_id,
            generated_by=generated_by,
            generator_version=generator_version,
            llm_model=llm_model,
            created_from=created_from,
            created_at=now,
            updated_at=now,
        )
        session.add(playlist)
        session.flush()
        if commit:
            session.commit()
        logger.info("Created playlist: %s (id: %s, user_id: %s)", name, playlist.id, user_id)
        return playlist.id

    @staticmethod
    def add_songs_to_playlist(
        current_user: CurrentUser,
        playlist_id: int,
        song_ids: list[int],
        session: Session,
        commit: bool = True,
    ) -> None:
        """Appends a list of song IDs to the user-owned playlist with positional ordering."""
        user_id = current_user.id or 1
        song_ids = song_ids or []

        playlist = (
            session.query(Playlist)
            .filter_by(id=playlist_id, user_id=user_id)
            .first()
        )
        if not playlist:
            raise ValueError(f"Playlist with ID {playlist_id} not found for user {user_id}.")

        session.query(PlaylistSong).filter_by(playlist_id=playlist_id).delete()

        for pos, song_id in enumerate(song_ids):
            ps = PlaylistSong(
                playlist_id=playlist_id,
                song_id=song_id,
                position=pos,
            )
            session.add(ps)

        playlist.updated_at = datetime.utcnow()

        if commit:
            session.commit()

        from app.services.playlist_artwork import PlaylistArtworkService
        PlaylistArtworkService.invalidate_cover(playlist_id)

        logger.info("Added %d songs to playlist id %d for user %s", len(song_ids), playlist_id, user_id)

    @staticmethod
    def update_playlist(
        current_user: CurrentUser,
        playlist_id: int,
        name: str | None = None,
        description: str | None = None,
        song_ids: list[int] | None = None,
        session: Session = None,
    ) -> bool:
        """Updates name, description, and song list of a user-owned playlist."""
        user_id = current_user.id or 1

        playlist = (
            session.query(Playlist)
            .filter_by(id=playlist_id, user_id=user_id)
            .first()
        )
        if not playlist:
            return False

        if name is not None:
            playlist.name = name.strip()
        if description is not None:
            playlist.description = description.strip()

        playlist.updated_at = datetime.utcnow()
        session.commit()

        if song_ids is not None:
            PlaylistService.add_songs_to_playlist(
                current_user=current_user,
                playlist_id=playlist_id,
                song_ids=song_ids,
                session=session,
            )

        return True

    @staticmethod
    def get_playlists(
        current_user: CurrentUser,
        session: Session,
        section: str = "all",
        limit: int = 50,
    ) -> list[dict]:
        """Retrieves metadata of playlists for the current user with optional section filtering."""
        user_id = current_user.id or 1

        if section == "recently_played":
            from app.services.playback_session import PlaybackSessionService
            return PlaybackSessionService.get_recently_played_playlists(
                current_user=current_user, limit=limit, session=session
            )

        query = session.query(Playlist).filter(Playlist.user_id == user_id)
        if section == "recently_added":
            query = query.order_by(Playlist.created_at.desc())
        else:
            query = query.order_by(Playlist.updated_at.desc())

        playlists = query.limit(limit).all()
        results = []
        from app.services.playback_session import PlaybackSessionService
        for p in playlists:
            songs_count = len(p.songs)
            total_duration = sum((ps.song.duration or 0.0) for ps in p.songs)
            stats = PlaybackSessionService.get_playlist_stats(current_user=current_user, playlist_id=p.id, session=session)
            results.append({
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "created_at": p.created_at.isoformat(),
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                "prompt": p.prompt,
                "strategy": p.strategy,
                "seed_type": p.seed_type,
                "generated_by": p.generated_by,
                "generator_version": p.generator_version,
                "llm_model": p.llm_model,
                "created_from": p.created_from,
                "songs_count": songs_count,
                "total_duration": total_duration,
                "play_count": stats["play_count"],
                "last_played_at": stats["last_played_at"],
            })
        return results

    @staticmethod
    def get_playlist_details(
        current_user: CurrentUser,
        playlist_id: int,
        session: Session,
    ) -> dict | None:
        """Retrieves complete details of a single user-owned playlist."""
        user_id = current_user.id or 1

        playlist = (
            session.query(Playlist)
            .filter_by(id=playlist_id, user_id=user_id)
            .first()
        )
        if not playlist:
            return None

        from app.services.playback_session import PlaybackSessionService
        stats = PlaybackSessionService.get_playlist_stats(current_user=current_user, playlist_id=playlist_id, session=session)
        songs_count = len(playlist.songs)
        total_duration = sum((ps.song.duration or 0.0) for ps in playlist.songs)

        seed_song_title = playlist.seed_song.title if playlist.seed_song else None

        return {
            "id": playlist.id,
            "name": playlist.name,
            "description": playlist.description,
            "created_at": playlist.created_at.isoformat(),
            "updated_at": playlist.updated_at.isoformat() if playlist.updated_at else None,
            "prompt": playlist.prompt,
            "strategy": playlist.strategy,
            "seed_type": playlist.seed_type,
            "seed_song_id": playlist.seed_song_id,
            "seed_song_title": seed_song_title,
            "generated_by": playlist.generated_by,
            "generator_version": playlist.generator_version,
            "llm_model": playlist.llm_model,
            "created_from": playlist.created_from,
            "songs_count": songs_count,
            "total_duration": total_duration,
            "play_count": stats["play_count"],
            "last_played_at": stats["last_played_at"],
            "songs": [
                {
                    "id": ps.song.id,
                    "title": ps.song.title,
                    "artist": ps.song.artist,
                    "album": ps.song.album,
                    "duration": ps.song.duration,
                    "genre": ps.song.original_genre or "Unknown",
                    "position": ps.position,
                    "artwork_available": ps.song.cover_art is not None,
                    "date_added": playlist.created_at.strftime("%b %d, %Y") if playlist.created_at else None,
                }
                for ps in playlist.songs if ps.song
            ],
        }

    @staticmethod
    def get_playlist_songs(
        current_user: CurrentUser,
        playlist_id: int,
        session: Session,
    ) -> list[dict]:
        """Retrieves all songs belonging to a user-owned playlist ordered by position."""
        user_id = current_user.id or 1

        playlist = (
            session.query(Playlist)
            .filter_by(id=playlist_id, user_id=user_id)
            .first()
        )
        if not playlist:
            return []

        results = []
        for ps in playlist.songs:
            s = ps.song
            if s:
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
    def delete_playlist(
        current_user: CurrentUser,
        playlist_id: int,
        session: Session,
    ) -> None:
        """Deletes a user-owned playlist by ID."""
        user_id = current_user.id or 1

        playlist = (
            session.query(Playlist)
            .filter_by(id=playlist_id, user_id=user_id)
            .first()
        )
        if playlist:
            session.delete(playlist)
            session.commit()
            from app.services.playlist_artwork import PlaylistArtworkService
            PlaylistArtworkService.invalidate_cover(playlist_id)
            logger.info("Deleted playlist id %d for user %s", playlist_id, user_id)

    @staticmethod
    def rename_playlist(
        current_user: CurrentUser,
        playlist_id: int,
        new_name: str,
        session: Session,
    ) -> None:
        """Renames a user-owned playlist."""
        PlaylistService.update_playlist(
            current_user=current_user,
            playlist_id=playlist_id,
            name=new_name,
            session=session,
        )

    @staticmethod
    def generate_playlist_preview(
        current_user: CurrentUser,
        strategy: str = "hybrid",
        filters: dict = None,
        target_length: int = 20,
        session: Session = None,
    ) -> list[dict]:
        """Generates list of recommended songs based on rules without persisting to database."""
        details = PlaylistService.generate_playlist_preview_details(
            current_user=current_user,
            strategy=strategy,
            filters=filters,
            target_length=target_length,
            session=session,
        )
        return details["songs"]

    @staticmethod
    def generate_playlist_preview_details(
        current_user: CurrentUser,
        strategy: str = "hybrid",
        filters: dict = None,
        target_length: int = 20,
        session: Session = None,
        name: str = "Generated Preview",
        enable_naming: bool = True,
    ) -> dict:
        """Generates temporary playlist preview details including shortfall feedback metadata and LLM naming."""
        filters = filters or {}
        final_candidates = _construct_playlist_candidates(
            strategy=strategy,
            filters=filters,
            target_length=target_length,
            session=session,
        )

        results = []
        for candidate in final_candidates:
            song = session.get(Song, candidate.song_id)
            if song:
                results.append(_song_to_preview_dict(song))

        total_duration = sum((s.get("duration") or 0.0) for s in results)
        shortfall = _build_shortfall_metadata(target_length, len(results))

        final_title, final_desc = name, None
        if results and enable_naming:
            try:
                from app.assistant.parser import LLMParser
                parser = LLMParser(disable_health_check=True)
                final_title, final_desc = parser.generate_playlist_name(
                    songs=results,
                    prompt=name if name != "Generated Preview" else None,
                    filters=filters,
                    default_name=name,
                )
            except Exception as err:
                logger.warning("Failed calling LLM playlist naming preview: %s", err)

        return {
            "name": final_title,
            "description": final_desc,
            "songs_count": len(results),
            "total_duration": total_duration,
            "strategy": strategy,
            "requested_length": shortfall["requested_length"],
            "found_length": shortfall["found_length"],
            "shortfall_reason": shortfall["shortfall_reason"],
            "feedback_message": shortfall["feedback_message"],
            "songs": results,
        }

    @staticmethod
    def generate_playlist(
        current_user: CurrentUser,
        name: str = "",
        strategy: str = "hybrid",
        filters: dict = None,
        target_length: int = 20,
        session: Session = None,
        prompt: str | None = None,
        enable_naming: bool = True,
    ) -> dict:
        """AI-orchestrated playlist generator delegating to search and recommendation engines."""
        filters = filters or {}

        final_candidates = _construct_playlist_candidates(
            strategy=strategy,
            filters=filters,
            target_length=target_length,
            session=session,
        )
        final_song_ids = [candidate.song_id for candidate in final_candidates]

        songs_for_naming = []
        for sid in final_song_ids:
            s = session.get(Song, sid)
            if s:
                songs_for_naming.append({"title": s.title, "artist": s.artist, "genre": s.original_genre})

        final_title, final_desc = name, None
        if songs_for_naming and enable_naming:
            try:
                from app.assistant.parser import LLMParser
                parser = LLMParser(disable_health_check=True)
                final_title, final_desc = parser.generate_playlist_name(
                    songs=songs_for_naming,
                    prompt=prompt or name,
                    filters=filters,
                    default_name=name,
                )
            except Exception as err:
                logger.warning("Failed calling LLM playlist naming: %s", err)

        playlist_id = PlaylistService.create_playlist(
            current_user=current_user,
            name=final_title,
            description=final_desc,
            prompt=prompt,
            strategy=strategy,
            generated_by="AI",
            session=session,
        )
        PlaylistService.add_songs_to_playlist(
            current_user=current_user,
            playlist_id=playlist_id,
            song_ids=final_song_ids,
            session=session,
        )

        playlist = session.get(Playlist, playlist_id)
        songs_count = len(playlist.songs)
        total_duration = sum((ps.song.duration or 0.0) for ps in playlist.songs)
        shortfall = _build_shortfall_metadata(target_length, songs_count)

        return {
            "id": playlist_id,
            "name": playlist.name,
            "description": playlist.description,
            "songs_count": songs_count,
            "total_duration": total_duration,
            "strategy": strategy,
            "requested_length": shortfall["requested_length"],
            "found_length": shortfall["found_length"],
            "shortfall_reason": shortfall["shortfall_reason"],
            "feedback_message": shortfall["feedback_message"],
            "songs": [
                {
                    "id": ps.song.id,
                    "title": ps.song.title,
                    "artist": ps.song.artist,
                }
                for ps in playlist.songs
            ],
        }
