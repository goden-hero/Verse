"""Rigorous unit and integration tests for the Ollama integration, settings, caching, and CLI."""

import os
import json
import argparse
import pytest
from unittest.mock import MagicMock, patch
import requests
from sqlalchemy.orm import Session
from app.config.settings import Settings
from app.database.models import AudioFeatures, MusicBrainzMetadata, SemanticTags, Song
from app.metadata.semantic import OllamaClient, enrich_song_semantics
from app.main import run_enrich_semantic, main


def get_real_ollama_info():
    """Checks if local Ollama server is running and returns (url, model) if available, else (None, None)."""
    url = "http://localhost:11434"
    try:
        response = requests.get(f"{url}/api/tags", timeout=2.0)
        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])
            if models:
                # Use the first available model name
                return f"{url}/api/generate", models[0]["name"]
    except Exception:
        pass
    return None, None


# =====================================================================
# 1. Ollama Integration (OllamaClient) Tests
# =====================================================================

def test_ollama_client_payload_json_format():
    """Verify that the request payload to Ollama specifies "format": "json"."""
    client = OllamaClient(api_url="http://localhost:11434/api/generate", model="llama3")
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": json.dumps({
            "moods": ["happy"],
            "activities": ["running"],
            "themes": ["victory"],
            "descriptors": ["energetic"],
            "energy": "high",
            "vocal_style": "clean",
            "language": "english"
        })
    }
    
    with patch("requests.post", return_value=mock_response) as mock_post:
        client.generate_tags({"title": "Mock Title"})
        
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert "json" in call_kwargs
        assert call_kwargs["json"]["format"] == "json"
        assert call_kwargs["json"]["model"] == "llama3"


def test_ollama_client_prompt_context_injection():
    """Verify that all song metadata context is injected into the LLM prompt."""
    client = OllamaClient()
    
    song_info = {
        "title": "Starlight",
        "artist": "Muse",
        "album": "Black Holes and Revelations",
        "genre": "Alternative Rock",
        "bpm": 121.5,
        "key": "B Major",
        "year": 2006,
        "duration": 240.2
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "{}"}
    
    with patch("requests.post", return_value=mock_response) as mock_post:
        client.generate_tags(song_info)
        
        call_kwargs = mock_post.call_args[1]
        prompt = call_kwargs["json"]["prompt"]
        
        # Verify all context fields are injected into the prompt
        assert "Title: Starlight" in prompt
        assert "Artist: Muse" in prompt
        assert "Album: Black Holes and Revelations" in prompt
        assert "Genre: Alternative Rock" in prompt
        assert "BPM: 121.5" in prompt
        assert "Key: B Major" in prompt
        assert "Year: 2006" in prompt
        assert "Duration: 240.2" in prompt


def test_ollama_client_output_sanitization():
    """Verify robust output sanitization for missing keys, bad types, and invalid energy values."""
    client = OllamaClient()
    
    # 1. Missing keys and invalid energy
    bad_data_1 = {
        "moods": ["Cheerful", ""],  # empty tag should be filtered, uppercase should be lowered
        # 'activities' is missing
        "themes": "not-a-list",     # string instead of list
        "descriptors": [123, None], # invalid list items
        "energy": "super-high",     # invalid energy value
        "vocal_style": None,        # None type
        # 'language' is missing
    }
    
    sanitized = client._validate_and_sanitize(bad_data_1)
    
    assert sanitized["moods"] == ["cheerful"]
    assert sanitized["activities"] == []
    assert sanitized["themes"] == []
    assert sanitized["descriptors"] == ["123"] # coerced to string
    assert sanitized["energy"] == "medium"     # coerced to default
    assert sanitized["vocal_style"] == ""      # coerced to empty string
    assert sanitized["language"] == ""         # coerced to empty string

    # 2. Correct lowercase conversion and valid energy preservation
    bad_data_2 = {
        "moods": ["Sad", "MELANCHOLIC"],
        "activities": ["SLEEPING"],
        "themes": ["Loss"],
        "descriptors": ["Acoustic", "Piano"],
        "energy": "low",
        "vocal_style": "Spoken Word",
        "language": "French"
    }
    
    sanitized_2 = client._validate_and_sanitize(bad_data_2)
    
    assert sanitized_2["moods"] == ["sad", "melancholic"]
    assert sanitized_2["activities"] == ["sleeping"]
    assert sanitized_2["themes"] == ["loss"]
    assert sanitized_2["descriptors"] == ["acoustic", "piano"]
    assert sanitized_2["energy"] == "low"
    assert sanitized_2["vocal_style"] == "spoken word"
    assert sanitized_2["language"] == "french"


# =====================================================================
# 2. Settings Layer (app/config/settings.py) Tests
# =====================================================================

def test_settings_layer_env_configuration():
    """Verify that Ollama URL and model are loaded from environment variables."""
    # Temporarily set environment variables
    custom_url = "http://my-ollama-server:12345/api/generate"
    custom_model = "mistral-music"
    
    with patch.dict(os.environ, {"OLLAMA_URL": custom_url, "OLLAMA_MODEL": custom_model}):
        # Re-instantiate Settings to verify it reads from os.getenv
        test_settings = Settings()
        assert test_settings.ollama_url == custom_url
        assert test_settings.ollama_model == custom_model


# =====================================================================
# 3. Database Caching & Isolation Tests
# =====================================================================

@pytest.fixture
def mock_db_song(db_session: Session) -> Song:
    """Fixture to insert a test song and features to DB."""
    song = Song(
        path="/music/test.mp3",
        hash="hash9876",
        title="Original Title",
        artist="Original Artist",
        album="Original Album",
        original_genre="Pop",
        duration=180.0
    )
    db_session.add(song)
    db_session.commit()
    
    features = AudioFeatures(
        song_id=song.id,
        bpm=120.0,
        key_estimation="C Major"
    )
    db_session.add(features)
    db_session.commit()
    return song


def test_enrich_song_semantics_database_isolation(db_session: Session, mock_db_song: Song):
    """Verify LLM results are stored in semantic_tags table, leaving Song table unchanged."""
    mock_tags = {
        "moods": ["energetic"],
        "activities": ["workout"],
        "themes": ["motivation"],
        "descriptors": ["synth"],
        "energy": "high",
        "vocal_style": "clean",
        "language": "english"
    }
    
    mock_client = MagicMock()
    mock_client.generate_tags.return_value = mock_tags
    
    # Run semantic enrichment
    success = enrich_song_semantics(
        song_id=mock_db_song.id,
        db_session=db_session,
        client=mock_client
    )
    assert success is True
    
    # 1. Verify semantic_tags has correct record
    tag_record = db_session.get(SemanticTags, mock_db_song.id)
    assert tag_record is not None
    assert json.loads(tag_record.moods) == ["energetic"]
    assert tag_record.energy == "high"
    
    # 2. Verify Song metadata table has NOT changed
    song_record = db_session.get(Song, mock_db_song.id)
    assert song_record.title == "Original Title"
    assert song_record.artist == "Original Artist"
    assert song_record.album == "Original Album"
    assert song_record.original_genre == "Pop"


def test_enrich_song_semantics_caching_and_force_refresh(db_session: Session, mock_db_song: Song):
    """Verify that database caching avoids regeneration and force_refresh overrides it."""
    mock_tags_1 = {
        "moods": ["happy"],
        "activities": ["studying"],
        "themes": ["chill"],
        "descriptors": ["guitar"],
        "energy": "low",
        "vocal_style": "clean",
        "language": "english"
    }
    
    mock_tags_2 = {
        "moods": ["dark"],
        "activities": ["coding"],
        "themes": ["focus"],
        "descriptors": ["electronic"],
        "energy": "high",
        "vocal_style": "instrumental",
        "language": "none"
    }
    
    mock_client = MagicMock()
    mock_client.generate_tags.return_value = mock_tags_1
    
    # 1. First invocation: calls client, writes cache
    res1 = enrich_song_semantics(mock_db_song.id, db_session, client=mock_client)
    assert res1 is True
    assert mock_client.generate_tags.call_count == 1
    
    # 2. Second invocation: cached, does NOT call client
    mock_client.reset_mock()
    res2 = enrich_song_semantics(mock_db_song.id, db_session, client=mock_client)
    assert res2 is True
    assert mock_client.generate_tags.call_count == 0
    
    # 3. Third invocation with force_refresh: calls client again, updates DB
    mock_client.reset_mock()
    mock_client.generate_tags.return_value = mock_tags_2
    res3 = enrich_song_semantics(mock_db_song.id, db_session, force_refresh=True, client=mock_client)
    assert res3 is True
    assert mock_client.generate_tags.call_count == 1
    
    # Verify DB contains mock_tags_2
    tag_record = db_session.get(SemanticTags, mock_db_song.id)
    assert json.loads(tag_record.moods) == ["dark"]
    assert tag_record.energy == "high"


# =====================================================================
# 4. CLI Commands (app/main.py) Tests
# =====================================================================

def test_cli_parser_registration():
    """Verify CLI parser registers the 'enrich-semantic' command and arguments."""
    with patch("sys.argv", ["app/main.py", "enrich-semantic", "--force", "--limit", "5"]):
        with patch("app.main.run_enrich_semantic") as mock_runner:
            main()
            mock_runner.assert_called_once()
            
            # Verify parsed arguments passed to runner
            args = mock_runner.call_args[0][0]
            assert args.command == "enrich-semantic"
            assert args.force is True
            assert args.limit == 5


def test_run_enrich_semantic_cli_handling(db_session: Session, mock_db_song: Song):
    """Verify the runner function handles song querying, limits, and force refresh flag."""
    # Add a second song to test limit
    song2 = Song(
        path="/music/test2.mp3",
        hash="hash1111",
        title="Second Song",
        artist="Second Artist",
        duration=120.0
    )
    db_session.add(song2)
    db_session.commit()
    
    # Create mock args
    args = argparse.Namespace(command="enrich-semantic", force=True, limit=1)
    
    # Mock database session factory used inside the CLI handler
    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__.return_value = db_session
    mock_session_ctx.return_value = mock_session_ctx
    mock_get_session = MagicMock(return_value=mock_session_ctx)
    
    with patch("app.main.get_session", mock_get_session):
        with patch("app.main.enrich_song_semantics", return_value=True) as mock_enrich:
            run_enrich_semantic(args)
            
            # Since limit is 1, enrich_song_semantics should only be called once
            assert mock_enrich.call_count == 1
            mock_enrich.assert_called_with(
                song_id=mock_db_song.id,
                db_session=db_session,
                force_refresh=True
            )


# =====================================================================
# 5. Real Ollama Server Integration Tests
# =====================================================================

def test_ollama_client_real_success():
    """Verify OllamaClient successfully queries a real running Ollama server if available."""
    api_url, model = get_real_ollama_info()
    if not api_url:
        pytest.skip("Active Ollama server not found on localhost:11434")
        
    client = OllamaClient(api_url=api_url, model=model)
    song_info = {
        "title": "Enter Sandman",
        "artist": "Metallica",
        "album": "Metallica",
        "genre": "Heavy Metal",
        "bpm": 123.0,
        "key": "E Minor",
        "year": 1991,
        "duration": 331.0
    }
    
    tags = client.generate_tags(song_info)
    assert tags is not None
    assert isinstance(tags, dict)
    
    # Check that all keys are present in sanitized response
    for key in ["moods", "activities", "themes", "descriptors", "energy", "vocal_style", "language"]:
        assert key in tags
        
    assert isinstance(tags["moods"], list)
    assert isinstance(tags["activities"], list)
    assert isinstance(tags["themes"], list)
    assert isinstance(tags["descriptors"], list)
    assert isinstance(tags["energy"], str)
    assert tags["energy"] in ["low", "medium", "high"]


def test_enrich_song_semantics_real_flow(db_session: Session, mock_db_song: Song):
    """Verify database caching and refresh behavior using the real active Ollama server."""
    api_url, model = get_real_ollama_info()
    if not api_url:
        pytest.skip("Active Ollama server not found on localhost:11434")
        
    client = OllamaClient(api_url=api_url, model=model)
    
    # 1. Run enrichment
    success = enrich_song_semantics(
        song_id=mock_db_song.id,
        db_session=db_session,
        client=client
    )
    assert success is True
    
    # Verify semantic_tags has correct record
    tag_record = db_session.get(SemanticTags, mock_db_song.id)
    assert tag_record is not None
    assert isinstance(json.loads(tag_record.moods), list)
    assert tag_record.energy in ["low", "medium", "high"]
    
    # 2. Second run without force_refresh (should read from cache without hitting requests.post)
    with patch("requests.post") as mock_post:
        success_cache = enrich_song_semantics(
            song_id=mock_db_song.id,
            db_session=db_session,
            client=client
        )
        assert success_cache is True
        mock_post.assert_not_called()


def test_run_enrich_semantic_cli_handling_real(db_session: Session, mock_db_song: Song):
    """Verify CLI runner enrichment with a real active Ollama server."""
    api_url, model = get_real_ollama_info()
    if not api_url:
        pytest.skip("Active Ollama server not found on localhost:11434")
        
    args = argparse.Namespace(command="enrich-semantic", force=True, limit=1)
    
    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__.return_value = db_session
    mock_session_ctx.return_value = mock_session_ctx
    mock_get_session = MagicMock(return_value=mock_session_ctx)
    
    custom_settings = Settings(ollama_url=api_url, ollama_model=model)
    
    with patch("app.main.get_session", mock_get_session):
        with patch("app.metadata.semantic.settings", custom_settings), \
             patch("app.main.settings", custom_settings):
            run_enrich_semantic(args)
            
            # Check that DB was populated with real tags
            tag_record = db_session.get(SemanticTags, mock_db_song.id)
            assert tag_record is not None
            assert isinstance(json.loads(tag_record.moods), list)


