# Database Models Documentation

This document details the SQLAlchemy 2.0 ORM model definitions ([app/database/models.py](file:///home/hisham/projects/music-rec/app/database/models.py)) in Verse, detailing entity responsibilities, relationships, cascades, and ownership permissions.

---

## 1. ORM Model Classes Catalog

### A. `Song` Model
- **Module**: [app/database/models.py](file:///home/hisham/projects/music-rec/app/database/models.py#L14-L52)
- **Table**: `songs`
- **Purpose**: Core entity representing a track in the user's music library.
- **Attributes**:
  - `id: Mapped[int]` (Primary Key, autoincrement)
  - `path: Mapped[str]` (Unique, indexed, non-nullable)
  - `hash: Mapped[str]` (Unique, indexed, non-nullable, SHA-256)
  - `title: Mapped[str | None]`
  - `artist: Mapped[str | None]`
  - `album: Mapped[str | None]`
  - `duration: Mapped[float | None]`
  - `original_genre: Mapped[str | None]`
  - `cover_art: Mapped[bytes | None]` (LargeBinary)
- **Relationships**:
  - `technical_metadata`: 1:1 relationship with `TechnicalMetadata` (`cascade="all, delete-orphan"`, `uselist=False`)
  - `audio_features`: 1:1 relationship with `AudioFeatures` (`cascade="all, delete-orphan"`, `uselist=False`)
  - `musicbrainz_metadata`: 1:1 relationship with `MusicBrainzMetadata` (`cascade="all, delete-orphan"`, `uselist=False`)
  - `embeddings`: 1:1 relationship with `Embeddings` (`cascade="all, delete-orphan"`, `uselist=False`)
  - `semantic_tags`: 1:1 relationship with `SemanticTags` (`cascade="all, delete-orphan"`, `uselist=False`)
  - `listening_history`: 1:1 relationship with `ListeningHistory` (`cascade="all, delete-orphan"`, `uselist=False`)
- **Write Ownership**: `LibraryService` & `ScanWorker`.
- **Read Ownership**: All services & UI components.

---

### B. `TechnicalMetadata` Model
- **Table**: `technical_metadata`
- **Purpose**: Low-level audio file properties extracted via `ffprobe`.
- **Attributes**: `song_id` (PK, FK `songs.id ON DELETE CASCADE`), `codec`, `bitrate`, `sample_rate`, `channels`, `bit_depth`, `format`.
- **Write Ownership**: `ScanWorker`.

---

### C. `AudioFeatures` Model
- **Table**: `audio_features`
- **Purpose**: Acoustic features computed via `librosa`.
- **Attributes**: `song_id` (PK, FK `songs.id ON DELETE CASCADE`), `bpm`, `chroma` (BLOB), `mfcc` (BLOB), `spectral_centroid` (BLOB), `spectral_contrast` (BLOB), `rms` (BLOB), `zero_crossing_rate` (BLOB), `key_estimation`.
- **Write Ownership**: `ScanWorker`.

---

### D. `MusicBrainzMetadata` Model
- **Table**: `musicbrainz_metadata`
- **Purpose**: MusicBrainz global recording enrichment data.
- **Attributes**: `song_id` (PK, FK `songs.id ON DELETE CASCADE`), `canonical_artist`, `canonical_album`, `release_year`, `canonical_genre`, `musicbrainz_id`.
- **Write Ownership**: `enrich_song_metadata()`.

---

### E. `Embeddings` Model
- **Table**: `embeddings`
- **Purpose**: Pickled vector embeddings used by vector search.
- **Attributes**: `song_id` (PK, FK `songs.id ON DELETE CASCADE`), `vector` (Pickled float list BLOB).
- **Write Ownership**: `ScanWorker`.

---

### F. `SemanticTags` Model
- **Table**: `semantic_tags`
- **Purpose**: Ollama-generated high-level mood/activity/theme descriptors.
- **Attributes**: `song_id` (PK, FK `songs.id ON DELETE CASCADE`), `moods` (JSON list string), `activities` (JSON list string), `themes` (JSON list string), `descriptors` (JSON list string), `energy` (`low`/`medium`/`high`), `vocal_style`, `language`.
- **Write Ownership**: `enrich_song_semantics()`.

---

### G. `ListeningHistory` Model
- **Table**: `listening_history`
- **Purpose**: Local user listening statistics and favorites.
- **Attributes**: `song_id` (PK, FK `songs.id ON DELETE CASCADE`), `play_count` (int, default=0), `skips` (int, default=0), `likes` (bool, default=False), `last_played` (datetime), `play_duration` (float, default=0.0).
- **Write Ownership**: `HistoryService`.

---

### H. `Playlist` Model
- **Table**: `playlists`
- **Purpose**: Manual or AI-generated playlists.
- **Attributes**: `id` (PK autoincrement), `name`, `description`, `created_at`, `updated_at`, `prompt`, `strategy`, `seed_type`, `seed_song_id` (FK `songs.id ON DELETE SET NULL`), `generated_by` (`MANUAL`/`AI`/`HYBRID`), `generator_version`, `llm_model`, `created_from`.
- **Relationships**:
  - `songs`: 1:N ordered list of `PlaylistSong` (`cascade="all, delete-orphan"`, `order_by="PlaylistSong.position"`)
  - `seed_song`: FK relationship to `Song`
  - `sessions`: 1:N list of `PlaybackSession` (`cascade="all, delete-orphan"`)
- **Write Ownership**: `PlaylistService`.

---

### I. `PlaylistSong` Model
- **Table**: `playlist_songs`
- **Purpose**: Associative model linking songs to playlists with positional ordering.
- **Attributes**: `playlist_id` (PK, FK `playlists.id ON DELETE CASCADE`), `song_id` (PK, FK `songs.id ON DELETE CASCADE`), `position` (int).
- **Write Ownership**: `PlaylistService`.

---

### J. `PlaybackSession` Model
- **Table**: `playback_sessions`
- **Purpose**: Active and historical playlist playback sessions.
- **Attributes**: `id` (PK autoincrement), `playlist_id` (FK `playlists.id ON DELETE CASCADE`), `started_at`, `updated_at`, `finished_at`, `current_song_index`, `current_position`, `completed` (bool).
- **Write Ownership**: `PlaybackSessionService`.

---

### K. `AssistantHistory` Model
- **Table**: `assistant_history`
- **Purpose**: Log of conversational AI prompts and outputs.
- **Attributes**: `id` (PK autoincrement), `timestamp`, `prompt`, `plan` (JSON string), `result` (JSON string).
- **Write Ownership**: `AssistantHistoryManager`.

---

### L. `LLMCache` Model
- **Table**: `llm_cache`
- **Purpose**: SQLite prompt response cache.
- **Attributes**: `prompt_hash` (PK string), `response` (JSON string), `created_at`.
- **Write Ownership**: `LLMCacheManager`.

---

## 2. Invariants & Modification Guidelines

1. **Cascade Safety**: Never delete a record in subordinate tables manually. Deleting a `Song` automatically cleans up all associated metadata, embeddings, features, history, and playlist song entries.
2. **Session Thread Safety**: Always acquire a session via `get_session()` context manager in worker threads or API dependencies. Never share SQLAlchemy session instances across thread boundaries.
