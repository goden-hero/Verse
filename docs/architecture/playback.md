# Playback & Session Engine Architecture

This document documents playback state registration, audio queue management, listening history tracking, playback session management, and artwork rendering.

---

## 1. Playback Architecture & Global Handler Registration

Verse uses a decoupled observer architecture for playback ([app/services/playback.py](file:///home/hisham/projects/music-rec/app/services/playback.py)). The core backend service delegates actual audio device playback to a registered UI handler (`MainWindow` in PySide6 or HTML5 Audio Node in Web SPA).

```mermaid
graph TD
    UI_REG["UI Component (MainWindow / Web SPA)"] -->|register_handler(handler)| PBS["PlaybackService"]

    USER_PLAY["User Clicks Play"] --> PBS_PLAY["PlaybackService.play_song(song_id)"]
    PBS_PLAY --> CHECK_HANDLER{"Is Handler Registered?"}
    
    CHECK_HANDLER -->|Yes| HANDLER_PLAY["handler.play_song(song_id)"]
    CHECK_HANDLER -->|No| LOG_ONLY["Log Playback Event in History Only"]

    USER_PAUSE["User Clicks Pause"] --> PBS_PAUSE["PlaybackService.pause()"]
    PBS_PAUSE --> HANDLER_PAUSE["handler.pause() / Audio Element .pause()"]

    USER_SKIP["User Clicks Skip"] --> PBS_SKIP["PlaybackService.skip()"]
    PBS_SKIP --> QUEUE_MGR["Queue Index Advance & Loop Check"]
```

---

## 2. Audio Queue State Management & Queue Navigation

The active playback handler maintains queue state properties:
- `playback_queue`: List of integer song database IDs (`list[int]`).
- `current_queue_index`: Integer index of current active song (`int`).
- `repeat_queue_mode`: Boolean flag (`True` = loop queue from beginning when end is reached).

### Shuffle Queue Algorithm
When `shuffle_queue` is executed, the current playing song remains fixed at index 0, while all remaining queued tracks are shuffled in-place using `random.shuffle()` to prevent interrupting the active track:
```python
current_song = playback_queue[current_queue_index]
remaining = [sid for sid in playback_queue if sid != current_song]
random.shuffle(remaining)
playback_queue = [current_song] + remaining
current_queue_index = 0
```

---

## 3. Session & Statistics Tracking

### Listening History (`HistoryService`)
- **Module**: [app/services/history.py](file:///home/hisham/projects/music-rec/app/services/history.py)
- **Table**: `listening_history` (`song_id` PK/FK, `play_count`, `skips`, `likes`, `last_played`, `play_duration`).
- **Methods**:
  - `record_play(song_id, play_duration, session)`: Increments `play_count`, adds to `play_duration`, updates `last_played` to `utcnow()`.
  - `record_skip(song_id, session)`: Increments `skips` count.
  - `set_like_status(song_id, liked, session)`: Sets `likes = True/False`.

### Playback Session Tracking (`PlaybackSessionService`)
- **Module**: [app/services/playback_session.py](file:///home/hisham/projects/music-rec/app/services/playback_session.py)
- **Table**: `playback_sessions` (`id`, `playlist_id`, `started_at`, `updated_at`, `finished_at`, `current_song_index`, `current_position`, `completed`).
- **Methods**:
  - `start_session(playlist_id, session)`: Creates new active playback session.
  - `update_session_progress(session_id, current_song_index, current_position, session)`: Updates real-time track index and second position.
  - `finish_session(session_id, completed, session)`: Marks session completed and records `finished_at`.
  - `get_recently_played_playlists(limit, session)`: Aggregates playlist statistics (`play_count`, `last_played_at`) for Home view.

---

## 4. Multi-Resolution Artwork Service (`PlaylistArtworkService`)

- **Module**: [app/services/playlist_artwork.py](file:///home/hisham/projects/music-rec/app/services/playlist_artwork.py)
- **Purpose**: Generates high-quality composite album artwork for playlists.
- **Workflow**:
  1. Queries all songs belonging to a playlist.
  2. Extracts available cover art bytes (`cover_art` BLOBs).
  3. If 1 cover exists: renders single cover image.
  4. If 2–3 covers exist: generates $2 \times 2$ matrix repeating covers.
  5. If 4+ covers exist: extracts first 4 distinct cover arts and constructs a $2 \times 2$ grid composite image using Pillow (`PIL.Image`).
  6. Serves response as JPEG/PNG bytes.
  7. Invalidation: `invalidate_cover(playlist_id)` clears cached artwork whenever songs are added or deleted from a playlist.
