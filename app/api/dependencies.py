from collections.abc import Generator
from sqlalchemy.orm import Session
from app.database.connection import get_session
from app.identity import CurrentUser, get_current_user


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency to yield a thread-safe database session."""
    with get_session() as session:
        yield session


__all__ = ["get_db", "get_current_user", "CurrentUser"]

