# Complete System Architecture

This document breaks down the Verse system into its logical subsystems. For each subsystem, we document its purpose, responsibilities, public interfaces, dependencies, internal workflows, extension points, and architectural limitations.

---

## Subsystem Index

1. [Music Library Subsystem](#1-music-library-subsystem)
2. [Folder Scanning & Indexing Pipeline](#2-folder-scanning--indexing-pipeline)
3. [Metadata Extraction Subsystem](#3-metadata-extraction-subsystem)
4. [Technical Audio Property Extractor](#4-technical-audio-property-extractor)
5. [Acoustic Feature Extractor](#5-acoustic-feature-extractor)
6. [Embedding Generation Engine](#6-embedding-generation-engine)
7. [MusicBrainz Metadata Enrichment](#7-musicbrainz-metadata-enrichment)
8. [LLM Semantic Enrichment Engine](#8-llm-semantic-enrichment-engine)
9. [FAISS Similarity Search Index](#9-faiss-similarity-search-index)
10. [Multi-Strategy Recommendation Engine](#10-multi-strategy-recommendation-engine)
11. [Search Subsystem](#11-search-subsystem)
12. [Playlist Management Engine](#12-playlist-management-engine)
13. [Playback & Session Manager](#13-playback--session-manager)
14. [Listening History Tracker](#14-listening-history-tracker)
15. [AI Assistant Subsystem](#15-ai-assistant-subsystem)
16. [Database & Persistence Layer](#16-database--persistence-layer)
17. [FastAPI Web Backend](#17-fastapi-web-backend)
18. [PySide6 Desktop Application](#18-pyside6-desktop-application)

---

## 1. Music Library Subsystem

- **Purpose**: Acts as the central CRUD registry for all audio assets in the system.
- **Responsibilities**: Manages database lifecycle for songs, lookup by title/artist/hash, and triggers library scans.
- **Public Interface**: `app.services.library.LibraryService`
  - `get_songs(session, offset, limit, search, genre, mood, sort_by)`
  - `get_song_by_id(song_id, session)`
  - `get_song_by_title(title, session)`
  - `scan_library(folder_path, session)`
- **Dependencies**: SQLAlchemy models ([Song](file:///home/hisham/projects/music-rec/app/database/models.py#L14-L52)), `app.indexing.scanner`.
- **Internal Workflow**: Accepts path requests, verifies file existence, delegates to scanning pipeline, and commits song records.
- **Extension Points**: Can be extended to support virtual cloud mounts or remote folder watching.
- **Limitations**: Deleting a song requires database cascade deletion. Physical file deletes on disk must be synchronized via scanning.

---

## 2. Folder Scanning & Indexing Pipeline

- **Purpose**: Recursively discovers audio files on the filesystem and orchestrates full metadata/feature extraction pipelines.
- **Responsibilities**: Filters supported extensions (`.mp3`, `.flac`, `.wav`, `.m4a`, `.ogg`), ignores hidden folders (`.git`, `.venv`), computes SHA-256 file hashes, detects modified files, and populates database records and FAISS indices.
- **Public Interface**:
  - `app.indexing.scanner.scan_music_folder(folder: Path) -> list[Path]`
  - `app.ui.workers.ScanWorker(folder_path, vector_index_path)`
- **Dependencies**: Mutagen, `ffprobe`, `librosa`, OpenL3 / Projection generator, FAISS, SQLAlchemy session.
- **Internal Workflow**:
  ```mermaid
  sequenceDiagram
      autonumber
      participant Worker as ScanWorker / CLI
      participant Scanner as Scanner Utility
      participant DB as SQLite DB
      participant Ext as Extractors
      participant Index as FAISS & Content Index

      Worker->>Scanner: scan_music_folder(path)
      Scanner-->>Worker: List[Path] of audio files
      loop For each audio file
          Worker->>Worker: compute_file_hash(file)
          Worker->>DB: Check existing Song by path and hash
          alt File unchanged
              Worker->>Worker: Skip indexing
          else File changed or new
              Worker->>Ext: extract_metadata(file)
              Worker->>Ext: extract_technical_metadata(file)
              Worker->>Ext: extract_features(file)
              Worker->>Ext: generate_embedding(features, file)
              Worker->>DB: Insert Song, Technical, Features, Embeddings
          end
      end
      Worker->>Index: Rebuild FAISS 512d Index
      Worker->>Index: Rebuild Classical MIR Content Index
  ```
- **Limitations**: Single-threaded linear extraction during scan; large libraries (>10,000 songs) take noticeable time.

---

## 3. Metadata Extraction Subsystem

- **Purpose**: Reads embedded ID3, FLAC, MP4/M4A, Vorbis Comments, and RIFF tags from audio files.
- **Responsibilities**: Extracts title, artist, album, album artist, genre, release year, track number, disc number, duration, and embedded cover art bytes (`APIC`, `covr`, `metadata_block_picture`).
- **Public Interface**: `app.metadata.extractor.extract_metadata(file: Path) -> SongMetadata`
- **Dependencies**: `mutagen`, `base64`.
- **Internal Workflow**: Uses Mutagen dispatching (`MP3`, `FLAC`, `MP4`, `OggVorbis`, `WAVE`), with safe string/integer cleanups.
- **Limitations**: Non-standard or corrupt ID3 frames are safely ignored, defaulting to filename stem for song title.

---

## 4. Technical Audio Property Extractor

- **Purpose**: Extracts low-level audio engineering specs.
- **Responsibilities**: Spawns `ffprobe` as a subprocess to parse stream format, codec name, audio bitrate, sample rate (Hz), channel count (mono/stereo/surround), bit depth, and container format.
- **Public Interface**: `app.metadata.technical.extract_technical_metadata(file: Path) -> TechnicalMetadataInfo`
- **Dependencies**: System `ffprobe` executable (5-second execution timeout).
- **Internal Workflow**: Executes `ffprobe -v error -select_streams a:0 -show_entries ... -of json <file>` and parses stdout.

---

## 5. Acoustic Feature Extractor

- **Purpose**: Computes DSP acoustic features for Content recommendations and Key estimation.
- **Responsibilities**: Loads the first 60 seconds of audio at 22,050 Hz mono. Extracts BPM, 12-dim STFT Chromagram, 13-dim MFCCs, Spectral Centroid, Spectral Contrast, RMS Energy, Zero Crossing Rate, and estimates key using the Krumhansl-Schmuckler pitch profiles.
- **Public Interface**:
  - `app.features.extractor.extract_features(file_path: Path, max_duration=60.0) -> AudioFeaturesInfo`
  - `app.features.extractor.estimate_key_from_chroma(chroma_mean: np.ndarray) -> str`
- **Dependencies**: `librosa`, `numpy`, `pickle`.

---

## 6. Embedding Generation Engine

- **Purpose**: Generates high-dimensional vector representations of songs for semantic/vibe similarity search.
- **Responsibilities**: Queries OpenL3 deep neural network (512-dim music embedding). If OpenL3 is unavailable, generates a deterministic 512-dim embedding using statistical feature concatenation + L2-normalized Gaussian random projection matrix (fixed seed `42`).
- **Public Interface**:
  - `app.embeddings.generator.generate_embedding(info: AudioFeaturesInfo, file_path: Path | None) -> list[float]`
  - `app.embeddings.generator.generate_fallback_embedding(info: AudioFeaturesInfo) -> list[float]`
- **Dependencies**: `openl3` (optional), `numpy`, `pickle`.

---

## 7. MusicBrainz Metadata Enrichment

- **Purpose**: Enhances local tags with canonical metadata from the MusicBrainz global database.
- **Responsibilities**: Queries MusicBrainz Web Service API (`https://musicbrainz.org/ws/2/recording`), parses best recording match, extracts canonical artist/album/release year/popular tag genre, and caches negative hits (`musicbrainz_id = "NOT_FOUND"`).
- **Public Interface**: `app.metadata.enrichment.enrich_song_metadata(song_id, title, artist, db_session) -> bool`
- **Dependencies**: `requests`, SQLAlchemy session.
- **Invariants**: Enforces a strict 1.0-second delay between requests (`_rate_limit()`) per MusicBrainz terms of service.

---

## 8. LLM Semantic Enrichment Engine

- **Purpose**: Uses a local LLM to tag songs with rich semantic descriptors (moods, activities, themes, instruments, energy level, vocal style, language).
- **Responsibilities**: Gathers metadata context (title, artist, album, genre, BPM, key, year, duration), constructs JSON schema enforcement prompt, queries local Ollama instance, validates schema, applies placeholder filter sanitization, regex repairs malformed JSON, and saves to `semantic_tags` table.
- **Public Interface**:
  - `app.metadata.semantic.OllamaClient.generate_tags(song_info: dict) -> dict | None`
  - `app.metadata.semantic.enrich_song_semantics(song_id, db_session, force_refresh, client)`
- **Dependencies**: Local Ollama server (`http://localhost:11434`), `requests`.

---

## 9. FAISS Similarity Search Index

- **Purpose**: Provides ultra-fast vector similarity lookup over song embeddings.
- **Responsibilities**: Manages C++ FAISS `IndexFlatIP` wrapped in `IndexIDMap` (Inner Product search on L2-normalized 512-dim vectors = Cosine Similarity). Handles load/save to disk (`vector_index.bin` and `content_index.bin`), vector insertion with database primary key mapping, deletion by ID, and $k$-NN search.
- **Public Interface**: `app.search.index.FAISSIndex(index_path: Path, dim: int = 512)`
  - `load() -> bool`, `save() -> bool`
  - `add_songs(song_ids: list[int], embeddings: list[list[float]])`
  - `remove_songs(song_ids: list[int])`
  - `search(query_embedding: list[float], k: int) -> list[tuple[int, float]]`
- **Dependencies**: `faiss-cpu`, `numpy`.

---

## 10. Multi-Strategy Recommendation Engine

- **Purpose**: Powers recommendation tabs, automatic mixes, and AI assistant playlist generation.
- **Responsibilities**: Implements Strategy Pattern (`BaseRecommender`). Provides:
  - `VectorRecommender`: FAISS 512d neural similarity.
  - `ContentRecommender`: Classical MIR statistical feature pipeline (StandardScaler + PCA down to 32d FAISS index).
  - `HybridRecommender`: Normalized linear weighted score fusion of underlying recommenders.
  - `Recommender Registry`: Global strategy registry (`get_recommender(strategy_name)`).
  - `Strategy Selector`: Auto-selects best available strategy (`automatic`).
- **Public Interface**: `app.recommendations.registry.get_recommender(name: str)`

---

## 11. Search Subsystem

- **Purpose**: Unified search engine supporting text matching, vector similarity, and semantic tag filtering.
- **Responsibilities**: Ranked metadata text search (exact title match > title prefix > title substring > exact artist > artist substring), synonym expansion for mood/activity tags, FAISS vector search, and semantic energy filtering.
- **Public Interface**: `app.services.search.SearchService`
  - `ranked_metadata_search(query, session)`
  - `metadata_search(query, session)`
  - `vector_search(query_song_title, session, k)`
  - `semantic_search(moods, activities, energy_min, energy_max, session)`

---

## 12. Playlist Management Engine

- **Purpose**: Manages manual and AI-generated playlists, candidate retrieval, confidence scoring, and shortfall feedback.
- **Responsibilities**: Handles playlist CRUD, position ordering (`playlist_songs`), candidate retrieval (`_retrieve_initial_candidates`), recommendation expansion (`_expand_candidates_from_recommendations`), candidate scoring & semantic validation (`_score_candidate_confidence`), artist diversity re-ranking (`_rank_candidates`), confidence thresholding (`_apply_confidence_threshold`), shortfall reason generation (`_build_shortfall_metadata`), and LLM-assisted creative playlist title generation.
- **Public Interface**: `app.services.playlist.PlaylistService`

---

## 13. Playback & Session Manager

- **Purpose**: Coordinates playback state across UIs and tracks active playback sessions.
- **Responsibilities**: Registers active UI playback handler (`register_handler`), manages playback queue, pause/resume/skip, toggles repeat/shuffle, logs playback start/completion events (`PlaybackSessionService`), and generates multi-cover mosaic artwork (`PlaylistArtworkService`).
- **Public Interface**: `app.services.playback.PlaybackService`

---

## 14. Listening History Tracker

- **Purpose**: Maintains persistent stats on user listening behavior.
- **Responsibilities**: Records play events (increments play count, updates play duration, updates last played timestamp), records skips, and toggles like/favorite status in `listening_history` table.
- **Public Interface**: `app.services.history.HistoryService`

---

## 15. AI Assistant Subsystem

- **Purpose**: Translates natural language prompts into executable actions and structured playlist previews.
- **Responsibilities**:
  - `LLMParser`: Formats system prompt, checks Ollama health & model installation, preloads model into memory, sends request, parses JSON response, triggers error-aware retry loop if schema fails validation, logs structured timing/token metrics, caches valid responses in `LLMCache`, and generates creative titles.
  - `Planner`: Validates parsed dictionaries into Pydantic `ActionPlan` models.
  - `Executor`: Executes `ActionPlan` steps sequentially against the Service Layer (`SearchService`, `RecommendationService`, `PlaylistService`, `PlaybackService`, `HistoryService`).
  - `AssistantHistoryManager`: Persists conversation history in `assistant_history` table.
- **Public Interface**: `app.services.assistant.AssistantService`

---

## 16. Database & Persistence Layer

- **Purpose**: Thread-safe database connection and ORM mapping.
- **Responsibilities**: Manages SQLite engine with `check_same_thread=False`, sets `PRAGMA foreign_keys=ON` on connection, provides scoped thread-local sessions (`SessionLocal`), context manager `get_session()`, schema initialization (`init_db()`), and Alembic migration compatibility.
- **Public Interface**: `app.database.connection` (`engine`, `get_session()`, `init_db()`)

---

## 17. FastAPI Web Backend

- **Purpose**: HTTP API adapter layer for the Web SPA.
- **Responsibilities**: Exposes REST endpoints (`/api/v1/songs`, `/api/v1/search`, `/api/v1/playlists`, `/api/v1/playback`, `/api/v1/assistant`), manages dependency injection (`get_db`), configures CORS, and mounts Web SPA static assets (`app/web`).
- **Public Interface**: `app.api.server.app`

---

## 18. PySide6 Desktop Application

- **Purpose**: Native PySide6 desktop client interface.
- **Responsibilities**: Implements tabbed layout (`LibraryTab`, `NowPlayingTab`, `RecommendationsTab`, `PlaylistsTab`, `SearchTab`, `AssistantTab`, `SettingsTab`), background `QThread` workers (`ScanWorker`, `RecommendWorker`, `AssistantWorker`), Qt signals, and registers global playback handler.
- **Public Interface**: `app.ui.main_window.MainWindow`
