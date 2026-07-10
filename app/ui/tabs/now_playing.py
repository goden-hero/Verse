"""Now Playing tab using QMediaPlayer for actual audio playback and updating database history logs."""

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from app.database.connection import get_session
from app.database.models import Song
from app.history import get_history, record_play, record_skip, set_like_status


class NowPlayingTab(QWidget):
    """Tab containing media player widgets for real audio playback and history log triggers."""

    def __init__(self, main_window) -> None:
        super().__init__()
        self.main_window = main_window
        self.song_id = None
        self.song_duration = 0.0
        self.elapsed = 0.0
        self.is_playing = False
        self.liked_state = False

        # Initialize QMediaPlayer and QAudioOutput for actual audio playback
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        # Connect signals for playback state and progress tracking
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)

        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Song details
        self.song_label = QLabel("Double-click a song in the Library to start playing.")
        self.song_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self.song_label)

        self.meta_label = QLabel("")
        layout.addWidget(self.meta_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Control Row
        control_layout = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self.toggle_play)
        control_layout.addWidget(self.play_btn)

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setEnabled(False)
        self.skip_btn.clicked.connect(self.skip_song)
        control_layout.addWidget(self.skip_btn)

        self.skip_forward_btn = QPushButton("Skip +5s")
        self.skip_forward_btn.setEnabled(False)
        self.skip_forward_btn.clicked.connect(self.skip_5_seconds_forward)
        control_layout.addWidget(self.skip_forward_btn)

        self.like_btn = QPushButton("Like")
        self.like_btn.setEnabled(False)
        self.like_btn.clicked.connect(self.toggle_like)
        control_layout.addWidget(self.like_btn)

        control_layout.addStretch()
        layout.addLayout(control_layout)

        # History log info
        self.history_label = QLabel("")
        layout.addWidget(self.history_label)

        layout.addStretch()

    def load_song(self, song_id: int) -> None:
        """Loads a song and starts playback."""
        # Stop previous playback and save stats if playing
        self.stop_and_save_progress()

        self.song_id = song_id
        with get_session() as session:
            song = session.get(Song, song_id)
            if not song:
                return

            self.song_duration = song.duration or 180.0
            self.song_label.setText(f"{song.title} — {song.artist}")
            self.meta_label.setText(f"Album: {song.album or 'Unknown'} | Genre: {song.original_genre or 'Unknown'} | Duration: {self.song_duration:.1f}s")

            # Load like status from history
            history = get_history(song_id, session)
            self.liked_state = history["likes"] if history else False
            self.update_like_button_label()
            self.update_history_display(session)

            # Set source for real audio playback
            self.player.setSource(QUrl.fromLocalFile(song.path))

        # Reset states
        self.elapsed = 0.0
        self.progress_bar.setValue(0)
        self.play_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
        self.skip_forward_btn.setEnabled(True)
        self.like_btn.setEnabled(True)

        # Start playing immediately
        self.start_play()

    def start_play(self) -> None:
        self.is_playing = True
        self.play_btn.setText("Pause")
        self.player.play()

    def toggle_play(self) -> None:
        if self.is_playing:
            self.player.pause()
            self.is_playing = False
            self.play_btn.setText("Play")
        else:
            self.start_play()

    def on_position_changed(self, position: int) -> None:
        """Called when the player's playback position changes (in ms)."""
        self.elapsed = position / 1000.0
        if self.song_duration > 0:
            pct = int((self.elapsed / self.song_duration) * 100)
            self.progress_bar.setValue(min(pct, 100))

    def on_duration_changed(self, duration: int) -> None:
        """Called when the loaded media's duration is determined (in ms)."""
        if duration > 0:
            self.song_duration = duration / 1000.0

    def on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        """Called when the media status of the player changes."""
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.is_playing = False
            self.play_btn.setText("Play")

            # Log play event
            with get_session() as session:
                record_play(self.song_id, self.song_duration, session)
                self.update_history_display(session)

            self.elapsed = 0.0
            self.progress_bar.setValue(0)

            # Advance playback queue
            next_idx = self.main_window.current_queue_index + 1
            if next_idx < len(self.main_window.playback_queue):
                self.main_window.current_queue_index = next_idx
                self.main_window.play_song(self.main_window.playback_queue[next_idx])
            elif self.main_window.repeat_queue_mode and len(self.main_window.playback_queue) > 0:
                self.main_window.current_queue_index = 0
                self.main_window.play_song(self.main_window.playback_queue[0])

    def skip_5_seconds_forward(self) -> None:
        """Skips the playback position 5 seconds ahead."""
        if self.song_id is None:
            return
        curr_pos = self.player.position()
        duration = self.player.duration()
        new_pos = min(curr_pos + 5000, duration)
        self.player.setPosition(new_pos)

    def skip_song(self) -> None:
        """Skips song, recording skip metric, and advances queue."""
        if self.song_id is None:
            return

        self.player.stop()
        self.is_playing = False
        self.play_btn.setText("Play")

        with get_session() as session:
            record_skip(self.song_id, session)
            if self.elapsed > 0:
                record_play(self.song_id, self.elapsed, session)
            self.update_history_display(session)

        self.elapsed = 0.0
        self.progress_bar.setValue(0)

        # Advance playback queue
        next_idx = self.main_window.current_queue_index + 1
        if next_idx < len(self.main_window.playback_queue):
            self.main_window.current_queue_index = next_idx
            self.main_window.play_song(self.main_window.playback_queue[next_idx])
        elif self.main_window.repeat_queue_mode and len(self.main_window.playback_queue) > 0:
            self.main_window.current_queue_index = 0
            self.main_window.play_song(self.main_window.playback_queue[0])

    def toggle_like(self) -> None:
        """Toggles like status in database."""
        if self.song_id is None:
            return

        self.liked_state = not self.liked_state
        with get_session() as session:
            set_like_status(self.song_id, self.liked_state, session)
            self.update_like_button_label()
            self.update_history_display(session)

    def update_like_button_label(self) -> None:
        self.like_btn.setText("Unlike" if self.liked_state else "Like")

    def update_history_display(self, session) -> None:
        history = get_history(self.song_id, session)
        if history:
            self.history_label.setText(
                f"Listening Logs: Plays: {history['play_count']} | Skips: {history['skips']} | "
                f"Liked: {history['likes']} | Cumulative Play Duration: {history['play_duration']:.1f}s"
            )
        else:
            self.history_label.setText("Listening Logs: No plays logged yet.")

    def stop_and_save_progress(self) -> None:
        """Saves play progress if media is playing during song transition or close."""
        if self.song_id is not None and self.is_playing and self.elapsed > 0:
            self.player.stop()
            self.is_playing = False
            with get_session() as session:
                record_play(self.song_id, self.elapsed, session)
            self.elapsed = 0.0
