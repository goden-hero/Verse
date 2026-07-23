from pydantic import BaseModel, ConfigDict
from typing import List, Optional

class SongResponse(BaseModel):
    """Pydantic model representing a song with basic metadata, excluding filesystem paths."""
    id: int
    title: Optional[str] = "Unknown"
    artist: Optional[str] = "Unknown"
    album: Optional[str] = "Unknown"
    duration: Optional[float] = 0.0
    genre: Optional[str] = "Unknown"
    artwork_available: bool

    # Enable SQLAlchemy ORM mapping
    model_config = ConfigDict(from_attributes=True)

class SongListResponse(BaseModel):
    """Pydantic model representing a paginated list of songs."""
    songs: List[SongResponse]
    total_count: int
    page: int
    page_size: int

class PlaylistGenerateRequest(BaseModel):
    """Pydantic model representing a request to generate a playlist preview."""
    strategy: str
    seed_type: str
    seed_value: str
    limit: Optional[int] = 20

class PlaylistCreateRequest(BaseModel):
    """Pydantic model representing a request to create/save a playlist."""
    name: str
    song_ids: List[int]

class PlaylistResponse(BaseModel):
    """Pydantic model representing a playlist's basic metadata."""
    id: int
    name: str
    songs_count: int
    total_duration: float
    strategy: Optional[str] = None
    generated_by: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)

class PlayRecordRequest(BaseModel):
    """Pydantic model representing a request to record a play event."""
    song_id: int
    duration: float

class SkipRecordRequest(BaseModel):
    """Pydantic model representing a request to record a skip event."""
    song_id: int

class LikeRecordRequest(BaseModel):
    """Pydantic model representing a request to toggle a song's liked/favorite status."""
    song_id: int
    liked: bool

class ChatRequest(BaseModel):
    """Pydantic model representing an AI Assistant prompt message request."""
    message: str

class ChatStepResponse(BaseModel):
    """Pydantic model representing an execution step's result."""
    action: str
    status: str
    output: Optional[dict] = None
    error: Optional[str] = None

class PlaylistPreviewResponse(BaseModel):
    """Pydantic model representing a temporary playlist preview returned by assistant."""
    name: str
    songs_count: int
    total_duration: float
    strategy: Optional[str] = None
    requested_length: Optional[int] = None
    found_length: Optional[int] = None
    shortfall_reason: Optional[str] = None
    feedback_message: Optional[str] = None
    songs: List[SongResponse]

class PlaylistUpdateRequest(BaseModel):
    """Pydantic model representing a request to update playlist details or track order."""
    name: Optional[str] = None
    description: Optional[str] = None
    song_ids: Optional[List[int]] = None

class PlaylistStatsResponse(BaseModel):
    """Pydantic model representing quick playlist statistics."""
    play_count: int
    last_played_at: Optional[str] = None
    song_count: int
    total_duration: float

class PlaylistDetailResponse(BaseModel):
    """Pydantic model representing complete playlist metadata and song list."""
    id: int
    name: str
    description: Optional[str] = None
    songs_count: int
    total_duration: float
    created_at: str
    updated_at: Optional[str] = None
    prompt: Optional[str] = None
    strategy: Optional[str] = None
    seed_type: Optional[str] = None
    seed_song_id: Optional[int] = None
    seed_song_title: Optional[str] = None
    generated_by: str
    generator_version: Optional[str] = None
    llm_model: Optional[str] = None
    created_from: Optional[str] = None
    play_count: int
    last_played_at: Optional[str] = None
    requested_length: Optional[int] = None
    found_length: Optional[int] = None
    shortfall_reason: Optional[str] = None
    feedback_message: Optional[str] = None
    songs: List[SongResponse]


class PlaySessionStartRequest(BaseModel):
    """Pydantic model representing request to start or resume a playlist playback session."""
    song_index: Optional[int] = 0
    position: Optional[float] = 0.0

class PlaySessionProgressRequest(BaseModel):
    """Pydantic model representing request to sync session progress."""
    song_index: int
    position: float
    completed: Optional[bool] = False

class PlaybackSessionResponse(BaseModel):
    """Pydantic model representing active or historical playback session details."""
    session_id: int
    playlist_id: Optional[int] = None
    current_song_index: int
    current_position: float
    started_at: str
    updated_at: str
    finished_at: Optional[str] = None
    completed: bool

class ContinueListeningResponse(BaseModel):
    """Pydantic model representing a playlist item in the Continue Listening list."""
    session_id: int
    playlist_id: int
    playlist_name: str
    song_count: int
    total_duration: float
    current_song_index: int
    current_position: float
    updated_at: Optional[str] = None
    started_at: Optional[str] = None

class ChatResponse(BaseModel):
    """Pydantic model representing the response to an assistant prompt."""
    message: str
    success: bool
    steps: List[ChatStepResponse]
    playlist: Optional[PlaylistPreviewResponse] = None


