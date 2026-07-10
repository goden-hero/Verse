"""AI Assistant tab supporting natural language prompts, plan checkpoints, and playlist preview."""

import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from app.ui.workers import AssistantWorker
from app.services.playback import PlaybackService

logger = logging.getLogger("music_rec.ui.tabs.assistant")


class AssistantTab(QWidget):
    """Interacts with AssistantWorker to display execution plans, track checkmarks, and previews."""

    def __init__(self, main_window) -> None:
        super().__init__()
        self.main_window = main_window
        self.assistant_worker = None
        self.last_generated_playlist = None

        self.init_ui()

    def init_ui(self) -> None:
        layout = QHBoxLayout(self)

        # Splitter to separate Chat logs (left) and Action Execution Details (right)
        splitter = QSplitter(Qt.Horizontal)

        # Left pane: Chat Panel
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.addWidget(QLabel("Assistant Chat History:"))

        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.append("AI Assistant: Hello! Ask me to create a playlist or play songs using natural language.\n")
        chat_layout.addWidget(self.chat_history)

        input_layout = QHBoxLayout()
        self.message_input = QTextEdit()
        self.message_input.setPlaceholderText("Type a prompt (e.g. 'Make me a study playlist and play it')")
        self.message_input.setMaximumHeight(65)
        input_layout.addWidget(self.message_input)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.send_message)
        self.send_btn.setFixedHeight(65)
        input_layout.addWidget(self.send_btn)
        chat_layout.addLayout(input_layout)

        splitter.addWidget(chat_widget)

        # Right pane: Orchestrator Panel
        orch_widget = QWidget()
        orch_layout = QVBoxLayout(orch_widget)

        # Plan checklist Box
        plan_box = QGroupBox("Execution Plan Checklist")
        plan_layout = QVBoxLayout(plan_box)
        
        self.status_label = QLabel("Status: Idle")
        self.status_label.setStyleSheet("font-weight: bold; color: #555;")
        plan_layout.addWidget(self.status_label)

        self.plan_list = QListWidget()
        plan_layout.addWidget(self.plan_list)
        orch_layout.addWidget(plan_box)

        # Generated Playlist Preview Box
        self.playlist_box = QGroupBox("Generated Playlist Preview")
        self.playlist_layout = QVBoxLayout(self.playlist_box)

        self.playlist_title = QLabel("No playlist generated yet.")
        self.playlist_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.playlist_layout.addWidget(self.playlist_title)

        self.playlist_meta = QLabel("")
        self.playlist_layout.addWidget(self.playlist_meta)

        self.playlist_tracks = QListWidget()
        self.playlist_layout.addWidget(self.playlist_tracks)

        # Action Buttons Row
        action_layout = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self.play_generated_playlist)
        action_layout.addWidget(self.play_btn)

        self.open_btn = QPushButton("Open Playlist")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self.open_generated_playlist)
        action_layout.addWidget(self.open_btn)

        self.regenerate_btn = QPushButton("Regenerate")
        self.regenerate_btn.setEnabled(False)
        self.regenerate_btn.clicked.connect(self.regenerate_current_request)
        action_layout.addWidget(self.regenerate_btn)

        self.playlist_layout.addLayout(action_layout)
        orch_layout.addWidget(self.playlist_box)

        splitter.addWidget(orch_widget)
        layout.addWidget(splitter)

        # Set splitter balance
        splitter.setSizes([450, 350])

    def send_message(self) -> None:
        """Sends chat request to local LLM parser & execution pipeline."""
        message = self.message_input.toPlainText().strip()
        if not message:
            return

        self.chat_history.append(f"You: {message}\n")
        self.message_input.clear()
        self.send_btn.setEnabled(False)

        # Reset execution widgets
        self.plan_list.clear()
        self.playlist_tracks.clear()
        self.playlist_title.setText("No playlist generated yet.")
        self.playlist_meta.setText("")
        self.play_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.regenerate_btn.setEnabled(False)
        self.status_label.setText("Status: Executing parser...")

        # Spawn background worker
        self.assistant_worker = AssistantWorker(message)
        self.assistant_worker.progress.connect(self.update_plan_step)
        self.assistant_worker.playlist_generated.connect(self.preview_playlist)
        self.assistant_worker.finished.connect(self.plan_finished)
        self.assistant_worker.error.connect(self.plan_failed)
        self.assistant_worker.start()

    def update_plan_step(self, step_name: str, status: str) -> None:
        """Updates plan checkpoints checklists with checkmarks/symbols."""
        self.status_label.setText(f"Status: Executing {step_name}...")
        
        # Check if list already has step
        items = self.plan_list.findItems(step_name, Qt.MatchEndsWith)
        if items:
            item = items[0]
        else:
            item = QListWidgetItem()
            self.plan_list.addItem(item)

        if status == "success":
            item.setText(f"✓ {step_name}")
            item.setForeground(Qt.green)
        elif status == "error":
            item.setText(f"✗ {step_name}")
            item.setForeground(Qt.red)
        else:
            item.setText(f"⋯ {step_name}")
            item.setForeground(Qt.blue)

    def preview_playlist(self, playlist_details: dict) -> None:
        """Populates preview metadata and tracks lists when a playlist is generated."""
        self.last_generated_playlist = playlist_details
        self.playlist_title.setText(playlist_details.get("name", "Generated Playlist"))
        
        count = playlist_details.get("songs_count", 0)
        dur = playlist_details.get("total_duration", 0.0)
        minutes = int(dur // 60)
        seconds = int(dur % 60)
        strategy = playlist_details.get("strategy", "hybrid")

        self.playlist_meta.setText(f"{count} Songs | {minutes}m {seconds}s | Strategy: {strategy}")
        
        self.playlist_tracks.clear()
        for song in playlist_details.get("songs", []):
            self.playlist_tracks.addItem(f"{song['title']} — {song['artist']}")

        self.play_btn.setEnabled(True)
        has_id = playlist_details.get("id") is not None
        self.open_btn.setEnabled(has_id)
        self.regenerate_btn.setEnabled(has_id)

    def plan_finished(self, summary: str, steps: list) -> None:
        self.send_btn.setEnabled(True)
        self.status_label.setText("Status: Completed")
        self.chat_history.append(f"AI Assistant: {summary}\n")
        
        # Refresh the playlist tab automatically so the newly generated playlist displays
        if hasattr(self.main_window, "playlists_tab"):
            self.main_window.playlists_tab.refresh_playlists()

    def plan_failed(self, error_msg: str) -> None:
        self.send_btn.setEnabled(True)
        self.status_label.setText("Status: Failed")
        self.chat_history.append(f"AI Assistant Error: {error_msg}\n")

    def play_generated_playlist(self) -> None:
        if not self.last_generated_playlist:
            return
        
        song_ids = [s["id"] for s in self.last_generated_playlist.get("songs", [])]
        if song_ids:
            self.main_window.playback_queue = song_ids
            self.main_window.current_queue_index = 0
            PlaybackService.play_song(song_ids[0])

    def open_generated_playlist(self) -> None:
        if not self.last_generated_playlist:
            return
        
        playlist_id = self.last_generated_playlist.get("id")
        if playlist_id and hasattr(self.main_window, "playlists_tab"):
            self.main_window.tabs.setCurrentWidget(self.main_window.playlists_tab)
            self.main_window.playlists_tab.open_playlist_by_id(playlist_id)

    def regenerate_current_request(self) -> None:
        if not self.last_generated_playlist:
            return
        
        # Regenerate via PlaylistsTab method
        playlist_id = self.last_generated_playlist.get("id")
        if playlist_id and hasattr(self.main_window, "playlists_tab"):
            self.main_window.playlists_tab.selected_playlist_id = playlist_id
            self.main_window.playlists_tab.regenerate_playlist()
            # Clear preview as playlist ID was deleted
            self.playlist_tracks.clear()
            self.playlist_title.setText("Regenerating...")
            self.playlist_meta.setText("")
            self.play_btn.setEnabled(False)
            self.open_btn.setEnabled(False)
            self.regenerate_btn.setEnabled(False)
