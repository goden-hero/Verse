# Architecture Overview

## 1. Executive Summary

**Verse** (workspace: `music-rec`) is a self-hosted, privacy-first, local AI-powered music recommendation engine and media server. Designed for audiophiles and privacy-conscious users, Verse indexes local music libraries, extracts deep acoustic features and neural audio embeddings, generates rich semantic mood/activity metadata using local Large Language Models (LLMs via Ollama), and powers intelligent search, multi-strategy recommendations, and conversational playlist curation.

Unlike cloud-dependent music services, Verse operates **100% offline and locally**, storing all metadata, indices, listening history, and vector embeddings on the user's filesystem.

---

## 2. System Goals & Core Features

### Primary Goals
1. **Zero Cloud Dependency & Absolute Privacy**: All audio analysis, feature extraction, similarity indexing, database storage, and LLM inference run entirely on local compute.
2. **Deep Audio Understanding**: Go beyond static text tags by combining traditional Music Information Retrieval (MIR) spectral features with 512-dimensional deep neural embeddings (OpenL3 or deterministic random projection fallback).
3. **Conversational Curation**: Translate complex natural language user requests ("Create a rainy evening playlist with low energy and acoustic vibes") into validated execution plans.
4. **Dual Interface Accessibility**: Provide both a rich, hardware-accelerated PySide6 desktop GUI and a lightweight, responsive Web Single Page Application (SPA) served via FastAPI.

### Primary Features
- **Recursive Audio Library Indexing**: Auto-detects MP3, FLAC, M4A, OGG, and WAV files using Mutagen and `ffprobe`. Computes SHA-256 file hashes to deduplicate files and preserve user state across renames.
- **Acoustic & Technical Metadata Extraction**: Measures sample rate, bitrate, codec, bit depth, channel count, BPM, STFT chromagrams, MFCCs, spectral centroids, spectral contrast, RMS energy, zero-crossing rate, and estimates musical keys using the Krumhansl-Schmuckler algorithm.
- **512-Dimensional Vector Similarity Search**: Powered by FAISS C++ bindings using Inner Product search on L2 unit-normalized embeddings (equivalent to Cosine Similarity).
- **Local LLM Semantic Enrichment**: Generates JSON-structured semantic tags (moods, activities, themes, descriptors, energy level, vocal style, language) using local Ollama models (`mistral`, `llama3`, `gemma`).
- **MusicBrainz Integration**: Enriches missing release years, canonical album names, and canonical artist metadata via MusicBrainz Web Services API with built-in rate-limiting and negative hit caching.
- **Multi-Strategy Recommendation Engine**:
  - **Vector Strategy**: FAISS-based 512d neural similarity.
  - **Content Strategy**: Classical MIR statistical pipeline (StandardScaler + PCA + 32d FAISS index).
  - **Hybrid Strategy**: Weighted linear score fusion of underlying strategies.
  - **Automatic Strategy**: Dynamic fallback selector based on index availability.
- **Conversational AI Assistant**: LLM-powered natural language prompt parser (`LLMParser`), Pydantic schema validator (`Planner`), step executor (`Executor`), error-aware self-correction loop, SQLite prompt response caching (`LLMCache`), and creative playlist title generation.
- **Full Playback & Session Tracking**: Cross-platform playback, listening history tracking (play counts, skips, likes, durations), active/historical playback session logging (`PlaybackSession`), and multi-resolution mosaic artwork rendering (`PlaylistArtworkService`).

---

## 3. Technology Stack

| Layer | Component | Technologies Used |
| :--- | :--- | :--- |
| **Desktop Client** | PySide6 | Python 3.13, PySide6 (Qt for Python), `QThread`, `QTabWidget` |
| **Web Client** | Vanilla SPA | HTML5, CSS3 (Modern dark-mode design system), ES6 JavaScript |
| **API Layer** | FastAPI | FastAPI, Uvicorn ASGI server, Pydantic v2, CORS middleware |
| **Service Layer** | Python Services | Decoupled Service-Oriented Architecture (`app/services`) |
| **Audio Processing** | MIR & Tagging | Mutagen, `ffprobe` (subprocess), `librosa`, NumPy, SciPy |
| **Vector Engine** | FAISS | `faiss-cpu` (Inner Product on L2-normalized 512d vectors) |
| **Embeddings** | OpenL3 / Projection | OpenL3 (Keras/TensorFlow) with 512d fixed Random Projection fallback |
| **AI / LLM** | Local LLM | Ollama HTTP API (`http://localhost:11434`), `requests` |
| **Database** | SQLite + SQLAlchemy | SQLite 3, SQLAlchemy 2.0 ORM, Alembic migrations |
| **Configuration** | Settings & CLI | Pydantic / Dataclasses, `python-dotenv`, `argparse` |

---

## 4. High-Level Architecture Diagram

```mermaid
graph TD
    subgraph Client Layer
        GUI["Desktop UI (PySide6 QMainWindow)"]
        WEB["Web UI (Vanilla JS / HTML / CSS)"]
        CLI["Command Line Interface (app/main.py)"]
    end

    subgraph Adapters & Routing
        API["FastAPI HTTP Server (app/api/server.py)"]
        WRK["QThread Workers (app/ui/workers.py)"]
    end

    subgraph Service Layer (app/services)
        LS["LibraryService"]
        SS["SearchService"]
        RS["RecommendationService"]
        PS["PlaylistService"]
        AS["AssistantService"]
        PBS["PlaybackService"]
        HS["HistoryService"]
        PSS["PlaybackSessionService"]
        PAS["PlaylistArtworkService"]
    end

    subgraph AI & Recommendation Subsystems
        AIP["AI Assistant (app/assistant)"]
        REC["Recommendation Engines (app/recommendations)"]
        OLL["Ollama Local LLM Service"]
    end

    subgraph Indexing & Analysis Pipeline
        MUT["Mutagen Tag Extractor"]
        FFP["ffprobe Technical Analyzer"]
        LIB["librosa Feature Extractor"]
        EMB["OpenL3 / Projection Generator"]
    end

    subgraph Data & Storage Layer
        FAS["FAISS Vector Indices (vector_index.bin & content_index.bin)"]
        SQL["SQLite Database (music_rec.db)"]
        ENV[".env Configuration & Settings"]
    end

    GUI --> WRK
    WRK --> LS
    WRK --> RS
    WRK --> AIP

    WEB --> API
    API --> LS
    API --> SS
    API --> RS
    API --> PS
    API --> AS
    API --> PBS

    CLI --> LS
    CLI --> AIP
    CLI --> ENV

    AS --> AIP
    AIP --> OLL
    AIP --> PS
    AIP --> SS
    AIP --> RS

    PS --> SS
    PS --> RS
    RS --> REC
    REC --> FAS
    REC --> SQL

    LS --> MUT
    LS --> FFP
    LS --> LIB
    LS --> EMB
    EMB --> FAS
    LS --> SQL

    SS --> SQL
    SS --> FAS
    PBS --> HS
    PBS --> PSS
    HS --> SQL
    PSS --> SQL
```

---

## 5. Architectural Design Principles

1. **Strict Service Decoupling**: Database logic, recommendation math, and AI parsing are encapsulated entirely within the Service Layer (`app/services`). Neither the FastAPI routes nor the PySide6 UI components contain business logic or direct database queries.
2. **Graceful Fallback & Degradation**:
   - If OpenL3 is unavailable, the system seamlessly uses a 512d fixed random projection fallback.
   - If Ollama is offline or unconfigured, search and recommendations continue to function using metadata and vector similarity.
   - If MusicBrainz network queries fail, local file tags are used exclusively.
3. **Deterministic Memory & Performance Guardrails**: Audio analysis operates strictly on the first 60 seconds (`max_duration=60.0`) downsampled to 22,050 Hz mono to bound RAM usage during bulk indexing.
4. **Idempotent File Scanning**: SHA-256 hashing ensures files moved or renamed are reconciled without losing user history or re-triggering expensive neural embedding generation.
