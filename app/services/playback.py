"""PlaybackService to handle starting, pausing, skipping, and resuming audio tracks."""

class PlaybackService:
    """Orchestrates playback commands by delegating to a registered player handler."""

    _handler = None

    @classmethod
    def register_handler(cls, handler) -> None:
        """Registers a global playback handler (typically the MainWindow)."""
        cls._handler = handler

    @classmethod
    def play_song(cls, song_id: int) -> None:
        """Instructs the active player handler to play the specified song by ID."""
        if cls._handler and hasattr(cls._handler, "play_song"):
            cls._handler.play_song(song_id)

    @classmethod
    def pause(cls) -> None:
        """Instructs the active player handler to pause active playback."""
        if cls._handler and hasattr(cls._handler, "now_playing_tab"):
            tab = cls._handler.now_playing_tab
            if hasattr(tab, "is_playing") and tab.is_playing:
                if hasattr(tab, "toggle_play"):
                    tab.toggle_play()

    @classmethod
    def resume(cls) -> None:
        """Instructs the active player handler to resume paused playback."""
        if cls._handler and hasattr(cls._handler, "now_playing_tab"):
            tab = cls._handler.now_playing_tab
            if hasattr(tab, "is_playing") and not tab.is_playing:
                if hasattr(tab, "toggle_play"):
                    tab.toggle_play()

    @classmethod
    def skip(cls) -> None:
        """Instructs the active player handler to skip the current song."""
        if cls._handler and hasattr(cls._handler, "now_playing_tab"):
            tab = cls._handler.now_playing_tab
            if hasattr(tab, "skip_song"):
                tab.skip_song()
