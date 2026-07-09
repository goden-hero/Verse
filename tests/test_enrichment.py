"""Unit tests for the MusicBrainz metadata enrichment module."""

import time
import pytest
from requests import RequestException
from sqlalchemy.orm import Session
from app.database.models import MusicBrainzMetadata, Song
from app.metadata.enrichment import enrich_song_metadata, query_musicbrainz


def test_query_musicbrainz_success(mocker) -> None:
    """Verifies that query_musicbrainz constructs requests correctly and returns JSON."""
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"recordings": [{"id": "mbid-123"}]}
    mock_get = mocker.patch("requests.get", return_value=mock_response)

    data = query_musicbrainz(title="Kiss Me", artist="Sixpence None The Richer")

    assert data == {"recordings": [{"id": "mbid-123"}]}
    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert "headers" in kwargs
    assert "User-Agent" in kwargs["headers"]
    assert "params" in kwargs
    assert "query" in kwargs["params"]
    assert 'artist:"Sixpence None The Richer"' in kwargs["params"]["query"]
    assert 'recording:"Kiss Me"' in kwargs["params"]["query"]


def test_query_musicbrainz_network_error(mocker) -> None:
    """Verifies that network exceptions are caught and return None."""
    mocker.patch("requests.get", side_effect=RequestException("connection failed"))
    data = query_musicbrainz(title="Error", artist="Artist")
    assert data is None


def test_query_musicbrainz_rate_limit(mocker) -> None:
    """Verifies that sequential calls to query_musicbrainz enforce rate-limiting delay."""
    import app.metadata.enrichment
    app.metadata.enrichment._LAST_CALL_TIME = 0.0

    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}
    mocker.patch("requests.get", return_value=mock_response)

    # Mock time.sleep to trace calls
    mock_sleep = mocker.patch("time.sleep")

    # First call sets initial time
    query_musicbrainz("Song1", "Artist1")
    # Second call should trigger rate limiting sleep because it happens immediately
    query_musicbrainz("Song2", "Artist2")

    mock_sleep.assert_called_once()
    sleep_time = mock_sleep.call_args[0][0]
    assert 0.0 < sleep_time <= 1.0


def test_enrich_song_metadata_database_caching(db_session: Session, mocker) -> None:
    """Verifies caching behavior for successful matches and negative matches."""
    # Set up dummy song
    song = Song(path="/path/test.mp3", hash="hash1", title="Test Song", artist="Test Artist")
    db_session.add(song)
    db_session.commit()

    # Mock response with valid recording data
    mock_api_data = {
        "recordings": [
            {
                "id": "musicbrainz-recording-uuid",
                "artist-credit": [{"artist": {"name": "Canonical Artist"}}],
                "releases": [{"title": "Canonical Album", "date": "2026-05-12"}],
                "tags": [{"name": "Synthpop", "count": 10}, {"name": "80s", "count": 5}],
            }
        ]
    }
    mock_query = mocker.patch("app.metadata.enrichment.query_musicbrainz", return_value=mock_api_data)

    # First run (should query API and write cache)
    status = enrich_song_metadata(song.id, song.title, song.artist, db_session)
    assert status is True
    mock_query.assert_called_once_with("Test Song", "Test Artist")

    # Check db has cached data
    cached = db_session.get(MusicBrainzMetadata, song.id)
    assert cached is not None
    assert cached.canonical_artist == "Canonical Artist"
    assert cached.canonical_album == "Canonical Album"
    assert cached.release_year == 2026
    assert cached.canonical_genre == "Synthpop"
    assert cached.musicbrainz_id == "musicbrainz-recording-uuid"

    # Reset mock and run again (should hit cache directly without querying API)
    mock_query.reset_mock()
    status_second = enrich_song_metadata(song.id, song.title, song.artist, db_session)
    assert status_second is True
    mock_query.assert_not_called()


def test_enrich_song_metadata_negative_caching(db_session: Session, mocker) -> None:
    """Verifies that failed matches cache negative search results."""
    song = Song(path="/path/no_match.mp3", hash="hash2", title="Unknown Song", artist="Unknown Artist")
    db_session.add(song)
    db_session.commit()

    # Mock response with empty recording list
    mock_api_data = {"recordings": []}
    mock_query = mocker.patch("app.metadata.enrichment.query_musicbrainz", return_value=mock_api_data)

    # First run (should query API and cache negative hit)
    status = enrich_song_metadata(song.id, song.title, song.artist, db_session)
    assert status is False
    mock_query.assert_called_once_with("Unknown Song", "Unknown Artist")

    # Check db has negative hit cache
    cached = db_session.get(MusicBrainzMetadata, song.id)
    assert cached is not None
    assert cached.musicbrainz_id == "NOT_FOUND"
    assert cached.canonical_artist is None

    # Reset mock and run again (should hit cache directly without calling API)
    mock_query.reset_mock()
    status_second = enrich_song_metadata(song.id, song.title, song.artist, db_session)
    assert status_second is False
    mock_query.assert_not_called()
