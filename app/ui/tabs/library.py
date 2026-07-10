"""Library tab for viewing indexed songs and scanning directories."""

from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from app.database.connection import get_session
from app.database.models import Song
from app.ui.workers import ScanWorker


class LibraryTab(QWidget):
    """Tab containing the local library list and scanning controls."""

    def __init__(self, main_window) -> None:
        super().__init__()
        self.main_window = main_window
        self.scan_worker = None

        self.init_ui()
        self.refresh_library()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Control Row
        control_layout = QHBoxLayout()
        self.scan_btn = QPushButton("Scan Music Folder")
        self.scan_btn.clicked.connect(self.start_scan)
        control_layout.addWidget(self.scan_btn)

        self.status_label = QLabel("Library Ready.")
        control_layout.addWidget(self.status_label)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Songs List
        self.songs_list = QListWidget()
        self.songs_list.itemDoubleClicked.connect(self.song_double_clicked)
        layout.addWidget(self.songs_list)

    def refresh_library(self) -> None:
        """Reloads all songs from the SQLite database."""
        self.songs_list.clear()
        with get_session() as session:
            songs = session.query(Song).order_by(Song.title).all()
            for song in songs:
                item = QListWidgetItem(f"{song.title} — {song.artist}")
                item.setData(Qt.UserRole, song.id)
                self.songs_list.addItem(item)

    def start_scan(self) -> None:
        """Opens folder picker and launches ScanWorker."""
        folder = QFileDialog.getExistingDirectory(self, "Select Music Directory")
        if not folder:
            return

        self.scan_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Preparing scan...")

        # Setup worker
        vector_index_path = self.main_window.settings_tab.get_vector_index_path()
        self.scan_worker = ScanWorker(folder, vector_index_path)
        self.scan_worker.progress.connect(self.update_scan_progress)
        self.scan_worker.finished.connect(self.scan_finished)
        self.scan_worker.error.connect(self.scan_error)
        self.scan_worker.start()

    def update_scan_progress(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    def scan_finished(self, new_songs: int) -> None:
        self.scan_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"Scan complete. Added/Updated {new_songs} songs.")
        self.refresh_library()
        self.main_window.search_tab.perform_search() # refresh search tab if any query is active

    def scan_error(self, error_msg: str) -> None:
        self.scan_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"Scan failed: {error_msg}")

    def song_double_clicked(self, item: QListWidgetItem) -> None:
        """Loads selected song in Now Playing tab."""
        song_id = item.data(Qt.UserRole)
        self.main_window.play_song(song_id)
