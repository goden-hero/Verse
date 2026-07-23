"""PlaylistService to manage playlist CRUD, ordering, and AI generation logic."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import Playlist, PlaylistSong, Song, SemanticTags
from app.services.search import SearchService, _expand_terms
from app.services.recommendation import RecommendationService

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
    moods = filters.get("moods", [])
    activities = filters.get("activities", [])
    energy_min = filters.get("energy_min")
    energy_max = filters.get("energy_max")

    base_confidence = BASE_CONFIDENCE_BY_SOURCE.get(candidate.source, 0.80)
    boost = SEMANTIC_BOOST * _semantic_match_count(
        song_id=candidate.song_id,
        moods=moods,
        activities=activities,
        energy_min=energy_min,
        energy_max=energy_max,
        session=session,
    )
    confidence = min(1.0, base_confidence + boost)

    return PlaylistCandidate(
        song_id=candidate.song_id,
        source=candidate.source,
        similarity_score=candidate.similarity_score,
        confidence=confidence,
    )


def _score_candidate_confidences(
    candidates: list[PlaylistCandidate],
    filters: dict,
    session: Session,
) -> list[PlaylistCandidate]:
    return [_score_candidate_confidence(candidate, filters, session) for candidate in candidates]


def _rank_candidates(
    candidates: list[PlaylistCandidate],
    session: Session,
) -> list[PlaylistCandidate]:
    """Ranks candidates by confidence, similarity, and artist diversity."""
    remaining = sorted(
        candidates,
        key=lambda candidate: (
            -candidate.confidence,
            -candidate.similarity_score,
            candidate.song_id,
        ),
    )
    ranked = []
    artist_counts = {}

    while remaining:
        best_index = min(
            range(len(remaining)),
            key=lambda index: (
                -remaining[index].confidence,
                -remaining[index].similarity_score,
                artist_counts.get(_candidate_artist(remaining[index], session), 0),
                remaining[index].song_id,
            ),
        )
        candidate = remaining.pop(best_index)
        artist = _candidate_artist(candidate, session)
        artist_counts[artist] = artist_counts.get(artist, 0) + 1
        ranked.append(candidate)

    return ranked


def _candidate_artist(candidate: PlaylistCandidate, session: Session) -> str:
    song = session.get(Song, candidate.song_id)
    if not song or not song.artist:
        return ""
    return song.artist.strip().lower()


def _apply_confidence_threshold(
    candidates: list[PlaylistCandidate],
    min_confidence: float = MIN_PLAYLIST_CONFIDENCE,
) -> list[PlaylistCandidate]:
    """Stops at the first ranked candidate below the minimum confidence."""
    accepted = []
    for candidate in candidates:
        if candidate.confidence < min_confidence:
            break
        accepted.append(candidate)
    return accepted


def _build_shortfall_metadata(requested_length: int, found_length: int) -> dict:
    if found_length < requested_length:
        reason = (
            f"Only {found_length} song(s) strongly matched your request criteria with sufficient confidence."
            if found_length > 0
            else "No songs matched your request criteria with sufficient confidence."
        )
        msg = (
            f"Found {found_length} high-quality match(es) matching your request (requested {requested_length}). Only these songs strongly matched your request."
            if found_length > 0
            else f"No high-quality matches found matching your request (requested {requested_length})."
        )
        return {
            "requested_length": requested_length,
            "found_length": found_length,
            "shortfall_reason": reason,
            "feedback_message": msg,
        }
    return {
        "requested_length": requested_length,
        "found_length": found_length,
        "shortfall_reason": None,
        "feedback_message": None,
    }


def _validate_candidates_semantically(
    candidates: list[PlaylistCandidate],
    filters: dict,
    session: Session,
) -> list[PlaylistCandidate]:
    """Keeps candidates that satisfy the original semantic filters."""
    moods = filters.get("moods", [])
    activities = filters.get("activities", [])
    energy_min = filters.get("energy_min")
    energy_max = filters.get("energy_max")

    return [
        candidate
        for candidate in candidates
        if _song_matches_semantic(candidate.song_id, moods, activities, energy_min, energy_max, session)
    ]



def _retrieve_initial_candidates(filters: dict, session: Session) -> list[PlaylistCandidate]:
    """Retrieves only direct semantic and seed-song matches."""
    candidates = []
    moods = filters.get("moods", [])
    activities = filters.get("activities", [])
    energy_min = filters.get("energy_min")
    energy_max = filters.get("energy_max")

    if moods or activities or (energy_min is not None) or (energy_max is not None):
        semantic_matches = SearchService.semantic_search(
            moods=moods,
            activities=activities,
            energy_min=energy_min,
            energy_max=energy_max,
            session=session,
        )
        candidates.extend(
            PlaylistCandidate(song_id=s["id"], source="semantic")
            for s in semantic_matches
        )

    seed_song = _find_seed_song(filters.get("seed_song_title"), session)
    if seed_song:
        candidates.append(PlaylistCandidate(song_id=seed_song.id, source="seed"))

    return _dedupe_candidates(_score_candidate_confidences(candidates, filters, session))


def _expand_candidates_from_recommendations(
    seeds: list[PlaylistCandidate],
    strategy: str,
    filters: dict,
    target_length: int,
    session: Session,
) -> list[PlaylistCandidate]:
    """Expands from the strongest direct matches and keeps only semantically valid recs."""
    if not seeds:
        return []

    expanded = []
    recommendation_source = _candidate_source_for_strategy(strategy)
    expansion_seeds = sorted(seeds, key=lambda c: c.confidence, reverse=True)[: max(1, min(3, target_length))]
    per_seed_limit = max(target_length * 2, 1)

    for seed in expansion_seeds:
        try:
            recs = RecommendationService.recommend(
                song_id=seed.song_id,
                strategy=strategy or "hybrid",
                limit=per_seed_limit,
                session=session,
            )
        except Exception as e:
            logger.warning("Failed to fetch recommendations for seed %s: %s", seed.song_id, e)
            continue

        for rec in recs:
            expanded.append(
                PlaylistCandidate(
                    song_id=rec["id"],
                    source=recommendation_source,
                    similarity_score=float(rec.get("score", 0.0)),
                )
            )

    validated_candidates = _validate_candidates_semantically(expanded, filters, session)
    scored_candidates = _score_candidate_confidences(validated_candidates, filters, session)
    return _dedupe_candidates(scored_candidates)


def _construct_playlist_candidates(
    strategy: str,
    filters: dict,
    target_length: int,
    session: Session,
) -> list[PlaylistCandidate]:
    """Runs retrieval, expansion, validation, and construction with target as an upper bound."""
    if target_length <= 0:
        return []

    initial_candidates = _validate_candidates_semantically(
        _retrieve_initial_candidates(filters, session),
        filters,
        session,
    )
    if len(initial_candidates) >= target_length:
        ranked_candidates = _rank_candidates(initial_candidates, session)
        confident_candidates = _apply_confidence_threshold(ranked_candidates)
        return confident_candidates[:target_length]

    expanded_candidates = _expand_candidates_from_recommendations(
        seeds=initial_candidates,
        strategy=strategy,
        filters=filters,
        target_length=target_length,
        session=session,
    )
    candidates = _dedupe_candidates([*initial_candidates, *expanded_candidates])
    ranked_candidates = _rank_candidates(candidates, session)
    confident_candidates = _apply_confidence_threshold(ranked_candidates)
    return confident_candidates[:target_length]


class PlaylistService:
    """Manages manual, AI, and hybrid playlists, including automatic content selection."""

    @staticmethod
    def create_playlist(
        name: str,
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
        """Creates a new playlist record in the database."""
        now = datetime.utcnow()
        playlist = Playlist(
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
        logger.info("Created playlist: %s (id: %s)", name, playlist.id)
        return playlist.id

    @staticmethod
    def add_songs_to_playlist(
        playlist_id: int,
        song_ids: list[int],
        session: Session,
        commit: bool = True,
    ) -> None:
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
        
        playlist = session.get(Playlist, playlist_id)
        if playlist:
            playlist.updated_at = datetime.utcnow()
            
        if commit:
            session.commit()
        
        # Invalidate cover cache
        from app.services.playlist_artwork import PlaylistArtworkService
        PlaylistArtworkService.invalidate_cover(playlist_id)
        
        logger.info("Added %d songs to playlist id %d", len(song_ids), playlist_id)

    @staticmethod
    def update_playlist(
        playlist_id: int,
        name: str | None = None,
        description: str | None = None,
        song_ids: list[int] | None = None,
        session: Session = None,
    ) -> bool:
        """Updates name, description, and song list of a playlist."""
        playlist = session.get(Playlist, playlist_id)
        if not playlist:
            return False

        if name is not None:
            playlist.name = name.strip()
        if description is not None:
            playlist.description = description.strip()

        playlist.updated_at = datetime.utcnow()
        session.commit()

        if song_ids is not None:
            PlaylistService.add_songs_to_playlist(playlist_id, song_ids, session)

        return True

    @staticmethod
    def get_playlists(
        session: Session,
        section: str = "all",
        limit: int = 50,
    ) -> list[dict]:
        """Retrieves metadata of playlists with optional section filtering."""
        if section == "recently_played":
            from app.services.playback_session import PlaybackSessionService
            return PlaybackSessionService.get_recently_played_playlists(limit=limit, session=session)

        query = session.query(Playlist)
        if section == "recently_added":
            query = query.order_by(Playlist.created_at.desc())
        else: # default/all
            query = query.order_by(Playlist.updated_at.desc())

        playlists = query.limit(limit).all()
        results = []
        from app.services.playback_session import PlaybackSessionService
        for p in playlists:
            songs_count = len(p.songs)
            total_duration = sum((ps.song.duration or 0.0) for ps in p.songs)
            stats = PlaybackSessionService.get_playlist_stats(p.id, session)
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
    def get_playlist_details(playlist_id: int, session: Session) -> dict | None:
        """Retrieves complete details of a single playlist including AI metadata and song list."""
        playlist = session.get(Playlist, playlist_id)
        if not playlist:
            return None

        from app.services.playback_session import PlaybackSessionService
        stats = PlaybackSessionService.get_playlist_stats(playlist_id, session)
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
                }
                for ps in playlist.songs if ps.song
            ]
        }

    @staticmethod
    def get_playlist_songs(playlist_id: int, session: Session) -> list[dict]:
        """Retrieves all songs belonging to a playlist ordered by position."""
        playlist = session.get(Playlist, playlist_id)
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
    def delete_playlist(playlist_id: int, session: Session) -> None:
        """Deletes a playlist by ID (cascades deletes to playlist_songs)."""
        playlist = session.get(Playlist, playlist_id)
        if playlist:
            session.delete(playlist)
            session.commit()
            from app.services.playlist_artwork import PlaylistArtworkService
            PlaylistArtworkService.invalidate_cover(playlist_id)
            logger.info("Deleted playlist id %d", playlist_id)

    @staticmethod
    def rename_playlist(playlist_id: int, new_name: str, session: Session) -> None:
        """Renames a playlist."""
        PlaylistService.update_playlist(playlist_id, name=new_name, session=session)

    @staticmethod
    def generate_playlist_preview(
        strategy: str,
        filters: dict,
        target_length: int,
        session: Session,
    ) -> list[dict]:
        """Generates list of recommended songs based on rules without persisting to database."""
        details = PlaylistService.generate_playlist_preview_details(
            strategy=strategy,
            filters=filters,
            target_length=target_length,
            session=session,
        )
        return details["songs"]

    @staticmethod
    def generate_playlist_preview_details(
        strategy: str,
        filters: dict,
        target_length: int,
        session: Session,
        name: str = "Generated Preview",
        enable_naming: bool = True,
    ) -> dict:
        """Generates temporary playlist preview details including shortfall feedback metadata and LLM naming."""
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
        name: str,
        strategy: str,
        filters: dict,
        target_length: int,
        session: Session,
        prompt: str | None = None,
        enable_naming: bool = True,
    ) -> dict:
        """AI-orchestrated playlist generator delegating to search and recommendation engines."""
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
            name=final_title,
            description=final_desc,
            prompt=prompt,
            strategy=strategy,
            generated_by="AI",
            session=session,
        )
        PlaylistService.add_songs_to_playlist(playlist_id, final_song_ids, session)

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
            ]
        }


