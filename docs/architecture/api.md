# REST API Specification

Verse exposes a REST API built with FastAPI ([app/api/server.py](file:///home/hisham/projects/music-rec/app/api/server.py)). All endpoints reside under the `/api/v1` URL prefix.

---

## 1. OpenAPI & Interactive Documentation

FastAPI automatically generates interactive OpenAPI documentation at server runtime:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI Schema**: `http://localhost:8000/openapi.json`

---

## 2. Router Catalog & Endpoints

### A. Songs Router (`/api/v1/songs`)
- **Module**: [app/api/routes/songs.py](file:///home/hisham/projects/music-rec/app/api/routes/songs.py)

| Method | Endpoint | Description | Request Parameters / Body | Response Model |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/songs` | List songs with pagination & filters | `page`, `page_size`, `search`, `genre`, `mood`, `sort_by` | `SongListResponse` |
| `GET` | `/api/v1/songs/{song_id}` | Get detailed song metadata | `song_id: int` | `SongDetail` |
| `GET` | `/api/v1/songs/{song_id}/cover` | Get binary cover art image | `song_id: int` | `Response(content_type="image/jpeg")` |
| `GET` | `/api/v1/songs/{song_id}/stream` | Stream audio file bytes | `song_id: int` | `FileResponse` |
| `POST` | `/api/v1/songs/{song_id}/like` | Toggle favorite status | `song_id: int`, `liked: bool` | `{"success": true, "liked": bool}` |

---

### B. Search Router (`/api/v1/search`)
- **Module**: [app/api/routes/search.py](file:///home/hisham/projects/music-rec/app/api/routes/search.py)

| Method | Endpoint | Description | Request Parameters | Response Model |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/search` | Unified text & metadata search | `q: str` | `SearchResponse` |
| `GET` | `/api/v1/search/vector` | FAISS vector similarity search | `seed_title: str`, `k: int` | `SearchResponse` |
| `GET` | `/api/v1/search/semantic` | Filter by semantic tags | `moods: List[str]`, `activities: List[str]`, `energy_min`, `energy_max` | `SearchResponse` |

---

### C. Playlists Router (`/api/v1/playlists`)
- **Module**: [app/api/routes/playlists.py](file:///home/hisham/projects/music-rec/app/api/routes/playlists.py)

| Method | Endpoint | Description | Request Parameters / Body | Response Model |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/playlists` | List all playlists | `section: str` (`all`/`recently_played`/`recently_added`), `limit: int` | `List[PlaylistSummary]` |
| `POST` | `/api/v1/playlists` | Create empty manual playlist | `CreatePlaylistRequest` (`name`, `description`) | `PlaylistDetail` |
| `GET` | `/api/v1/playlists/{playlist_id}` | Get playlist details & tracks | `playlist_id: int` | `PlaylistDetail` |
| `PUT` | `/api/v1/playlists/{playlist_id}` | Update playlist name & songs | `playlist_id: int`, `UpdatePlaylistRequest` | `PlaylistDetail` |
| `DELETE` | `/api/v1/playlists/{playlist_id}`| Delete playlist by ID | `playlist_id: int` | `{"success": true}` |
| `GET` | `/api/v1/playlists/{playlist_id}/cover` | Get composite artwork image | `playlist_id: int` | `Response(content_type="image/jpeg")` |
| `POST` | `/api/v1/playlists/preview` | Preview AI playlist without saving | `GeneratePlaylistRequest` | `PlaylistPreviewResponse` |
| `POST` | `/api/v1/playlists/generate` | Generate and save AI playlist | `GeneratePlaylistRequest` | `PlaylistDetail` |

---

### D. Playback Router (`/api/v1/playback`)
- **Module**: [app/api/routes/playback.py](file:///home/hisham/projects/music-rec/app/api/routes/playback.py)

| Method | Endpoint | Description | Request Parameters / Body | Response Model |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/playback/play` | Record song play event | `PlayEventRequest` (`song_id`, `duration`) | `{"success": true}` |
| `POST` | `/api/v1/playback/skip` | Record song skip event | `SkipEventRequest` (`song_id`) | `{"success": true}` |
| `POST` | `/api/v1/playback/sessions/start` | Start playlist playback session | `StartSessionRequest` (`playlist_id`) | `SessionResponse` |
| `PUT` | `/api/v1/playback/sessions/{id}`| Update active session progress | `session_id: int`, `UpdateSessionRequest` | `SessionResponse` |
| `POST` | `/api/v1/playback/sessions/{id}/finish` | Mark playback session complete | `session_id: int`, `FinishSessionRequest` | `SessionResponse` |

---

### E. AI Assistant Router (`/api/v1/assistant`)
- **Module**: [app/api/routes/assistant.py](file:///home/hisham/projects/music-rec/app/api/routes/assistant.py)

| Method | Endpoint | Description | Request Parameters / Body | Response Model |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/assistant/chat` | Send natural language prompt | `ChatRequest` (`message: str`) | `ChatResponse` |
| `POST` | `/api/v1/assistant/regenerate` | Regenerate playlist preview | `RegenerateRequest` (`playlist_id: int`) | `ChatResponse` |

---

## 3. Dependency Injection & Error Handling

- **Database Session Injection**: FastAPI endpoints inject a thread-safe database session via `db: Session = Depends(get_db)`. The context manager yields `SessionLocal()`, handles exceptions with rollback, and automatically closes the session on HTTP response completion.
- **HTTP Exception Mapping**:
  - `404 Not Found`: Returned when requesting non-existent song ID, playlist ID, or missing cover art.
  - `400 Bad Request`: Returned when passing invalid strategy names or malformed payload JSON.
  - `500 Internal Server Error`: Returned on database failures or unhandled system exceptions.
