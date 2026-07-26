# Request Lifecycles & Sequence Diagrams

This document details the complete end-to-end execution lifecycles for major operations in Verse.

---

## Lifecycle Index

1. [AI Assistant Request Lifecycle ("Create a rainy evening playlist")](#1-ai-assistant-request-lifecycle)
2. [Music Library Scanning Lifecycle](#2-music-library-scanning-lifecycle)
3. [Metadata Search Lifecycle](#3-metadata-search-lifecycle)
4. [Semantic Tag Enrichment Lifecycle](#4-semantic-tag-enrichment-lifecycle)
5. [Playlist Creation & Persistence Lifecycle](#5-playlist-creation--persistence-lifecycle)
6. [Playback & Listening History Lifecycle](#6-playback--listening-history-lifecycle)
7. [Web HTTP REST Request Lifecycle](#7-web-http-rest-request-lifecycle)
8. [Desktop PySide6 Worker Lifecycle](#8-desktop-pyside6-worker-lifecycle)

---

## 1. AI Assistant Request Lifecycle

Example User Input: `"Create a rainy evening playlist"`

### High-Level Stage Sequence
```text
User Types Prompt -> LLM Parser (Ollama Health + Preload + JSON Generation) -> SQLite Cache Check -> Schema Validation (Planner / Pydantic ActionPlan) -> Executor -> Service Layer Orchestration -> Dynamic Candidate Retrieval -> Semantic Filtering & Confidence Scoring -> Diversity Re-ranking -> LLM Playlist Naming -> Response Returned to UI
```

### Detailed Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Desktop UI / Web SPA
    participant AS as AssistantService / AssistantWorker
    participant Parser as LLMParser (app/assistant/parser.py)
    participant Cache as LLMCacheManager (SQLite llm_cache)
    participant Ollama as Local Ollama Service
    participant Plan as Planner / Pydantic ActionPlan
    participant Exec as Executor (app/assistant/executor.py)
    participant PS as PlaylistService
    participant RS as RecommendationService
    participant SS as SearchService
    participant DB as SQLite DB

    User->>UI: Enter prompt: "Create a rainy evening playlist"
    UI->>AS: process_chat("Create a rainy evening playlist")
    AS->>Parser: parse_intent("Create a rainy evening playlist", session)
    
    Parser->>Cache: get_cached_response(prompt_hash)
    alt Cache Hit
        Cache-->>Parser: Cached JSON string
    else Cache Miss
        Parser->>Ollama: GET /api/tags (Check health & model existence)
        Parser->>Ollama: GET /api/ps (Check if model loaded, preload if needed)
        Parser->>Ollama: POST /api/generate (System prompt + User prompt, format="json")
        Ollama-->>Parser: JSON String response
        alt JSON or Schema Error
            Parser->>Ollama: Retry request with error details in system prompt (up to 3 retries)
        end
        Parser->>Cache: cache_response(prompt, response_text)
    end

    Parser-->>AS: Raw plan dict
    AS->>Plan: create_plan(plan_dict)
    Plan-->>AS: Validated ActionPlan model instance
    
    AS->>Exec: execute_plan(action_plan, session)
    loop For each step in ActionPlan
        alt Action: generate_playlist
            Exec->>PS: generate_playlist_preview_details(strategy, filters, target_length, session)
            PS->>SS: semantic_search(moods=["rainy", "evening"], ...)
            SS->>DB: Query semantic_tags matching criteria
            SS-->>PS: Direct matching song records
            PS->>RS: recommend(seed_song_id, strategy="hybrid", limit=40)
            RS-->>PS: Expanded candidate songs
            PS->>PS: Validate candidates semantically against filters
            PS->>PS: Score candidate confidence (C >= 0.85)
            PS->>PS: Re-rank by artist diversity
            PS->>Parser: generate_playlist_name(songs, prompt, filters)
            Parser->>Ollama: POST /api/generate (Creative Title Prompt)
            Ollama-->>Parser: {"title": "Midnight Rain & Neon", "description": "..."}
            PS-->>Exec: Preview dictionary + shortfall metadata
        end
    end

    Exec-->>AS: Result dictionary (success=True, steps=[...])
    AS-->>UI: Conversational response + Playlist Preview object
    UI-->>User: Display assistant message & playlist tracks in UI
```

---

## 2. Music Library Scanning Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Desktop GUI / Web UI / CLI
    participant Worker as ScanWorker (QThread) / CLI Handler
    participant Scanner as scan_music_folder (scanner.py)
    participant Ext as Extractors (mutagen, ffprobe, librosa, OpenL3)
    participant DB as SQLite DB
    participant FAISS as FAISS Index Manager

    User->>UI: Click "Scan Library" / Run `python -m app.main scan /path`
    UI->>Worker: Instantiate & start ScanWorker(folder_path)
    Worker->>Scanner: scan_music_folder(folder_path)
    Scanner-->>Worker: List of resolved audio file Path objects
    
    loop For each audio file
        Worker->>Worker: Compute SHA-256 hash of file content
        Worker->>DB: Query existing Song by path
        alt Song exists & hash matches
            Worker->>Worker: Skip (Unchanged)
        else Song exists & hash differs
            Worker->>DB: Delete existing Song (cascades related records)
        end
        Worker->>Ext: extract_metadata(file) [Mutagen]
        Worker->>Ext: extract_technical_metadata(file) [ffprobe]
        Worker->>Ext: extract_features(file) [librosa]
        Worker->>Ext: generate_embedding(features, file) [OpenL3 / Projection]
        Worker->>DB: Save Song, TechnicalMetadata, AudioFeatures, Embeddings
        Worker->>UI: Emit progress signal (percentage, current file)
    end

    Worker->>FAISS: Rebuild FAISS 512d Index (`vector_index.bin`)
    Worker->>FAISS: Rebuild Classical MIR Content Index (`content_index.bin`)
    Worker->>UI: Emit finished signal (total new/updated songs count)
    UI-->>User: Display scan completion message
```

---

## 3. Metadata Search Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Web SPA / Desktop UI
    participant API as FastAPI Router (/api/v1/search)
    participant Service as SearchService (app/services/search.py)
    participant DB as SQLite DB

    User->>UI: Types query in search bar (e.g. "Radiohead")
    UI->>API: GET /api/v1/search?q=Radiohead
    API->>Service: ranked_metadata_search("Radiohead", session)
    Service->>DB: Query songs WHERE title ILIKE '%Radiohead%' OR artist ILIKE '%Radiohead%'
    DB-->>Service: Unsorted song records
    Service->>Service: Sort songs by rank key:<br/>1. Exact title<br/>2. Title prefix<br/>3. Title substring<br/>4. Exact artist<br/>5. Artist substring
    Service-->>API: List of formatted song dictionaries
    API-->>UI: JSON HTTP 200 Response
    UI-->>User: Render search results table
```

---

## 4. Semantic Tag Enrichment Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor Developer/User
    participant CLI as CLI / Worker
    participant Semantic as enrich_song_semantics (app/metadata/semantic.py)
    participant DB as SQLite DB
    participant Ollama as Local Ollama Service

    Developer/User->>CLI: Run `python -m app.main enrich-semantic`
    CLI->>DB: Query all Song records
    DB-->>CLI: List of songs
    loop For each song
        CLI->>Semantic: enrich_song_semantics(song_id, db_session)
        Semantic->>DB: Check cached SemanticTags
        alt Already cached & not force_refresh
            Semantic-->>CLI: Return True (Cached)
        else Needs enrichment
            Semantic->>DB: Fetch Song, MusicBrainzMetadata, AudioFeatures
            Semantic->>Ollama: POST /api/generate with Context Prompt & JSON Format
            Ollama-->>Semantic: JSON String output
            Semantic->>Semantic: Validate & sanitize keys, regex repair if needed
            Semantic->>DB: Save/Update SemanticTags record
            Semantic-->>CLI: Return True (Successfully Enriched)
        end
    end
```

---

## 5. Playlist Creation & Persistence Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Web UI / Desktop UI
    participant API as FastAPI Router (/api/v1/playlists)
    participant PS as PlaylistService (app/services/playlist.py)
    participant DB as SQLite DB
    participant Art as PlaylistArtworkService

    User->>UI: Submit Create Playlist Form (Strategy, Seed, Limit)
    UI->>API: POST /api/v1/playlists/generate
    API->>PS: generate_playlist(name, strategy, filters, target_length, session)
    PS->>PS: Retrieve candidates & score confidence
    PS->>DB: Insert Playlist record (generated_by="AI")
    PS->>DB: Insert PlaylistSong records with sequential position index
    PS->>Art: invalidate_cover(playlist_id)
    PS-->>API: Generated playlist summary JSON
    API-->>UI: HTTP 200 Response
    UI-->>User: Show new playlist in UI & load details view
```

---

## 6. Playback & Listening History Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Desktop UI / Web SPA
    participant PBS as PlaybackService (app/services/playback.py)
    participant HS as HistoryService (app/services/history.py)
    participant PSS as PlaybackSessionService
    participant DB as SQLite DB

    User->>UI: Click "Play Song" / Click "Play Playlist"
    UI->>PBS: play_song(song_id) / play_playlist(playlist_id)
    PBS->>UI: Dispatch play command to registered UI handler / Audio element
    
    note over UI,PBS: User listens to song for 45 seconds

    User->>UI: Click "Skip" / Song finishes playing
    UI->>PBS: record_play(song_id, duration=45.0)
    PBS->>HS: record_play(song_id, duration=45.0, session)
    HS->>DB: Update listening_history SET play_count = play_count + 1, play_duration = play_duration + 45.0, last_played = NOW()
    
    alt Active Playlist Session
        UI->>PSS: update_session_progress(session_id, current_song_index, current_position)
        PSS->>DB: Update playback_sessions record
    end
```

---

## 7. Web HTTP REST Request Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor Browser
    participant Uvicorn as Uvicorn ASGI Server
    participant FastAPI as FastAPI App (app/api/server.py)
    participant Dep as Dependencies (get_db)
    participant Router as API Router (app/api/routes)
    participant Service as Service Layer
    participant DB as SQLite Session

    Browser->>Uvicorn: HTTP Request (e.g. GET /api/v1/songs?limit=20)
    Uvicorn->>FastAPI: Route matching
    FastAPI->>Dep: Execute get_db() dependency
    Dep->>DB: SessionLocal() opened
    FastAPI->>Router: Forward request & injected DB session
    Router->>Service: LibraryService.get_songs(session, ...)
    Service->>DB: SQLAlchemy Query execution
    DB-->>Service: ORM Model objects
    Service-->>Router: Formatted dict / schema primitives
    Router-->>FastAPI: Return Pydantic response model
    Dep->>DB: session.close()
    FastAPI-->>Uvicorn: Serialized JSON Response + Headers
    Uvicorn-->>Browser: HTTP 200 OK Response
```

---

## 8. Desktop PySide6 Worker Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant MainUI as MainWindow (PySide6 QMainWindow)
    participant Tab as AssistantTab / RecommendationsTab / LibraryTab
    participant Worker as QThread Worker (AssistantWorker / RecommendWorker)
    participant Service as Service Layer

    User->>Tab: Click action button (e.g. Submit Assistant Prompt)
    Tab->>Worker: Instantiate worker thread object
    Tab->>Worker: Connect Qt signals (progress, playlist_generated, finished, error)
    Tab->>Worker: worker.start()
    
    note over Worker: Worker executes in separate OS thread, preventing UI freeze

    Worker->>Service: Call service methods (LLM Parser / Recommendation Engine)
    Worker->>Tab: Emit progress.emit("Parsing intent...", "running")
    Tab->>MainUI: Update UI status indicator
    Worker->>Service: Complete execution
    Worker->>Tab: Emit finished.emit(summary, steps)
    Worker->>Tab: Emit playlist_generated.emit(playlist_data)
    Tab->>MainUI: Render result in tab view & update Now Playing
    Worker->>Worker: Thread terminates cleanly
```
