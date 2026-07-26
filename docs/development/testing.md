# Testing Strategy & Test Suite Architecture

Verse features a comprehensive test suite built with `pytest` and `pytest-mock`.

---

## 1. Test Architecture Overview

Tests are located in the [tests/](file:///home/hisham/projects/music-rec/tests/) directory and configured via `pyproject.toml` ([file:///home/hisham/projects/music-rec/pyproject.toml#L39-L42]):

```text
tests/
├── conftest.py                   # Global pytest fixtures (in-memory DB, sample audio generator)
├── test_scanner.py               # File scanner & extension filter tests
├── test_metadata.py              # Mutagen tag extraction tests
├── test_technical.py             # ffprobe parsing tests
├── test_features.py              # librosa acoustic feature extraction tests
├── test_embeddings.py            # OpenL3 & random projection fallback tests
├── test_search.py                # FAISS index & metadata search tests
├── test_recommendations.py       # Recommendation engine strategy tests
├── test_recommendation_selector.py# Automatic strategy selection & mapping tests
├── test_enrichment.py            # MusicBrainz API rate-limiting & caching tests
├── test_semantic.py              # Semantic tag generation & JSON repair tests
├── test_semantic_rigorous.py     # Deep semantic filtering & synonym tests
├── test_history.py               # Play count, skip, and like history tests
├── test_playlist_system.py       # Playlist candidate scoring & shortfall tests
├── test_playlist_services.py     # Playlist CRUD & ordering tests
├── test_playlist_filtering.py    # Multi-filter candidate validation tests
├── test_assistant.py             # LLMParser, Planner, Executor tests
├── test_api.py                   # FastAPI REST router endpoint tests
├── test_web_api.py               # Web SPA static file mounting & endpoint tests
├── test_playlist_api_routes.py   # Web API playlist endpoints tests
├── test_cli_scan.py              # CLI scanner command tests
├── test_cli_model_config.py      # CLI set-model / get-model tests
├── test_ui.py                    # PySide6 MainWindow & tab unit tests
├── test_phase15_rigorous.py      # Integrated system verification tests
└── test_quality_first_verification.py # High-level system quality tests
```

---

## 2. Global Test Fixtures (`conftest.py`)

Primary test fixtures defined in `tests/conftest.py`:
- `db_session`: Provides an isolated SQLite in-memory database session (`sqlite:///:memory:`) pre-populated with database schemas. Rolls back transactions on test teardown.
- `temp_music_dir`: Creates a temporary directory containing synthetic `.mp3`, `.flac`, and `.wav` audio files using `wave` or synthetic bytes for isolated scanner tests.
- `mock_ollama_response`: Fixture mocking local Ollama HTTP responses for deterministic assistant testing without calling an external service.

---

## 3. Running Test Suites

### Run Full Test Suite
```bash
pytest
```

### Run Specific Test Categories
- **Unit Tests**:
  ```bash
  pytest tests/test_metadata.py tests/test_features.py tests/test_embeddings.py
  ```
- **Recommendation & Search Tests**:
  ```bash
  pytest tests/test_recommendations.py tests/test_search.py tests/test_recommendation_selector.py
  ```
- **AI Assistant Tests**:
  ```bash
  pytest tests/test_assistant.py tests/test_semantic.py
  ```
- **FastAPI REST API Tests**:
  ```bash
  pytest tests/test_api.py tests/test_web_api.py tests/test_playlist_api_routes.py
  ```

---

## 4. Test Invariants & Quality Standards

1. **No Real Network Calls**: Tests mocking external APIs (`MusicBrainz`, `Ollama`) must never hit live endpoints during automated test runs.
2. **Isolation**: Tests must run against isolated temporary files or SQLite in-memory databases to prevent polluting production data (`data/music_rec.db`).
3. **No Muted Failures**: Never catch exceptions silently or lower test assertions to force a passing status.
