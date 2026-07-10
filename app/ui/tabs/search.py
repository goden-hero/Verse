"""Search tab to query songs using metadata text filtering or vector similarity."""

import pickle
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from app.database.connection import get_session
from app.database.models import Embeddings, Song
from app.search.index import FAISSIndex


class SearchTab(QWidget):
    """Tab supporting text searches and vector searches on the library."""

    def __init__(self, main_window) -> None:
        super().__init__()
        self.main_window = main_window

        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Control Row
        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("Query:"))

        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Enter title, artist, or genre...")
        self.query_input.returnPressed.connect(self.perform_search)
        control_layout.addWidget(self.query_input)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Metadata Text", "Vector Similarity"])
        control_layout.addWidget(self.type_combo)

        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.perform_search)
        control_layout.addWidget(self.search_btn)

        layout.addLayout(control_layout)

        # Status label
        self.status_label = QLabel("Enter search query.")
        layout.addWidget(self.status_label)

        # Results list
        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.song_double_clicked)
        layout.addWidget(self.results_list)

    def perform_search(self) -> None:
        """Runs the search query."""
        self.results_list.clear()
        query = self.query_input.text().strip()
        search_type = self.type_combo.currentText()

        if not query:
            # If query is empty, list all library songs
            self.main_window.library_tab.refresh_library()
            # Copy all items to search results list
            for i in range(self.main_window.library_tab.songs_list.count()):
                ref_item = self.main_window.library_tab.songs_list.item(i)
                item = QListWidgetItem(ref_item.text())
                item.setData(Qt.UserRole, ref_item.data(Qt.UserRole))
                self.results_list.addItem(item)
            self.status_label.setText("Showing all songs in library.")
            return

        with get_session() as session:
            from app.services.search import SearchService

            if search_type == "Metadata Text":
                songs = SearchService.metadata_search(query, session)
                self.status_label.setText(f"Found {len(songs)} matches:")
                for song in songs:
                    item = QListWidgetItem(f"{song['title']} — {song['artist']}")
                    item.setData(Qt.UserRole, song['id'])
                    self.results_list.addItem(item)
            else:
                # Vector Similarity Search
                results = SearchService.vector_search(query, session, k=6)
                if not results:
                    self.status_label.setText("No similar songs found.")
                    return

                self.status_label.setText(f"Similarity search results based on matches:")
                for match in results:
                    item = QListWidgetItem(f"{match['title']} — {match['artist']} (similarity score: {match['score']:.2f})")
                    item.setData(Qt.UserRole, match['id'])
                    self.results_list.addItem(item)

    def song_double_clicked(self, item: QListWidgetItem) -> None:
        song_id = item.data(Qt.UserRole)
        self.main_window.play_song(song_id)
