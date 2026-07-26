# Database Schema & Entity-Relationship Documentation

This document documents the relational database schema for Verse (`music_rec.db`), including entity relationships, indices, constraint enforcement, and cascade rules.

---

## 1. Entity-Relationship Diagram (ERD)

```mermaid
erDiagram
    songs ||--o| technical_metadata : "has 1:1"
    songs ||--o| audio_features : "has 1:1"
    songs ||--o| musicbrainz_metadata : "has 1:1"
    songs ||--o| embeddings : "has 1:1"
    songs ||--o| semantic_tags : "has 1:1"
    songs ||--o| listening_history : "has 1:1"
    songs ||--o{ playlist_songs : "appears in 1:N"

    playlists ||--o{ playlist_songs : "contains 1:N"
    playlists ||--o| songs : "optional seed_song_id"
    playlists ||--o{ playback_sessions : "has 1:N"

    assistant_history {
        int id PK
        datetime timestamp
        string prompt
        string plan
        string result
    }

    llm_cache {
        string prompt_hash PK
        string response
        datetime created_at
    }

    songs {
        int id PK
        string path UK
        string hash UK
        string title
        string artist
        string album
        float duration
        string original_genre
        blob cover_art
    }

    technical_metadata {
        int song_id PK, FK
        string codec
        int bitrate
        int sample_rate
        int channels
        int bit_depth
        string format
    }

    audio_features {
        int song_id PK, FK
        float bpm
        blob chroma
        blob mfcc
        blob spectral_centroid
        blob spectral_contrast
        blob rms
        blob zero_crossing_rate
        string key_estimation
    }

    musicbrainz_metadata {
        int song_id PK, FK
        string canonical_artist
        string canonical_album
        int release_year
        string canonical_genre
        string musicbrainz_id
    }

    embeddings {
        int song_id PK, FK
        blob vector
    }

    semantic_tags {
        int song_id PK, FK
        string moods
        string activities
        string themes
        string descriptors
        string energy
        string vocal_style
        string language
    }

    listening_history {
        int song_id PK, FK
        int play_count
        int skips
        boolean likes
        datetime last_played
        float play_duration
    }

    playlists {
        int id PK
        string name
        string description
        datetime created_at
        datetime updated_at
        string prompt
        string strategy
        string seed_type
        int seed_song_id FK
        string generated_by
        string generator_version
        string llm_model
        string created_from
    }

    playlist_songs {
        int playlist_id PK, FK
        int song_id PK, FK
        int position
    }

    playback_sessions {
        int id PK
        int playlist_id FK
        datetime started_at
        datetime updated_at
        datetime finished_at
        int current_song_index
        float current_position
        boolean completed
    }
```

---

## 2. Table Specifications & Indexes

### A. Core Library Table: `songs`
- Stores primary metadata and unique file identities.
- **Indexes**:
  - `sqlite_autoindex_songs_1`: `path` UNIQUE INDEX
  - `sqlite_autoindex_songs_2`: `hash` UNIQUE INDEX

### B. Subordinate 1:1 Metadata Tables
All subordinate song metadata tables store `song_id` as both Primary Key and Foreign Key referencing `songs.id` with `ON DELETE CASCADE`:
- **`technical_metadata`**: `codec`, `bitrate`, `sample_rate`, `channels`, `bit_depth`, `format`.
- **`audio_features`**: `bpm`, `chroma` (BLOB), `mfcc` (BLOB), `spectral_centroid` (BLOB), `spectral_contrast` (BLOB), `rms` (BLOB), `zero_crossing_rate` (BLOB), `key_estimation`.
- **`musicbrainz_metadata`**: `canonical_artist`, `canonical_album`, `release_year`, `canonical_genre`, `musicbrainz_id`.
- **`embeddings`**: `vector` (Pickled float list BLOB).
- **`semantic_tags`**: `moods` (JSON string array), `activities` (JSON string array), `themes` (JSON string array), `descriptors` (JSON string array), `energy` (`low`/`medium`/`high`), `vocal_style`, `language`.
- **`listening_history`**: `play_count` (default: 0), `skips` (default: 0), `likes` (default: false), `last_played`, `play_duration` (default: 0.0).

### C. Playlist Tables
- **`playlists`**: `id` (PK autoincrement), `name`, `description`, `created_at`, `updated_at`, `prompt`, `strategy`, `seed_type`, `seed_song_id` (FK to `songs.id ON DELETE SET NULL`), `generated_by` (`MANUAL`/`AI`/`HYBRID`), `generator_version`, `llm_model`, `created_from`.
- **`playlist_songs`**: Composite PK `(playlist_id, song_id)`. `playlist_id` (FK `playlists.id ON DELETE CASCADE`), `song_id` (FK `songs.id ON DELETE CASCADE`), `position` (int).

### D. Playback & Session Tables
- **`playback_sessions`**: `id` (PK autoincrement), `playlist_id` (FK `playlists.id ON DELETE CASCADE`, indexed), `started_at`, `updated_at`, `finished_at`, `current_song_index`, `current_position`, `completed`.
- **Index**: `idx_playback_sessions_playlist_id` on `playlist_id`.

### E. AI System Tables
- **`assistant_history`**: `id` (PK autoincrement), `timestamp`, `prompt`, `plan` (JSON string), `result` (JSON string).
- **`llm_cache`**: `prompt_hash` (PK string), `response` (JSON string), `created_at`.

---

## 3. SQLite Connection Settings & Pragma Rules

SQLite requires explicit PRAGMA configuration to enforce relational invariants:
```python
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()
```
- **`PRAGMA foreign_keys=ON`**: Mandated on every new connection so that deleting a `Song` or `Playlist` automatically triggers database cascade deletions across all dependent metadata tables.
