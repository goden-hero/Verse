# Architectural Decision Records (ADRs)

This document records the major architectural design decisions made during the development of Verse, detailing context, decision rationale, alternatives considered, and consequences.

---

## ADR 1: SQLite as Primary Relational Database

### Status: Accepted
### Context
Verse requires a fast, low-overhead database to store song metadata, acoustic features, listening history, playlists, and AI logs.

### Decision
Use **SQLite 3** managed via **SQLAlchemy 2.0 ORM** with `PRAGMA foreign_keys=ON` enabled on every connection.

### Rationale
- Zero server administration or external service configuration required for users.
- Single-file database (`data/music_rec.db`) simplifies backups and cross-platform distribution.
- High performance for local single-user read workloads.

### Alternatives Considered
- **PostgreSQL**: Overkill for a local single-user desktop/media server app; requires complex installation and service maintenance.
- **DuckDB**: Great for analytics, but lacks maturity for ORM single-record write cascades.

---

## ADR 2: FAISS for Vector Similarity Search

### Status: Accepted
### Context
Verse needs sub-millisecond nearest neighbor search over thousands of 512-dimensional audio embeddings.

### Decision
Use **FAISS (`faiss-cpu`)** with `IndexFlatIP` (Inner Product search over L2 unit-normalized vectors).

### Rationale
- Mathematical equivalence between Inner Product on L2-normalized vectors and Cosine Similarity:
  $$\langle \mathbf{u}, \mathbf{v} \rangle = \|\mathbf{u}\|_2 \|\mathbf{v}\|_2 \cos(\theta) = \cos(\theta)$$
- C++ execution speed is orders of magnitude faster than pure Python/NumPy matrix multiplication.
- `IndexIDMap` seamlessly maps FAISS internal vector positions to SQLite integer `song_id` primary keys.

---

## ADR 3: Local LLM Integration via Ollama

### Status: Accepted
### Context
Natural language parsing and semantic enrichment require generative language model capabilities without sacrificing privacy.

### Decision
Integrate with **Ollama HTTP API** (`http://localhost:11434`), supporting local models like `mistral`, `llama3`, and `gemma`.

### Rationale
- Completely offline and private; audio metadata is never transmitted to cloud providers.
- Local GPU/CPU acceleration via Ollama's GGUF runtime.
- Structured JSON output format enforcement (`"format": "json"`).

---

## ADR 4: Deterministic Fixed Random Projection Fallback for OpenL3

### Status: Accepted
### Context
OpenL3 provides state-of-the-art 512d audio embeddings, but requires heavy ML dependencies (TensorFlow/Keras) that may fail to install or run on minimal hardware.

### Decision
Implement a **Deterministic Random Projection Fallback** (`generate_fallback_embedding`):
- Concatenates statistical summaries (means and standard deviations) of librosa acoustic features into a dense 1D vector.
- Standardizes the vector to zero mean & unit variance.
- Multiplies by a fixed $80 \times 512$ Gaussian projection matrix initialized with a constant random seed (`seed=42`).
- L2-normalizes the resulting vector.

### Rationale
- Guarantees that Verse **always functions**, even without TensorFlow or OpenL3 installed.
- Fixed seed `42` guarantees mathematical determinism across operating systems and hardware platforms.

---

## ADR 5: Thin API & Service-Oriented Architecture

### Status: Accepted
### Context
Verse features two separate interfaces: PySide6 Desktop GUI and FastAPI Web SPA.

### Decision
Decouple all business logic into a centralized Python Service Layer (`app/services`). Both API routes and PySide6 UI components consume services directly.

### Rationale
- Eliminates code duplication across Desktop and Web clients.
- Enables easy unit testing of core recommendation and library algorithms.
