"""Helper module to handle recommendation style mappings and automatic engine selection."""

import logging
from pathlib import Path
from sqlalchemy.orm import Session
from app.database.models import Embeddings, AudioFeatures
from app.search.index import FAISSIndex
from app.config.settings import settings

logger = logging.getLogger("music_rec.recommendations.selector")


def is_vector_available(session: Session, vector_index_path: Path | str | None = None) -> bool:
    """Checks if the Vector recommendation engine is available and initialized."""
    if not vector_index_path:
        vector_index_path = Path(settings.PROJECT_ROOT) / "data" / "vector_index.bin"
    path = Path(vector_index_path)
    if not path.exists():
        return False
    try:
        # Check if database has any embedding records
        emb_exists = session.query(Embeddings).first() is not None
        if not emb_exists:
            return False

        # Load and verify FAISS index contains vectors
        idx = FAISSIndex(path)
        if idx.load() and idx.index is not None and idx.index.ntotal > 0:
            return True
    except Exception as e:
        logger.debug("Error checking vector index availability: %s", e)
    return False


def is_content_available(session: Session) -> bool:
    """Checks if the Content recommendation engine is available and initialized."""
    try:
        # ContentRecommender can rebuild the pipeline if audio features exist in DB
        feat_exists = session.query(AudioFeatures).first() is not None
        if not feat_exists:
            return False

        content_index_path = Path("data/content_index.bin")
        if content_index_path.exists() and content_index_path.stat().st_size > 0:
            return True

        return feat_exists
    except Exception as e:
        logger.debug("Error checking content pipeline availability: %s", e)
    return False


def get_automatic_strategy(session: Session, vector_index_path: Path | str | None = None) -> str:
    """Implements the fallback strategy for Automatic mode:

    1. Default to Hybrid if both Vector and Content are available.
    2. Fall back to Vector if only Vector is available.
    3. Fall back to Content if only Content is available.
    4. Fall back to Hybrid as a last resort.
    """
    vector_ok = is_vector_available(session, vector_index_path)
    content_ok = is_content_available(session)

    if vector_ok and content_ok:
        return "hybrid"
    elif vector_ok:
        return "vector"
    elif content_ok:
        return "content"
    else:
        return "hybrid"


def map_ui_to_backend_strategy(
    ui_strategy: str, session: Session, vector_index_path: Path | str | None = None
) -> str:
    """Maps the user-friendly Recommendation Style to the internal backend strategy."""
    mapping = {
        "automatic (recommended)": "automatic",
        "similar vibe": "vector",
        "similar sound": "content",
        "balanced": "hybrid",
        "vector": "vector",
        "content": "content",
        "hybrid": "hybrid",
        "automatic": "automatic",
    }

    key = ui_strategy.lower().strip()
    strategy = mapping.get(key, "hybrid")

    if strategy == "automatic":
        return get_automatic_strategy(session, vector_index_path)
    return strategy
