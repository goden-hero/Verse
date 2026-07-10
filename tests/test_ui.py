"""Unit tests for Phase 13 Desktop UI layout and background workers."""

import os
import pytest
from unittest.mock import MagicMock, patch

# Force offscreen platform for headless Qt operation
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow
from app.ui.workers import ScanWorker, RecommendWorker, AssistantWorker


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Session-wide QApplication instance."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_main_window_tabs(qapp, db_session) -> None:
    """Verifies MainWindow layout and tab structures."""
    win = MainWindow()
    assert win.windowTitle() == "Music Recommendation System"
    assert win.tabs.count() == 7

    # Verify tab labels
    labels = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert "Library" in labels
    assert "Now Playing" in labels
    assert "Recommendations" in labels
    assert "Playlists" in labels
    assert "Search" in labels
    assert "AI Assistant" in labels
    assert "Settings" in labels

    win.close()


def test_now_playing_tab_state(qapp, db_session) -> None:
    """Verifies initial UI state of Now Playing tab is disabled until a song is loaded."""
    win = MainWindow()
    tab = win.now_playing_tab

    assert not tab.play_btn.isEnabled()
    assert not tab.skip_btn.isEnabled()
    assert not tab.like_btn.isEnabled()

    win.close()


def test_scan_worker_initialization() -> None:
    """Verifies ScanWorker constructs correctly with arguments."""
    from pathlib import Path
    worker = ScanWorker(folder_path="/test/folder", vector_index_path="/test/index.bin")
    assert worker.folder_path == Path("/test/folder")
    assert worker.vector_index_path == Path("/test/index.bin")


def test_recommend_worker_initialization() -> None:
    """Verifies RecommendWorker constructs correctly with arguments."""
    from pathlib import Path
    worker = RecommendWorker(
        strategy="vector",
        song_id=42,
        limit=5,
        vector_index_path="/test/index.bin",
    )
    assert worker.strategy == "vector"
    assert worker.song_id == 42
    assert worker.limit == 5
    assert worker.vector_index_path == Path("/test/index.bin")


def test_assistant_worker_initialization() -> None:
    """Verifies AssistantWorker constructs correctly with prompt."""
    worker = AssistantWorker("play happy music")
    assert worker.message == "play happy music"
