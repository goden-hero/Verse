"""Unit tests for Phase 14 AI Assistant parser, planner, executor, and UI worker integration."""

import json
import requests
from unittest.mock import MagicMock, patch
import pytest
from app.assistant.parser import LLMParser
from app.assistant.planner import Planner
from app.assistant.executor import Executor
from app.assistant.cache import LLMCacheManager
from app.assistant.history import AssistantHistoryManager
from app.assistant.schemas import ActionPlan, PlaySong, Pause
from app.database.models import LLMCache, AssistantHistory, Song
from app.ui.workers import AssistantWorker
from app.services.playback import PlaybackService


def test_planner_validates_correct_schema():
    """Verify Planner parses valid dictionaries into ActionPlan objects."""
    raw = {
        "plan": [
            {"action": "play_song", "song_title": "Hotel California"},
            {"action": "pause"},
        ]
    }
    plan = Planner.create_plan(raw)
    assert isinstance(plan, ActionPlan)
    assert len(plan.plan) == 2
    assert isinstance(plan.plan[0], PlaySong)
    assert plan.plan[0].song_title == "Hotel California"
    assert isinstance(plan.plan[1], Pause)


def test_llm_cache_manager_hits(db_session):
    """Verify LLMCacheManager caches and retrieves prompt responses."""
    prompt = "Play some jazz"
    response = '{"plan": [{"action": "pause"}]}'

    # Miss first
    val = LLMCacheManager.get_cached_response(prompt, db_session)
    assert val is None

    # Cache
    LLMCacheManager.cache_response(prompt, response, db_session)

    # Hit second
    val = LLMCacheManager.get_cached_response(prompt, db_session)
    assert val == response


@patch("requests.post")
def test_llm_parser_success(mock_post, db_session):
    """Verify LLMParser queries Ollama and validates standard plan JSON responses."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "response": '{"plan": [{"action": "play_song", "song_title": "Hey Jude"}]}'
    }
    mock_post.return_value = mock_resp

    parser = LLMParser(api_url="http://mock-ollama/api/generate", model="mock-model", disable_health_check=True)
    res = parser.parse_intent("play Hey Jude", db_session)

    assert res is not None
    assert "plan" in res
    assert res["plan"][0]["action"] == "play_song"
    assert res["plan"][0]["song_title"] == "Hey Jude"

    # Verify cached
    cached = LLMCacheManager.get_cached_response("play Hey Jude", db_session)
    assert cached is not None


@patch("requests.post")
def test_llm_parser_retry_validation_error(mock_post, db_session):
    """Verify LLMParser requests a retry when the first response fails validation."""
    # First response fails (missing plan field)
    resp_invalid = MagicMock()
    resp_invalid.status_code = 200
    resp_invalid.json.return_value = {"response": '{"wrong_field": []}'}

    # Second response is valid
    resp_valid = MagicMock()
    resp_valid.status_code = 200
    resp_valid.json.return_value = {
        "response": '{"plan": [{"action": "pause"}]}'
    }

    mock_post.side_effect = [resp_invalid, resp_valid]

    parser = LLMParser(api_url="http://mock-ollama/api/generate", model="mock-model", disable_health_check=True)
    res = parser.parse_intent("stop music", db_session, max_retries=2)

    assert res is not None
    assert res["plan"][0]["action"] == "pause"
    assert mock_post.call_count == 2


@patch("requests.get")
@patch("requests.post")
def test_llm_parser_verify_health_success(mock_post, mock_get):
    """Verify that verify_health successfully passes when Ollama is running and has model."""
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_tags_data = {"models": [{"name": "mock-model"}]}
    mock_ps_data = {"models": []}
    
    mock_get_resp.json.side_effect = [
        mock_tags_data,
        mock_ps_data
    ]
    mock_get.return_value = mock_get_resp
    
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post.return_value = mock_post_resp
    
    LLMParser._health_checked = False
    LLMParser._is_healthy = False
    
    parser = LLMParser(api_url="http://mock-ollama/api/generate", model="mock-model", disable_health_check=False)
    parser.verify_health()
    
    assert LLMParser._health_checked is True
    assert LLMParser._is_healthy is True
    assert mock_get.call_count == 3
    mock_post.assert_called_once()


@patch("requests.get")
def test_llm_parser_verify_health_unreachable(mock_get):
    """Verify verify_health raises ConnectionError when Ollama server is unreachable."""
    mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
    
    LLMParser._health_checked = False
    LLMParser._is_healthy = False
    
    parser = LLMParser(api_url="http://mock-ollama/api/generate", model="mock-model", disable_health_check=False)
    with pytest.raises(ConnectionError) as exc_info:
        parser.verify_health()
    
    assert "Ollama server is unreachable" in str(exc_info.value)


@patch("requests.get")
def test_llm_parser_verify_health_missing_model(mock_get):
    """Verify verify_health raises ValueError when model is not installed."""
    mock_base_resp = MagicMock()
    mock_base_resp.status_code = 200
    
    mock_tags_resp = MagicMock()
    mock_tags_resp.status_code = 200
    mock_tags_resp.json.return_value = {"models": [{"name": "other-model"}]}
    
    mock_get.side_effect = [mock_base_resp, mock_tags_resp]
    
    LLMParser._health_checked = False
    LLMParser._is_healthy = False
    
    parser = LLMParser(api_url="http://mock-ollama/api/generate", model="mock-model", disable_health_check=False)
    with pytest.raises(ValueError) as exc_info:
        parser.verify_health()
        
    assert "not installed in Ollama" in str(exc_info.value)


def test_pydantic_float_coercion():
    """Verify Pydantic schemas successfully coerce floats/strings to integers for limit and target_length."""
    raw_playlist = {
        "action": "generate_playlist",
        "playlist_name": "Chill Mix",
        "target_length": 15.6
    }
    plan = ActionPlan.model_validate({"plan": [raw_playlist]})
    assert plan.plan[0].target_length == 16
    
    raw_playlist_str = {
        "action": "generate_playlist",
        "playlist_name": "Chill Mix",
        "target_length": "12.2"
    }
    plan_str = ActionPlan.model_validate({"plan": [raw_playlist_str]})
    assert plan_str.plan[0].target_length == 12

    raw_recommend = {
        "action": "recommend_song",
        "song_title": "Hotel California",
        "limit": 5.4
    }
    plan_rec = ActionPlan.model_validate({"plan": [raw_recommend]})
    assert plan_rec.plan[0].limit == 5


def test_history_manager_logs_and_retrieves(db_session):
    """Verify AssistantHistoryManager persists conversation history correctly."""
    prompt = "Create a chill mix"
    plan = [{"action": "generate_playlist", "playlist_name": "Chill Mix"}]
    result = {"success": True, "steps": []}

    AssistantHistoryManager.log_conversation(prompt, plan, result, db_session)

    history = AssistantHistoryManager.get_recent_history(5, db_session)
    assert len(history) == 1
    assert history[0]["prompt"] == prompt
    assert history[0]["plan"] == plan
    assert history[0]["result"] == result


def test_executor_dispatches_playback_actions(db_session):
    """Verify Executor handles simple actions without crashing."""
    raw = {"plan": [{"action": "pause"}, {"action": "resume"}]}
    plan = ActionPlan.model_validate(raw)

    mock_handler = MagicMock()
    PlaybackService.register_handler(mock_handler)

    res = Executor.execute_plan(plan, db_session)
    assert res["success"] is True
    assert len(res["steps"]) == 2
    assert res["steps"][0]["action"] == "pause"
    assert res["steps"][0]["status"] == "success"


def test_executor_song_not_found(db_session):
    """Verify Executor fails gracefully when a requested song is not in the library."""
    raw = {"plan": [{"action": "play_song", "song_title": "Non-existent Song"}]}
    plan = ActionPlan.model_validate(raw)

    res = Executor.execute_plan(plan, db_session)
    assert res["success"] is False
    assert res["steps"][0]["status"] == "error"
    assert "Song not found" in res["steps"][0]["error"]


def test_executor_generate_playlist_success(db_session):
    """Verify Executor successfully generates and persists playlists."""
    # Seed a song in DB first
    s = Song(
        title="Beat It",
        artist="Michael Jackson",
        album="Thriller",
        duration=240.0,
        path="/path/beat_it.mp3",
        hash="xyz123"
    )
    db_session.add(s)
    db_session.commit()

    raw = {
        "plan": [
            {
                "action": "generate_playlist",
                "playlist_name": "Pop Mix",
                "strategy": "hybrid",
                "filters": {},
                "target_length": 5
            }
        ]
    }
    plan = ActionPlan.model_validate(raw)
    res = Executor.execute_plan(plan, db_session)

    assert res["success"] is True
    assert res["steps"][0]["status"] == "success"
    playlist_id = res["steps"][0]["output"]["id"]
    assert playlist_id is not None
