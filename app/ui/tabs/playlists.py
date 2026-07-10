"""Playlists tab to view, play, rename, delete, and regenerate manual or AI playlists."""

import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from app.database.connection import get_session
from app.services.playlist import PlaylistService
from app.services.playback import PlaybackService

logger = logging.getLogger("music_rec.ui.tabs.playlists")


class PlaylistsTab(QWidget):
    """Tab containing lists of saved playlists and their song lists."""

    def __init__(self, main_window) -> None:
        super().__init__()
        self.main_window = main_window
        self.selected_playlist_id = None

        self.init_ui()

    def init_ui(self) -> None:
        layout = QHBoxLayout(self)

        # Splitter to divide left (playlist list) and right (details + song list)
        splitter = QSplitter(Qt.Horizontal)

        # Left pane: playlists list
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.addWidget(QLabel("Playlists:"))
        
        self.playlists_list = QListWidget()
        self.playlists_list.itemClicked.connect(self.playlist_selected)
        left_layout.addWidget(self.playlists_list)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_playlists)
        left_layout.addWidget(self.refresh_btn)

        splitter.addWidget(left_widget)

        # Right pane: details & songs list
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # Playlist Info Card
        self.info_label = QLabel("Select a playlist to view details.")
        self.info_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        right_layout.addWidget(self.info_label)

        self.meta_label = QLabel("")
        right_layout.addWidget(self.meta_label)

        # Controls Row
        btn_layout = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self.play_playlist)
        btn_layout.addWidget(self.play_btn)

        self.queue_btn = QPushButton("Queue")
        self.queue_btn.setEnabled(False)
        self.queue_btn.clicked.connect(self.queue_playlist)
        btn_layout.addWidget(self.queue_btn)

        self.rename_btn = QPushButton("Rename")
        self.rename_btn.setEnabled(False)
        self.rename_btn.clicked.connect(self.rename_playlist)
        btn_layout.addWidget(self.rename_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self.delete_playlist)
        btn_layout.addWidget(self.delete_btn)

        self.regenerate_btn = QPushButton("Regenerate")
        self.regenerate_btn.setEnabled(False)
        self.regenerate_btn.clicked.connect(self.regenerate_playlist)
        btn_layout.addWidget(self.regenerate_btn)

        right_layout.addLayout(btn_layout)

        # Songs in playlist
        right_layout.addWidget(QLabel("Songs:"))
        self.songs_list = QListWidget()
        self.songs_list.itemDoubleClicked.connect(self.song_double_clicked)
        right_layout.addWidget(self.songs_list)

        splitter.addWidget(right_widget)
        layout.addWidget(splitter)

        # Set sizes (30% left, 70% right)
        splitter.setSizes([240, 560])

        self.refresh_playlists()

    def refresh_playlists(self) -> None:
        """Loads playlists from database."""
        self.playlists_list.clear()
        with get_session() as session:
            playlists = PlaylistService.get_playlists(session)
            for p in playlists:
                item = QListWidgetItem(f"{p['name']} ({p['songs_count']} songs)")
                item.setData(Qt.UserRole, p["id"])
                self.playlists_list.addItem(item)
                
        # Disable buttons if no selection active
        if self.selected_playlist_id is None:
            self.play_btn.setEnabled(False)
            self.queue_btn.setEnabled(False)
            self.rename_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            self.regenerate_btn.setEnabled(False)
            self.info_label.setText("Select a playlist to view details.")
            self.meta_label.setText("")
            self.songs_list.clear()

    def playlist_selected(self, item: QListWidgetItem) -> None:
        playlist_id = item.data(Qt.UserRole)
        self.open_playlist_by_id(playlist_id)

    def open_playlist_by_id(self, playlist_id: int) -> None:
        """Opens a playlist view details by database ID."""
        self.selected_playlist_id = playlist_id
        self.songs_list.clear()

        with get_session() as session:
            # Query playlist details
            playlists = PlaylistService.get_playlists(session)
            p = next((x for x in playlists if x["id"] == playlist_id), None)
            if not p:
                return

            minutes = int(p["total_duration"] // 60)
            seconds = int(p["total_duration"] % 60)
            strategy = p["strategy"] or "manual"
            created_at = p["created_at"].split(".")[0].replace("T", " ")

            self.info_label.setText(f"{p['name']} ({p['generated_by']} Generated)")
            self.meta_label.setText(
                f"Strategy: {strategy} | Created: {created_at} | Duration: {minutes}m {seconds}s"
            )

            # Load songs list
            songs = PlaylistService.get_playlist_songs(playlist_id, session)
            for s in songs:
                s_item = QListWidgetItem(f"{s['title']} — {s['artist']}")
                s_item.setData(Qt.UserRole, s["id"])
                self.songs_list.addItem(s_item)

        # Enable buttons
        self.play_btn.setEnabled(True)
        self.queue_btn.setEnabled(True)
        self.rename_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        # Enable regenerate only for AI generated playlists
        self.regenerate_btn.setEnabled(p["generated_by"] == "AI")

    def play_playlist(self) -> None:
        if self.selected_playlist_id is None:
            return

        with get_session() as session:
            songs = PlaylistService.get_playlist_songs(self.selected_playlist_id, session)
            if songs:
                # Load songs into playback queue
                self.main_window.playback_queue = [s["id"] for s in songs]
                self.main_window.current_queue_index = 0
                # Play first song
                PlaybackService.play_song(songs[0]["id"])

    def queue_playlist(self) -> None:
        if self.selected_playlist_id is None:
            return

        with get_session() as session:
            songs = PlaylistService.get_playlist_songs(self.selected_playlist_id, session)
            if songs:
                if not hasattr(self.main_window, "playback_queue") or not self.main_window.playback_queue:
                    self.main_window.playback_queue = [s["id"] for s in songs]
                    self.main_window.current_queue_index = 0
                    PlaybackService.play_song(songs[0]["id"])
                else:
                    self.main_window.playback_queue.extend([s["id"] for s in songs])
                logger.info("Queued %d songs in active playback queue.", len(songs))

    def rename_playlist(self) -> None:
        if self.selected_playlist_id is None:
            return

        new_name, ok = QInputDialog.getText(self, "Rename Playlist", "Enter new name:")
        if ok and new_name.strip():
            with get_session() as session:
                PlaylistService.rename_playlist(self.selected_playlist_id, new_name.strip(), session)
            self.refresh_playlists()
            self.open_playlist_by_id(self.selected_playlist_id)

    def delete_playlist(self) -> None:
        if self.selected_playlist_id is None:
            return

        with get_session() as session:
            PlaylistService.delete_playlist(self.selected_playlist_id, session)
        self.selected_playlist_id = None
        self.refresh_playlists()

    def regenerate_playlist(self) -> None:
        """Regenerates the songs in the selected AI playlist using its saved config details."""
        if self.selected_playlist_id is None:
            return

        with get_session() as session:
            playlists = PlaylistService.get_playlists(session)
            p = next((x for x in playlists if x["id"] == self.selected_playlist_id), None)
            if not p or p["generated_by"] != "AI":
                return

            # Re-generate playlist with same filters/parameters
            # We can extract filters from prompt text or build a mock filter set
            filters = {}
            if p["prompt"]:
                # Parse mood tags keywords from the prompt if present
                for word in ["chill", "happy", "focused", "sad", "energetic"]:
                    if word in p["prompt"].lower():
                        filters.setdefault("moods", []).append(word)

            PlaylistService.generate_playlist(
                name=p["name"],
                strategy=p["strategy"] or "hybrid",
                filters=filters,
                target_length=p["songs_count"] or 25,
                session=session,
                prompt=p["prompt"],
            )

            # Delete old duplicate playlist if a new one is created, or since PlaylistService.generate_playlist creates a new one
            # We delete the old playlist
            PlaylistService.delete_playlist(self.selected_playlist_id, session)

        # Refresh
        self.selected_playlist_id = None
        self.refresh_playlists()

    def song_double_clicked(self, item: QListWidgetItem) -> None:
        song_id = item.data(Qt.UserRole)
        PlaybackService.play_song(song_id)
