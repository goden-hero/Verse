"""pytest configuration and shared fixtures."""

import pytest
from pathlib import Path


@pytest.fixture
def mock_music_library(tmp_path: Path) -> Path:
    """Creates a temporary music folder structure with mock audio files."""
    # Create main library folder
    lib_dir = tmp_path / "music_library"
    lib_dir.mkdir()

    # Create normal files
    (lib_dir / "song1.mp3").write_text("audio content 1")
    (lib_dir / "song2.FLAC").write_text("audio content 2")
    (lib_dir / "readme.txt").write_text("doc content")

    # Create subfolder
    sub_dir = lib_dir / "Pop"
    sub_dir.mkdir()
    (sub_dir / "song3.wav").write_text("audio content 3")
    (sub_dir / "song4.m4a").write_text("audio content 4")
    (sub_dir / "song5.ogg").write_text("audio content 5")
    (sub_dir / "unsupported.mp4").write_text("video content")

    # Create hidden subfolder
    hidden_dir = lib_dir / ".hidden_folder"
    hidden_dir.mkdir()
    (hidden_dir / "song6.mp3").write_text("hidden audio content")

    # Create hidden file in Pop
    (sub_dir / ".hidden_song.mp3").write_text("hidden pop audio content")

    return lib_dir


@pytest.fixture(scope="function")
def db_engine():
    """Creates a temporary in-memory database engine for tests."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.pool import StaticPool
    from app.database.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

    # Enforce foreign keys in SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db_engine) -> Generator["Session", None, None]:
    """Provides an isolated SQLAlchemy Session for testing."""
    from collections.abc import Generator
    from sqlalchemy.orm import Session, sessionmaker

    SessionClass = sessionmaker(bind=db_engine)
    session = SessionClass()

    yield session

    session.close()
