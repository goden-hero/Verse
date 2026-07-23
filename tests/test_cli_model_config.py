"""Unit tests for CLI LLM model configuration, status checking, and persistence."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.config.settings import PROJECT_ROOT, set_ollama_model, settings
from app.main import main, run_config, run_get_model, run_set_model


def test_set_ollama_model_in_memory_and_persistence(tmp_path: Path):
    """Test set_ollama_model updates settings in-memory and persists to .env file."""
    original_model = settings.ollama_model
    fake_env = tmp_path / ".env"
    
    try:
        with patch("app.config.settings.PROJECT_ROOT", tmp_path):
            updated = set_ollama_model("llama3:8b", persist=True)
            assert updated == "llama3:8b"
            assert settings.ollama_model == "llama3:8b"
            assert os.environ.get("OLLAMA_MODEL") == "llama3:8b"
            
            # Verify file content in .env
            assert fake_env.exists()
            content = fake_env.read_text(encoding="utf-8")
            assert "OLLAMA_MODEL=llama3:8b" in content

            # Update again to test overwriting existing key in .env
            set_ollama_model("mistral:7b", persist=True)
            assert settings.ollama_model == "mistral:7b"
            content_updated = fake_env.read_text(encoding="utf-8")
            assert "OLLAMA_MODEL=mistral:7b" in content_updated
            assert "OLLAMA_MODEL=llama3:8b" not in content_updated
    finally:
        # Restore original setting
        object.__setattr__(settings, "ollama_model", original_model)


def test_cli_set_model_command(capsys, tmp_path: Path):
    """Test CLI set-model and set-llm subcommands."""
    original_model = settings.ollama_model
    try:
        with patch("app.config.settings.PROJECT_ROOT", tmp_path), \
             patch("app.main.PROJECT_ROOT", tmp_path), \
             patch("requests.get") as mock_get:
            
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"models": [{"name": "gemma:2b"}]}
            mock_get.return_value = mock_resp

            with patch("sys.argv", ["app/main.py", "set-model", "gemma:2b"]):
                main()

            captured = capsys.readouterr().out
            assert "Successfully updated project LLM model to 'gemma:2b'" in captured
            assert settings.ollama_model == "gemma:2b"

            # Test set-llm alias
            with patch("sys.argv", ["app/main.py", "set-llm", "mistral"]):
                main()

            captured_alias = capsys.readouterr().out
            assert "Successfully updated project LLM model to 'mistral'" in captured_alias
            assert settings.ollama_model == "mistral"
    finally:
        object.__setattr__(settings, "ollama_model", original_model)


def test_cli_get_model_command(capsys):
    """Test CLI get-model and get-llm subcommands."""
    original_model = settings.ollama_model
    object.__setattr__(settings, "ollama_model", "test-model")
    try:
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"models": [{"name": "test-model"}]}
            mock_get.return_value = mock_resp

            with patch("sys.argv", ["app/main.py", "get-model"]):
                main()

            captured = capsys.readouterr().out
            assert "Current Project LLM Model: test-model" in captured
            assert "Ollama Server Status:  Connected" in captured
            assert "test-model" in captured
    finally:
        object.__setattr__(settings, "ollama_model", original_model)


def test_cli_config_subcommand(capsys, tmp_path: Path):
    """Test CLI config set-model and config get-model subcommands."""
    original_model = settings.ollama_model
    try:
        with patch("app.config.settings.PROJECT_ROOT", tmp_path), \
             patch("app.main.PROJECT_ROOT", tmp_path), \
             patch("requests.get") as mock_get:
            
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"models": [{"name": "qwen:7b"}]}
            mock_get.return_value = mock_resp

            # Test config set-model
            with patch("sys.argv", ["app/main.py", "config", "set-model", "qwen:7b"]):
                main()

            captured = capsys.readouterr().out
            assert "Successfully updated project LLM model to 'qwen:7b'" in captured
            assert settings.ollama_model == "qwen:7b"

            # Test config get-model
            with patch("sys.argv", ["app/main.py", "config", "get-model"]):
                main()

            captured_get = capsys.readouterr().out
            assert "Current Project LLM Model: qwen:7b" in captured_get
    finally:
        object.__setattr__(settings, "ollama_model", original_model)


def test_cli_global_model_flag_override(capsys):
    """Test top-level --model flag temporarily overrides settings for execution."""
    original_model = settings.ollama_model
    try:
        with patch("app.main.run_enrich_semantic") as mock_runner:
            with patch("sys.argv", ["app/main.py", "--model", "temp-llama", "enrich-semantic"]):
                main()

            mock_runner.assert_called_once()
            assert settings.ollama_model == "temp-llama"
    finally:
        object.__setattr__(settings, "ollama_model", original_model)
