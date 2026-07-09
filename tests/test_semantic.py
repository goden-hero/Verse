"""Unit tests for Phase 11 Semantic Enrichment."""

import json
import pytest
from unittest.mock import MagicMock, patch
import requests
from sqlalchemy.orm import Session
from app.database.models import AudioFeatures, MusicBrainzMetadata, SemanticTags, Song
from app.metadata.semantic import OllamaClient, enrich_song_semantics


@pytest.fixture
def mock_song(db_session: Session) -> Song:
    """Fixture to create a test song in the DB."""
    song = Song(
        path="/path/test_song.mp3",
        hash="testhash123",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        original_genre="Rock",
        duration=180.0,
    )
    db_session.add(song)
    db_session.commit()

    # Add features
    feat = AudioFeatures(
        song_id=song.id,
        bpm=120.0,
        key_estimation="C Major",
    )
    db_session.add(feat)

    # Add MusicBrainz metadata
    mb = MusicBrainzMetadata(
        song_id=song.id,
        canonical_genre="Alternative Rock",
        canonical_artist="Canonical Artist",
        canonical_album="Canonical Album",
        release_year=2020,
        musicbrainz_id="mbid-123",
    )
    db_session.add(mb)

    db_session.commit()
    return song


def test_ollama_client_success() -> None:
    """Verifies that OllamaClient successfully requests and validates JSON responses."""
    client = OllamaClient(
        api_url="http://mock-ollama:11434/api/generate", model="mock-model"
    )

    mock_llm_response = {
        "moods": ["happy", "calm"],
        "activities": ["studying"],
        "themes": ["nature"],
        "descriptors": ["acoustic"],
        "energy": "low",
        "vocal_style": "melodic",
        "language": "english",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "model": "mock-model",
        "response": json.dumps(mock_llm_response),
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        tags = client.generate_tags({"title": "Test Title"})

        assert tags == mock_llm_response
        mock_post.assert_called_once()
        # Verify JSON format payload constraint was sent
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["format"] == "json"


def test_ollama_client_missing_keys_and_sanitization() -> None:
    """Verifies that OllamaClient fills default fields when keys are missing or malformed."""
    client = OllamaClient()

    # LLM response with missing keys, uppercase energy, and non-list elements
    mock_llm_response = {
        "moods": ["Happy", ""],
        "energy": "HIGH",
        "vocal_style": "clean",
        # 'activities', 'themes', 'descriptors', 'language' are missing
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": json.dumps(mock_llm_response),
    }

    with patch("requests.post", return_value=mock_response):
        tags = client.generate_tags({})

        assert tags["moods"] == ["happy"]
        assert tags["activities"] == []
        assert tags["themes"] == []
        assert tags["descriptors"] == []
        assert tags["energy"] == "high"
        assert tags["vocal_style"] == "clean"
        assert tags["language"] == ""


def test_ollama_client_network_error() -> None:
    """Verifies that OllamaClient handles requests exceptions and returns None."""
    client = OllamaClient()

    with patch("requests.post", side_effect=requests.exceptions.ConnectionError("Mocked Connection Error")):
        tags = client.generate_tags({})
        assert tags is None


def test_enrich_song_semantics_caching_and_refresh(db_session: Session, mock_song: Song) -> None:
    """Verifies SQLite database caching, retrieval, and force refresh of semantic tags."""
    mock_tags_1 = {
        "moods": ["happy"],
        "activities": ["cooking"],
        "themes": ["nostalgia"],
        "descriptors": ["guitar"],
        "energy": "medium",
        "vocal_style": "clean",
        "language": "english",
    }

    mock_tags_2 = {
        "moods": ["sad"],
        "activities": ["sleeping"],
        "themes": ["rain"],
        "descriptors": ["piano"],
        "energy": "low",
        "vocal_style": "whisper",
        "language": "english",
    }

    mock_client = MagicMock()
    mock_client.generate_tags.return_value = mock_tags_1

    # 1. First run: Generates tags and caches them
    success = enrich_song_semantics(
        song_id=mock_song.id,
        db_session=db_session,
        client=mock_client,
    )
    assert success is True
    mock_client.generate_tags.assert_called_once()

    # Verify database record matches mock_tags_1
    tags_in_db = db_session.get(SemanticTags, mock_song.id)
    assert tags_in_db is not None
    assert json.loads(tags_in_db.moods) == ["happy"]
    assert tags_in_db.energy == "medium"

    # 2. Second run without force_refresh: returns True without calling client again (caching)
    mock_client.reset_mock()
    success = enrich_song_semantics(
        song_id=mock_song.id,
        db_session=db_session,
        client=mock_client,
    )
    assert success is True
    mock_client.generate_tags.assert_not_called()

    # 3. Third run with force_refresh: queries client and updates DB
    mock_client.generate_tags.return_value = mock_tags_2
    success = enrich_song_semantics(
        song_id=mock_song.id,
        db_session=db_session,
        force_refresh=True,
        client=mock_client,
    )
    assert success is True
    mock_client.generate_tags.assert_called_once()

    # Verify updated database record matches mock_tags_2
    db_session.expire(tags_in_db)
    tags_in_db = db_session.get(SemanticTags, mock_song.id)
    assert json.loads(tags_in_db.moods) == ["sad"]
    assert tags_in_db.energy == "low"
