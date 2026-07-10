"""Core QMainWindow implementation for the Music Recommendation System."""

import logging
from PySide6.QtWidgets import QMainWindow, QTabWidget
from app.ui.tabs.assistant import AssistantTab
from app.ui.tabs.library import LibraryTab
from app.ui.tabs.now_playing import NowPlayingTab
from app.ui.tabs.recommendations import RecommendationsTab
from app.ui.tabs.search import SearchTab
from app.ui.tabs.settings import SettingsTab

logger = logging.getLogger("music_rec.ui.main_window")


class MainWindow(QMainWindow):
    """Main window class containing the tabbed layout manager."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Music Recommendation System")
        self.resize(800, 600)
        self.current_song_id = None

        # Register global playback handler
        from app.services.playback import PlaybackService
        PlaybackService.register_handler(self)

        self.playback_queue = []
        self.current_queue_index = 0
        self.repeat_queue_mode = False

        self.init_ui()

    def init_ui(self) -> None:
        self.tabs = QTabWidget()

        # Instantiate tabs
        from app.ui.tabs.playlists import PlaylistsTab
        self.settings_tab = SettingsTab(self)
        self.library_tab = LibraryTab(self)
        self.now_playing_tab = NowPlayingTab(self)
        self.recommendations_tab = RecommendationsTab(self)
        self.playlists_tab = PlaylistsTab(self)
        self.search_tab = SearchTab(self)
        self.assistant_tab = AssistantTab(self)

        # Add tabs to central widget layout manager
        self.tabs.addTab(self.library_tab, "Library")
        self.tabs.addTab(self.now_playing_tab, "Now Playing")
        self.tabs.addTab(self.recommendations_tab, "Recommendations")
        self.tabs.addTab(self.playlists_tab, "Playlists")
        self.tabs.addTab(self.search_tab, "Search")
        self.tabs.addTab(self.assistant_tab, "AI Assistant")
        self.tabs.addTab(self.settings_tab, "Settings")

        self.setCentralWidget(self.tabs)

    def play_song(self, song_id: int) -> None:
        """Helper to load a song in Now Playing and focus the tab."""
        self.current_song_id = song_id
        # Load song details and start play
        self.now_playing_tab.load_song(song_id)
        # Select the Now Playing tab
        self.tabs.setCurrentWidget(self.now_playing_tab)

    def closeEvent(self, event) -> None:
        """Clean up background threads and log playing progress on exit."""
        logger.info("Main UI window closing. Triggering cleanup processes...")
        # Save any in-progress playback session
        self.now_playing_tab.stop_and_save_progress()
        
        # Stop background workers if active
        if self.library_tab.scan_worker and self.library_tab.scan_worker.isRunning():
            self.library_tab.scan_worker.terminate()
            self.library_tab.scan_worker.wait()
            
        if self.recommendations_tab.recommend_worker and self.recommendations_tab.recommend_worker.isRunning():
            self.recommendations_tab.recommend_worker.terminate()
            self.recommendations_tab.recommend_worker.wait()

        if self.assistant_tab.assistant_worker and self.assistant_tab.assistant_worker.isRunning():
            self.assistant_tab.assistant_worker.terminate()
            self.assistant_tab.assistant_worker.wait()

        event.accept()
