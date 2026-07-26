# Contributing Standards & Invariants

This document outlines coding conventions, logging rules, and architectural invariants that all developers working on Verse must preserve.

---

## 1. Architectural Invariants

1. **Service Layer Isolation**: All business logic, DB queries, recommendation math, and AI parsing MUST reside in `app/services/` or dedicated core packages (`app/recommendations/`, `app/assistant/`). Route handlers in `app/api/` and UI components in `app/ui/` must remain thin adapters.
2. **Thread Safety**: Never access shared SQLAlchemy sessions or UI widgets across thread boundaries. Background tasks must execute in dedicated `QThread` workers or asyncio tasks using thread-local sessions (`get_session()`).
3. **Graceful Degraded Modes**: Code must fail gracefully when optional dependencies (`OpenL3`, `Ollama`, `MusicBrainz`) are unavailable, switching to local fallbacks without crashing the application.
4. **Deterministic Feature Limits**: Audio processing operations must bound resource consumption (e.g. limiting duration to first 60 seconds at 22.05kHz mono).

---

## 2. Code Style & Formatting

- **Python Version**: Python 3.13+
- **Type Annotations**: All function signatures must include Python type hints (`str`, `int`, `list[dict]`, `Session`).
- **Pydantic Models**: Use Pydantic v2 `BaseModel` for validation schemas.
- **Docstrings**: Google-style docstrings for all modules, classes, and public functions.

### Example Function Standard
```python
def process_data(song_id: int, db_session: Session) -> dict | None:
    """Processes a song record and returns formatted attributes.

    Args:
        song_id: Primary key ID of the target song.
        db_session: Active SQLAlchemy session.

    Returns:
        Formatted summary dict or None if song is not found.
    """
    song = db_session.get(Song, song_id)
    if not song:
        logger.warning("Song ID %d not found.", song_id)
        return None
    return {"id": song.id, "title": song.title}
```

---

## 3. Logging Conventions

Verse uses a centralized logging hierarchy initialized via `app.utils.logging.setup_logging()`:
- Use named loggers per module: `logger = logging.getLogger("music_rec.<subsystem>")`.
- Log Level Rules:
  - `DEBUG`: Verbose loop details, raw SQL query params, UI signal triggers.
  - `INFO`: Scan progress steps, worker completions, API request summaries.
  - `WARNING`: Recoverable fallbacks (e.g. OpenL3 import failure, missing MusicBrainz hit).
  - `ERROR`: Unhandled exceptions, failed pipeline steps, database rollbacks.

---

## 4. Pull Request (PR) Checklist

Before submitting a PR:
1. Run `pytest` and ensure all test cases pass cleanly.
2. Verify type annotations and imports.
3. Ensure no hardcoded absolute filesystem paths or secret keys are committed.
4. Update relevant documentation in `/docs` if adding or modifying features.
