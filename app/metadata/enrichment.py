"""Enriches song metadata using the MusicBrainz Web Service API with caching and rate-limiting."""

import logging
import time
from pathlib import Path
import requests
from sqlalchemy.orm import Session
from app.database.models import MusicBrainzMetadata

logger = logging.getLogger("music_rec.metadata.enrichment")

# Global tracker for the last API call timestamp to enforce rate-limiting
_LAST_CALL_TIME = 0.0


def _rate_limit() -> None:
    """Enforces a strict 1-second delay between MusicBrainz API calls."""
    global _LAST_CALL_TIME
    now = time.time()
    elapsed = now - _LAST_CALL_TIME
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _LAST_CALL_TIME = time.time()


def query_musicbrainz(title: str, artist: str) -> dict | None:
    """Queries the MusicBrainz recording API for the given title and artist.

    Respects the rate limit (1 request/second) and returns the parsed JSON dict
    or None on failure.
    """
    _rate_limit()
    url = "https://musicbrainz.org/ws/2/recording"
    headers = {
        "User-Agent": "MusicRecommendationSystem/0.1.0 ( mailto:hisham@example.com )"
    }

    # Clean double quotes to avoid Lucene query syntax errors
    clean_title = title.replace('"', "")
    clean_artist = artist.replace('"', "")

    params = {
        "query": f'artist:"{clean_artist}" AND recording:"{clean_title}"',
        "fmt": "json",
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10.0)
        if response.status_code == 200:
            return response.json()
        logger.warning(
            "MusicBrainz API request failed with status code: %d",
            response.status_code,
        )
    except requests.RequestException as e:
        logger.error("Network error while querying MusicBrainz: %s", e)
    return None


def enrich_song_metadata(
    song_id: int, title: str, artist: str, db_session: Session
) -> bool:
    """Queries MusicBrainz to enrich the song metadata and caches the result.

    Checks if metadata has already been cached in `musicbrainz_metadata`. If not,
    queries the MusicBrainz API, processes the best match, saves it to the DB,
    and commits. Returns True if metadata is successfully retrieved or already cached.
    """
    if not title or not artist:
        logger.debug("Skipping enrichment for song_id %d: title or artist is empty", song_id)
        return False

    # Check database cache first
    existing = db_session.get(MusicBrainzMetadata, song_id)
    if existing is not None:
        logger.debug("Song %d is already enriched/cached.", song_id)
        return existing.musicbrainz_id != "NOT_FOUND"

    logger.info("Enriching metadata from MusicBrainz for song '%s' by '%s'...", title, artist)
    data = query_musicbrainz(title, artist)

    if not data:
        # Network/API error, do not write a negative cache record so we can retry later
        return False

    recordings = data.get("recordings", [])
    if not recordings:
        logger.info("No MusicBrainz match found for '%s' by '%s'. Caching negative hit.", title, artist)
        # Cache negative hit to prevent querying API again next time
        neg_cache = MusicBrainzMetadata(
            song_id=song_id,
            canonical_artist=None,
            canonical_album=None,
            release_year=None,
            canonical_genre=None,
            musicbrainz_id="NOT_FOUND",
        )
        db_session.add(neg_cache)
        db_session.commit()
        return False

    # Select the best match (the first recording in the result list)
    best_match = recordings[0]
    mbid = best_match.get("id")

    # Canonical artist name
    artist_credit = best_match.get("artist-credit", [])
    canonical_artist = None
    if artist_credit:
        canonical_artist = artist_credit[0].get("artist", {}).get("name")

    # Canonical album name and release year from associated releases
    releases = best_match.get("releases", [])
    canonical_album = None
    release_year = None
    if releases:
        # Find the first release that has a title and a date
        best_release = releases[0]
        canonical_album = best_release.get("title")
        date_str = best_release.get("date")
        if date_str:
            try:
                # Dates can be "YYYY-MM-DD", "YYYY-MM", or just "YYYY"
                release_year = int(date_str.split("-")[0])
            except ValueError:
                pass

    # Extract genre from tags if present
    tags = best_match.get("tags", [])
    canonical_genre = None
    if tags:
        # Sort by count (popularity) descending if 'count' exists
        sorted_tags = sorted(tags, key=lambda t: t.get("count", 0), reverse=True)
        canonical_genre = sorted_tags[0].get("name")

    # Save to database
    meta = MusicBrainzMetadata(
        song_id=song_id,
        canonical_artist=canonical_artist,
        canonical_album=canonical_album,
        release_year=release_year,
        canonical_genre=canonical_genre,
        musicbrainz_id=mbid,
    )
    db_session.add(meta)
    db_session.commit()

    logger.info("Successfully enriched song %d with MusicBrainz ID: %s", song_id, mbid)
    return True
