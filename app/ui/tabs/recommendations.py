"""Recommendations tab for retrieving similar songs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from app.database.connection import get_session
from app.database.models import Song
from app.ui.workers import RecommendWorker


class RecommendationsTab(QWidget):
    """Tab allowing strategy configuration and querying recommendations."""

    def __init__(self, main_window) -> None:
        super().__init__()
        self.main_window = main_window
        self.recommend_worker = None

        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Strategy selector and controls
        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("Recommendation Style:"))

        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems([
            "Automatic (Recommended)",
            "Similar Vibe",
            "Similar Sound",
            "Balanced"
        ])
        control_layout.addWidget(self.strategy_combo)

        self.rec_btn = QPushButton("Get Recommendations")
        self.rec_btn.clicked.connect(self.fetch_recommendations)
        control_layout.addWidget(self.rec_btn)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        # Playlist Generation Row
        gen_layout = QHBoxLayout()
        gen_layout.addWidget(QLabel("Generate Playlist from:"))

        self.playlist_source_combo = QComboBox()
        self.playlist_source_combo.addItems([
            "Current Song",
            "Current Queue",
            "Favorites",
            "Recently Played",
            "Mood",
            "Activity"
        ])
        gen_layout.addWidget(self.playlist_source_combo)

        self.gen_btn = QPushButton("Generate Playlist")
        self.gen_btn.clicked.connect(self.generate_playlist_from_recommendations)
        gen_layout.addWidget(self.gen_btn)
        gen_layout.addStretch()
        layout.addLayout(gen_layout)

        # Status label
        self.status_label = QLabel("Select a song to base recommendations on.")
        layout.addWidget(self.status_label)

        # Recommendations list
        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.song_double_clicked)
        layout.addWidget(self.results_list)

    def fetch_recommendations(self) -> None:
        """Launches RecommendWorker for currently loaded/playing song."""
        song_id = self.main_window.current_song_id
        if song_id is None:
            self.status_label.setText("Error: Please select or play a song first.")
            return

        strategy = self.strategy_combo.currentText()
        self.status_label.setText(f"Querying {strategy} recommender engine...")
        self.rec_btn.setEnabled(False)
        self.results_list.clear()

        # Spawns background worker
        vector_path = self.main_window.settings_tab.get_vector_index_path()
        self.recommend_worker = RecommendWorker(
            strategy=strategy,
            song_id=song_id,
            limit=10,
            vector_index_path=vector_path,
        )
        self.recommend_worker.finished.connect(self.display_recommendations)
        self.recommend_worker.error.connect(self.handle_error)
        self.recommend_worker.start()

    def display_recommendations(self, results: list) -> None:
        self.rec_btn.setEnabled(True)
        if not results:
            self.status_label.setText("No recommendations found.")
            return

        self.status_label.setText(f"Found {len(results)} recommendations:")
        for song, score in results:
            item = QListWidgetItem(f"{song.title} — {song.artist} (similarity score: {score:.2f})")
            item.setData(Qt.UserRole, song.id)
            self.results_list.addItem(item)

    def handle_error(self, error_msg: str) -> None:
        self.rec_btn.setEnabled(True)
        self.status_label.setText(f"Query failed: {error_msg}")

    def song_double_clicked(self, item: QListWidgetItem) -> None:
        song_id = item.data(Qt.UserRole)
        self.main_window.play_song(song_id)

    def generate_playlist_from_recommendations(self) -> None:
        """Triggers PlaylistService to construct and save a new playlist based on seeds/filters."""
        from PySide6.QtWidgets import QInputDialog
        from datetime import datetime
        import random
        from app.services.playlist import PlaylistService
        from app.recommendations.selector import map_ui_to_backend_strategy

        source = self.playlist_source_combo.currentText()
        strategy_ui = self.strategy_combo.currentText()
        filters = {}
        prompt_text = f"Generated from recommendations using source: {source}"

        with get_session() as session:
            vector_path = self.main_window.settings_tab.get_vector_index_path()
            strategy = map_ui_to_backend_strategy(strategy_ui, session, vector_path)
            if source == "Current Song":
                song_id = self.main_window.current_song_id
                if song_id is None:
                    self.status_label.setText("Error: No current song loaded.")
                    return
                song = session.get(Song, song_id)
                if song:
                    filters["seed_song_title"] = song.title
            elif source == "Current Queue":
                if not hasattr(self.main_window, "playback_queue") or not self.main_window.playback_queue:
                    self.status_label.setText("Error: Queue is empty.")
                    return
                curr_song_id = self.main_window.playback_queue[self.main_window.current_queue_index]
                song = session.get(Song, curr_song_id)
                if song:
                    filters["seed_song_title"] = song.title
            elif source == "Favorites":
                from app.database.models import History
                liked_songs = session.query(History).filter_by(likes=True).all()
                if not liked_songs:
                    self.status_label.setText("Error: No favorite/liked songs found in history.")
                    return
                seed_h = random.choice(liked_songs)
                song = session.get(Song, seed_h.song_id)
                if song:
                    filters["seed_song_title"] = song.title
            elif source == "Recently Played":
                from app.database.models import History
                recent = session.query(History).order_by(History.last_played.desc()).first()
                if not recent:
                    self.status_label.setText("Error: No playback history found.")
                    return
                song = session.get(Song, recent.song_id)
                if song:
                    filters["seed_song_title"] = song.title
            elif source == "Mood":
                mood, ok = QInputDialog.getText(self, "Generate by Mood", "Enter mood (e.g. chill, happy, focused):")
                if not ok or not mood.strip():
                    return
                filters["moods"] = [mood.strip()]
                prompt_text = f"Mood: {mood}"
            elif source == "Activity":
                activity, ok = QInputDialog.getText(self, "Generate by Activity", "Enter activity (e.g. studying, running):")
                if not ok or not activity.strip():
                    return
                filters["activities"] = [activity.strip()]
                prompt_text = f"Activity: {activity}"

            # Run playlist generation
            name = f"{source} Mix ({datetime.now().strftime('%H:%M:%S')})"
            try:
                PlaylistService.generate_playlist(
                    name=name,
                    strategy=strategy,
                    filters=filters,
                    target_length=20,
                    session=session,
                    prompt=prompt_text,
                )
                self.status_label.setText(f"Successfully generated playlist '{name}'!")
                # Refresh playlists tab
                if hasattr(self.main_window, "playlists_tab"):
                    self.main_window.playlists_tab.refresh_playlists()
                    self.main_window.tabs.setCurrentWidget(self.main_window.playlists_tab)
            except Exception as e:
                self.status_label.setText(f"Failed to generate playlist: {e}")

