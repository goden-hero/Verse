"""Database connection setup and session lifecycle helpers."""

import logging
from collections.abc import Generator
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from app.config.settings import settings
from app.database.models import Base

logger = logging.getLogger("music_rec.database.connection")

# Configure SQLite-specific connection listener to enforce foreign keys
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """Enforces SQLite foreign key constraints upon connection."""
    # Only execute for sqlite connections
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    except Exception as e:
        logger.debug("Failed to set PRAGMA foreign_keys: %s", e)
    finally:
        cursor.close()


# Resolve database engine
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

# Thread-safe sessionmaker
SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
SessionLocal = scoped_session(SessionFactory)


def init_db() -> None:
    """Creates all tables if they do not exist in the database.

    Ensures the parent directory of the database file exists beforehand.
    """
    # If using SQLite, ensure the parent data folder exists
    if settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.replace("sqlite:///", ""))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        logger.info("Initializing database schema...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.error("Failed to initialize database schema: %s", e)
        raise


from contextlib import contextmanager


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Dependency / generator context manager for db sessions.

    Yields:
        A thread-safe SQLAlchemy Session object.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
