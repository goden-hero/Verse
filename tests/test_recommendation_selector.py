"""Unit tests for the recommendation selector and automatic fallback logic."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy.orm import Session
from app.database.models import AudioFeatures, Embeddings, Song
from app.recommendations.selector import (
    get_automatic_strategy,
    is_content_available,
    is_vector_available,
    map_ui_to_backend_strategy,
)


def test_is_vector_available_no_file(db_session: Session) -> None:
    """Verifies is_vector_available returns False if the vector index file does not exist."""
    non_existent_path = Path("/tmp/does_not_exist_vector_index.bin")
    assert not is_vector_available(db_session, non_existent_path)


@patch("app.recommendations.selector.FAISSIndex")
def test_is_vector_available_empty_db(mock_faiss_cls, db_session: Session, tmp_path: Path) -> None:
    """Verifies is_vector_available returns False if the database has no embeddings."""
    mock_idx = MagicMock()
    mock_idx.load.return_value = True
    mock_idx.index.ntotal = 5
    mock_faiss_cls.return_value = mock_idx

    dummy_path = tmp_path / "vector_index.bin"
    dummy_path.write_text("dummy content")

    # DB is empty (no Embeddings records)
    assert not is_vector_available(db_session, dummy_path)


@patch("app.recommendations.selector.FAISSIndex")
def test_is_vector_available_success(mock_faiss_cls, db_session: Session, tmp_path: Path) -> None:
    """Verifies is_vector_available returns True if database has embeddings and index loads successfully with items."""
    mock_idx = MagicMock()
    mock_idx.load.return_value = True
    mock_idx.index.ntotal = 5
    mock_faiss_cls.return_value = mock_idx

    dummy_path = tmp_path / "vector_index.bin"
    dummy_path.write_text("dummy content")

    # Insert a dummy embedding
    song = Song(title="Test Song", artist="Artist", path="path", hash="dummy_hash_1")
    db_session.add(song)
    db_session.commit()

    emb = Embeddings(song_id=song.id, vector=b"dummy_bytes")
    db_session.add(emb)
    db_session.commit()

    assert is_vector_available(db_session, dummy_path)


def test_is_content_available_empty_db(db_session: Session) -> None:
    """Verifies is_content_available returns False if database has no audio features."""
    assert not is_content_available(db_session)


def test_is_content_available_success(db_session: Session) -> None:
    """Verifies is_content_available returns True if database has audio features."""
    song = Song(title="Test Song", artist="Artist", path="path", hash="dummy_hash_2")
    db_session.add(song)
    db_session.commit()

    feat = AudioFeatures(song_id=song.id, bpm=120.0)
    db_session.add(feat)
    db_session.commit()

    assert is_content_available(db_session)


@patch("app.recommendations.selector.is_vector_available")
@patch("app.recommendations.selector.is_content_available")
def test_get_automatic_strategy(mock_content_ok, mock_vector_ok, db_session: Session) -> None:
    """Verifies fallback hierarchy of get_automatic_strategy:

    - Both available -> hybrid
    - Only vector available -> vector
    - Only content available -> content
    - Neither available -> hybrid (last resort fallback)
    """
    # 1. Both available
    mock_vector_ok.return_value = True
    mock_content_ok.return_value = True
    assert get_automatic_strategy(db_session) == "hybrid"

    # 2. Only vector available
    mock_vector_ok.return_value = True
    mock_content_ok.return_value = False
    assert get_automatic_strategy(db_session) == "vector"

    # 3. Only content available
    mock_vector_ok.return_value = False
    mock_content_ok.return_value = True
    assert get_automatic_strategy(db_session) == "content"

    # 4. Neither available
    mock_vector_ok.return_value = False
    mock_content_ok.return_value = False
    assert get_automatic_strategy(db_session) == "hybrid"


@patch("app.recommendations.selector.get_automatic_strategy")
def test_map_ui_to_backend_strategy(mock_get_auto, db_session: Session) -> None:
    """Verifies map_ui_to_backend_strategy translates correctly and tolerates casing/whitespace."""
    mock_get_auto.return_value = "vector"

    # Test friendly UI styles
    assert map_ui_to_backend_strategy("Similar Vibe", db_session) == "vector"
    assert map_ui_to_backend_strategy("Similar Sound", db_session) == "content"
    assert map_ui_to_backend_strategy("Balanced", db_session) == "hybrid"
    assert map_ui_to_backend_strategy("Automatic (Recommended)", db_session) == "vector"

    # Test lowercase raw strategy inputs
    assert map_ui_to_backend_strategy("vector", db_session) == "vector"
    assert map_ui_to_backend_strategy("content", db_session) == "content"
    assert map_ui_to_backend_strategy("hybrid", db_session) == "hybrid"

    # Test casing / whitespace tolerance
    assert map_ui_to_backend_strategy("  Similar vibe  ", db_session) == "vector"
    assert map_ui_to_backend_strategy("BALANCED", db_session) == "hybrid"
