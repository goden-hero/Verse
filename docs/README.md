# Verse Engineering Handover Documentation

Welcome to the primary engineering reference documentation for **Verse** (workspace: `music-rec`).

This documentation suite reverse-engineers the entire Verse system, explaining its architecture, subsystems, algorithms, data flows, database schemas, AI integrations, API specifications, and extension patterns. It is designed to allow any experienced engineer to quickly gain a deep conceptual and technical understanding of the system and begin contributing immediately.

---

## 📚 Documentation Structure

### 🏛️ Architecture & System Blueprint
- **[Architecture Overview](file:///home/hisham/projects/music-rec/docs/architecture/overview.md)**: High-level overview, goals, target users, technology stack, design philosophy, and system maturity.
- **[System Architecture](file:///home/hisham/projects/music-rec/docs/architecture/system_architecture.md)**: Deep dive into all 18 logical subsystems, ownership boundaries, interfaces, and limitations.
- **[Data Flow Architecture](file:///home/hisham/projects/music-rec/docs/architecture/data_flow.md)**: End-to-end data pipelines from audio files on disk through feature extraction, 512d vector embeddings, FAISS indices, semantic tagging, SQLite, and UI views.
- **[Request Lifecycles](file:///home/hisham/projects/music-rec/docs/architecture/request_lifecycles.md)**: Comprehensive sequence diagrams and step-by-step lifecycles for AI playlist generation, metadata search, scanning, playback, and API requests.
- **[Recommendation Engine](file:///home/hisham/projects/music-rec/docs/architecture/recommendation_engine.md)**: Exhaustive breakdown of Vector, Content, and Hybrid strategies, candidate retrieval, confidence scoring, diversity re-ranking, and shortfall mitigation.
- **[AI Assistant Architecture](file:///home/hisham/projects/music-rec/docs/architecture/ai_assistant.md)**: Ollama local LLM integration, Pydantic `ActionPlan` validation, self-correcting retry loop, LLM caching, conversation history, and creative playlist title generation.
- **[Search Subsystem](file:///home/hisham/projects/music-rec/docs/architecture/search.md)**: Ranked metadata search, synonym expansion dictionary, FAISS similarity search, and semantic tag filtering.
- **[Playback & Session Engine](file:///home/hisham/projects/music-rec/docs/architecture/playback.md)**: `PlaybackService`, queue management, state registration, listening history tracking, session history, and artwork rendering.
- **[Web Architecture](file:///home/hisham/projects/music-rec/docs/architecture/web.md)**: Vanilla SPA client (`index.html`, `index.js`, `index.css`), view routing, static file mounting, and REST API consumption.
- **[Desktop Architecture](file:///home/hisham/projects/music-rec/docs/architecture/desktop.md)**: PySide6 GUI structure, tab architecture, background `QThread` workers (`ScanWorker`, `RecommendWorker`, `AssistantWorker`), and thread safety.
- **[API Specification](file:///home/hisham/projects/music-rec/docs/architecture/api.md)**: Complete catalog of FastAPI endpoints, request/response models, dependencies, and router organization.

### 🗄️ Database & Models
- **[Database Schema](file:///home/hisham/projects/music-rec/docs/database/schema.md)**: Entity-Relationship diagram, SQLite configuration (`PRAGMA foreign_keys=ON`), indexes, constraints, and cascade rules.
- **[Database Models](file:///home/hisham/projects/music-rec/docs/database/models.md)**: Comprehensive guide to all 12 SQLAlchemy 2.0 mapped entity classes, ownership rules, and CRUD permissions.

### 🛠️ Development & Engineering Operations
- **[Setup & Configuration](file:///home/hisham/projects/music-rec/docs/development/setup.md)**: Local environment setup, Python 3.13 configuration, Ollama setup, model management CLI, and environment variables.
- **[Testing Strategy](file:///home/hisham/projects/music-rec/docs/development/testing.md)**: Pytest suite organization, unit tests, integration tests, recommendation evaluation, and test execution.
- **[Deployment Guide](file:///home/hisham/projects/music-rec/docs/development/deployment.md)**: Running Desktop GUI vs FastAPI Web Server, daemonization, persistence files, and system requirements.
- **[Contributing Standards](file:///home/hisham/projects/music-rec/docs/development/contributing.md)**: Code style, PR workflows, logging protocols, and architectural invariants.
- **[Extension Guide](file:///home/hisham/projects/music-rec/docs/development/extension_guide.md)**: Step-by-step developer instructions for adding new recommendation strategies, search modes, assistant actions, API routes, and database models.

### 🎯 Architectural Decisions & Technical Debt
- **[Architecture Decisions (ADRs)](file:///home/hisham/projects/music-rec/docs/decisions/architecture_decisions.md)**: Rationale behind major design choices (SQLite + FAISS, local LLM via Ollama, thin API adapter layer, deterministic random projection fallback).
- **[Technical Debt & Bottlenecks](file:///home/hisham/projects/music-rec/docs/decisions/technical_debt.md)**: Known limitations, performance bottlenecks, coupling, and recommended future refactors.
- **[Product & Architecture Roadmap](file:///home/hisham/projects/music-rec/docs/decisions/roadmap.md)**: Short-term, medium-term, and long-term evolutionary roadmap for the system.

---

## ⚡ Quick Start for Developers

1. **Environment Setup**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

2. **Configure Local LLM (Ollama)**:
   ```bash
   ollama pull mistral
   python -m app.main set-model mistral
   ```

3. **Scan Local Music Collection**:
   ```bash
   python -m app.main scan /path/to/your/music
   ```

4. **Launch Web Interface**:
   ```bash
   python -m app.main web --port 8000
   ```
   Open `http://localhost:8000` in your browser.

5. **Launch PySide6 Desktop GUI**:
   ```bash
   python -m app.main gui
   ```
