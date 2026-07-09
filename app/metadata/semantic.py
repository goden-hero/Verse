"""Semantic enrichment of songs using a local LLM through Ollama."""

import json
import logging
import requests
from sqlalchemy.orm import Session
from app.config.settings import settings
from app.database.models import AudioFeatures, MusicBrainzMetadata, SemanticTags, Song

logger = logging.getLogger("music_rec.metadata.semantic")


class OllamaClient:
    """Client for communicating with the local Ollama service."""

    def __init__(self, api_url: str | None = None, model: str | None = None) -> None:
        self.api_url = api_url or settings.ollama_url
        self.model = model or settings.ollama_model

    def generate_tags(self, song_info: dict, max_retries: int = 3) -> dict | None:
        """Queries Ollama to generate semantic enrichment tags for a song.

        Args:
            song_info: Dict containing song metadata context (title, artist, BPM, etc.)
            max_retries: Number of attempts in case of network or decoding errors.

        Returns:
            Parsed JSON dict with semantic tags, or None on failure.
        """
        # Construct context-rich prompt
        prompt = (
            "You are a Music Information Retrieval (MIR) semantic tagging system.\n"
            "Analyze the following metadata for this song:\n"
            f"Title: {song_info.get('title', 'Unknown')}\n"
            f"Artist: {song_info.get('artist', 'Unknown')}\n"
            f"Album: {song_info.get('album', 'Unknown')}\n"
            f"Genre: {song_info.get('genre', 'Unknown')}\n"
            f"BPM: {song_info.get('bpm', 'Unknown')}\n"
            f"Key: {song_info.get('key', 'Unknown')}\n"
            f"Year: {song_info.get('year', 'Unknown')}\n"
            f"Duration: {song_info.get('duration', 'Unknown')} seconds\n\n"
            "Identify the moods, activities, themes, instruments/descriptors, energy level, "
            "vocal style, and language. Do not guess blindly, use musical characteristics.\n"
            "Generate tag classifications matching this JSON schema exactly:\n"
            "{\n"
            '  "moods": ["value1", "value2"],\n'
            '  "activities": ["value1", "value2"],\n'
            '  "themes": ["value1", "value2"],\n'
            '  "descriptors": ["value1", "value2"],\n'
            '  "energy": "low|medium|high",\n'
            '  "vocal_style": "value",\n'
            '  "language": "value"\n'
            "}\n"
            "All keys must be present. Energy must be one of low, medium, or high.\n"
            "Response must be valid JSON only. Do not add conversational text or markdown blocks."
        )

        payload = {
            "model": self.model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
        }

        response_text = ""
        for attempt in range(max_retries):
            try:
                logger.info(
                    "Querying Ollama (model: %s, attempt %d/%d) for semantic enrichment...", 
                    self.model, attempt + 1, max_retries
                )
                # Increased timeout to 60.0s to allow model loading
                response = requests.post(self.api_url, json=payload, timeout=60.0)
                if response.status_code != 200:
                    logger.warning(
                        "Ollama API request failed (status %d) on attempt %d: %s",
                        response.status_code,
                        attempt + 1,
                        response.text,
                    )
                    continue

                data = response.json()
                response_text = data.get("response", "").strip()
                if not response_text and "thinking" in data:
                    logger.info("Empty response but 'thinking' field present; falling back to thinking content.")
                    response_text = data.get("thinking", "").strip()

                if not response_text:
                    logger.warning("Empty response received from Ollama on attempt %d.", attempt + 1)
                    continue

                # Parse LLM response
                parsed = json.loads(response_text)
                return self._validate_and_sanitize(parsed)

            except requests.exceptions.RequestException as e:
                logger.warning("Connection error on attempt %d: %s", attempt + 1, e)
            except json.JSONDecodeError as e:
                logger.warning(
                    "Failed to decode JSON response on attempt %d: %s. Content: %s", 
                    attempt + 1, e, response_text
                )
            except Exception as e:
                logger.error("Unexpected error in OllamaClient on attempt %d: %s", attempt + 1, e)
                break

        logger.error("All %d attempts to query Ollama failed.", max_retries)
        return None

    def _validate_and_sanitize(self, data: dict) -> dict:
        """Validates response fields, applying defaults for missing keys or wrong types."""
        sanitized = {}

        # List fields
        for key in ["moods", "activities", "themes", "descriptors"]:
            val = data.get(key)
            if isinstance(val, list):
                sanitized[key] = [str(x).strip().lower() for x in val if x]
            else:
                sanitized[key] = []

        # String fields
        for key in ["energy", "vocal_style", "language"]:
            val = data.get(key)
            if val is not None:
                sanitized[key] = str(val).strip().lower()
            else:
                sanitized[key] = ""

        # Validate energy field value
        if sanitized["energy"] not in ["low", "medium", "high"]:
            sanitized["energy"] = "medium"

        return sanitized


def enrich_song_semantics(
    song_id: int,
    db_session: Session,
    force_refresh: bool = False,
    client: OllamaClient | None = None,
) -> bool:
    """Enriches a song with semantic tags generated via local LLM and caches results.

    Retrieves metadata from DB records, queries Ollama, saves parsed tags, and commits.
    Does not modify original song metadata.

    Args:
        song_id: Database song ID.
        db_session: Database session.
        force_refresh: Re-enrich and overwrite even if semantic tags already exist.
        client: Optional custom OllamaClient instance.

    Returns:
        True if successfully enriched or already cached; False on error.
    """
    song = db_session.get(Song, song_id)
    if not song:
        logger.error("Song ID %d not found in database.", song_id)
        return False

    # Check cache first
    existing = db_session.get(SemanticTags, song_id)
    if existing and not force_refresh:
        logger.debug("Semantic tags already cached for song_id %d.", song_id)
        return True

    # 1. Gather context from databases
    song_info = {
        "title": song.title,
        "artist": song.artist,
        "album": song.album,
        "genre": song.original_genre,
        "duration": song.duration,
    }

    # Integrate MusicBrainz data
    mb_meta = db_session.get(MusicBrainzMetadata, song_id)
    if mb_meta:
        if mb_meta.canonical_genre:
            song_info["genre"] = mb_meta.canonical_genre
        if mb_meta.canonical_artist:
            song_info["artist"] = mb_meta.canonical_artist
        if mb_meta.canonical_album:
            song_info["album"] = mb_meta.canonical_album
        if mb_meta.release_year:
            song_info["year"] = mb_meta.release_year

    # Integrate acoustic features
    features = db_session.get(AudioFeatures, song_id)
    if features:
        song_info["bpm"] = features.bpm
        song_info["key"] = features.key_estimation

    # 2. Query Ollama
    ollama_client = client or OllamaClient()
    tags = ollama_client.generate_tags(song_info)

    if not tags:
        logger.warning("Failed to generate semantic tags for song %d.", song_id)
        return False

    # 3. Save to database without modifying original song model fields
    if existing:
        existing.moods = json.dumps(tags["moods"])
        existing.activities = json.dumps(tags["activities"])
        existing.themes = json.dumps(tags["themes"])
        existing.descriptors = json.dumps(tags["descriptors"])
        existing.energy = tags["energy"]
        existing.vocal_style = tags["vocal_style"]
        existing.language = tags["language"]
    else:
        new_tags = SemanticTags(
            song_id=song_id,
            moods=json.dumps(tags["moods"]),
            activities=json.dumps(tags["activities"]),
            themes=json.dumps(tags["themes"]),
            descriptors=json.dumps(tags["descriptors"]),
            energy=tags["energy"],
            vocal_style=tags["vocal_style"],
            language=tags["language"],
        )
        db_session.add(new_tags)

    db_session.commit()
    logger.info("Successfully saved semantic tags for song_id %d.", song_id)
    return True
