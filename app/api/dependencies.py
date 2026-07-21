from collections.abc import Generator
from sqlalchemy.orm import Session
from app.database.connection import get_session

def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency to yield a thread-safe database session."""
    with get_session() as session:
        yield session
