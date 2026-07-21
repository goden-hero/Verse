"""SearchService querying songs via metadata text search, vector search, or semantic tags."""

import json
import pickle
from pathlib import Path
from sqlalchemy.orm import Session
from app.config.settings import settings
from app.database.models import Embeddings, Song, SemanticTags
from app.search.index import FAISSIndex


SYNONYMS = {
    # Moods
    "sad": ["sad", "sadness", "melancholic", "somber", "depressing", "gloomy", "heartbroken", "sorrowful", "tearful", "grief", "pensive", "lonely"],
    "happy": ["happy", "happiness", "joyful", "cheerful", "upbeat", "excited", "energetic", "glad", "bright", "celebratory", "elated", "positive"],
    "relaxing": ["relaxing", "relaxed", "calm", "chill", "peaceful", "soothing", "tranquil", "mellow", "serene", "meditative", "quiet", "soft", "gentle"],
    "chill": ["chill", "mellow", "relaxed", "calm", "laid-back", "smooth", "easygoing", "lofi", "ambient"],
    "energetic": ["energetic", "excited", "upbeat", "workout", "hype", "pumped", "intense", "high-energy", "aggressive", "fast", "powerful", "heavy"],
    
    # Activities
    "studying": ["studying", "study", "concentration", "focus", "work", "reading", "coding", "writing"],
    "workout": ["workout", "gym", "running", "exercise", "training", "lifting", "cardio", "fitness", "active", "excited"],
    "sleeping": ["sleeping", "sleep", "bedtime", "relaxing", "dreaming", "night", "rest", "resting"],
}


def _expand_terms(query_list: list[str]) -> set[str]:
    expanded = set()
    for q in query_list:
        q_clean = q.lower().strip()
        if not q_clean:
            continue
        expanded.add(q_clean)
        if q_clean in SYNONYMS:
            expanded.update(SYNONYMS[q_clean])
        for parent, syns in SYNONYMS.items():
            if q_clean in syns:
                expanded.add(parent)
                expanded.update(syns)
    return expanded


class SearchService:
    """Consolidates text metadata matching, FAISS vector search, and semantic tag filter logic."""

    @staticmethod
    def ranked_metadata_search(query: str, session: Session) -> list[dict]:
        """Queries database and returns search results ranked by title/artist match priority."""
        query_clean = query.strip().lower()
        if not query_clean:
            return []

        term = f"%{query_clean}%"
        songs = (
            session.query(Song)
            .filter(
                Song.title.ilike(term)
                | Song.artist.ilike(term)
            )
            .all()
        )

        def get_rank_key(s):
            t = (s.title or "").lower().strip()
            a = (s.artist or "").lower().strip()
            
            if t == query_clean:
                rank = 1
            elif t.startswith(query_clean):
                rank = 2
            elif query_clean in t:
                rank = 3
            elif a == query_clean:
                rank = 4
            elif query_clean in a:
                rank = 5
            else:
                rank = 6
            return rank, t

        ranked_songs = sorted(songs, key=get_rank_key)

        return [
            {
                "id": s.id,
                "title": s.title,
                "artist": s.artist,
                "album": s.album,
                "duration": s.duration,
                "genre": s.original_genre,
                "artwork_available": s.cover_art is not None,
            }
            for s in ranked_songs
        ]

    @staticmethod
    def metadata_search(query: str, session: Session) -> list[dict]:
        """Queries the database for matching title, artist, album, or genre substring."""
        term = f"%{query}%"
        songs = (
            session.query(Song)
            .filter(
                Song.title.ilike(term)
                | Song.artist.ilike(term)
                | Song.album.ilike(term)
                | Song.original_genre.ilike(term)
            )
            .all()
        )
        return [
            {"id": s.id, "title": s.title, "artist": s.artist, "album": s.album}
            for s in songs
        ]

    @staticmethod
    def vector_search(query_song_title: str, session: Session, k: int = 6) -> list[dict]:
        """Queries FAISS index for similar songs based on a seed song title."""
        target_song = (
            session.query(Song)
            .filter(Song.title.ilike(f"%{query_song_title}%"))
            .first()
        )
        if not target_song:
            return []

        emb = session.get(Embeddings, target_song.id)
        if not emb or not emb.vector:
            return []

        try:
            vector = pickle.loads(emb.vector)
            index_path = Path(settings.PROJECT_ROOT) / "data" / "vector_index.bin"
            if not index_path.exists():
                return []
            idx = FAISSIndex(index_path)
            idx.load()
            matches = idx.search(vector, k=k)

            results = []
            for song_id, score in matches:
                song = session.get(Song, song_id)
                if song:
                    results.append({
                        "id": song.id,
                        "title": song.title,
                        "artist": song.artist,
                        "album": song.album,
                        "score": float(score),
                    })
            return results
        except Exception:
            return []

    @staticmethod
    def semantic_search(
        moods: list[str] = None,
        activities: list[str] = None,
        energy_min: float = None,
        energy_max: float = None,
        session: Session = None,
    ) -> list[dict]:
        """Filters songs by matching semantic tags (moods, activities, energy thresholds) in DB."""
        tag_records = session.query(SemanticTags).all()
        matching_song_ids = []

        moods_expanded = _expand_terms(moods or [])
        activities_expanded = _expand_terms(activities or [])

        for tag in tag_records:
            # Match moods
            if moods_expanded:
                tag_moods = [m.lower().strip() for m in json.loads(tag.moods or "[]")]
                if not any(m in tag_moods for m in moods_expanded):
                    continue

            # Match activities
            if activities_expanded:
                tag_acts = [a.lower().strip() for a in json.loads(tag.activities or "[]")]
                if not any(a in tag_acts for a in activities_expanded):
                    continue

            # Match energy
            if energy_min is not None or energy_max is not None:
                energy_map = {"low": 0.2, "medium": 0.5, "high": 0.8}
                numeric_val = energy_map.get(tag.energy or "medium", 0.5)
                if energy_min is not None and numeric_val < energy_min:
                    continue
                if energy_max is not None and numeric_val > energy_max:
                    continue

            matching_song_ids.append(tag.song_id)

        results = []
        for song_id in matching_song_ids:
            song = session.get(Song, song_id)
            if song:
                results.append({
                    "id": song.id,
                    "title": song.title,
                    "artist": song.artist,
                    "album": song.album,
                })
        return results
