"""Pydantic schemas for the AI assistant actions and plans."""

from typing import Dict, List, Literal, Optional, Union, Annotated
from pydantic import BaseModel, Field, field_validator


class SearchLibrary(BaseModel):
    """Searches library by text query matching."""

    action: Literal["search_library"] = "search_library"
    query: str


class SemanticSearch(BaseModel):
    """Filters library based on semantic LLM descriptors."""

    action: Literal["semantic_search"] = "semantic_search"
    moods: List[str] = Field(default_factory=list)
    activities: List[str] = Field(default_factory=list)
    energy_min: Optional[float] = None
    energy_max: Optional[float] = None


class RecommendSong(BaseModel):
    """Retrieves ranked similar items to a specified song."""

    action: Literal["recommend_song"] = "recommend_song"
    song_title: str
    strategy: str = "vector"
    limit: int = 10

    @field_validator("limit", mode="before")
    @classmethod
    def coerce_limit(cls, v):
        if isinstance(v, (int, float)):
            return int(round(v))
        if isinstance(v, str):
            try:
                return int(round(float(v)))
            except ValueError:
                pass
        return v


class GeneratePlaylist(BaseModel):
    """Generates and persists a playlist."""

    action: Literal["generate_playlist"] = "generate_playlist"
    playlist_name: str
    strategy: str = "hybrid"
    filters: Dict = Field(default_factory=dict)
    target_length: int = 25

    @field_validator("target_length", mode="before")
    @classmethod
    def coerce_target_length(cls, v):
        if isinstance(v, (int, float)):
            return int(round(v))
        if isinstance(v, str):
            try:
                return int(round(float(v)))
            except ValueError:
                pass
        return v


class PlayPlaylist(BaseModel):
    """Plays the specified playlist by name."""

    action: Literal["play_playlist"] = "play_playlist"
    playlist_name: str


class PlaySong(BaseModel):
    """Loads and starts playback of a song."""

    action: Literal["play_song"] = "play_song"
    song_title: str


class Pause(BaseModel):
    """Pauses current active playback."""

    action: Literal["pause"] = "pause"


class Resume(BaseModel):
    """Resumes paused active playback."""

    action: Literal["resume"] = "resume"


class Skip(BaseModel):
    """Skips the currently playing song."""

    action: Literal["skip"] = "skip"


class LikeSong(BaseModel):
    """Adds a song to favorites (likes = True)."""

    action: Literal["like_song"] = "like_song"
    song_title: str


class UnlikeSong(BaseModel):
    """Removes a song from favorites (likes = False)."""

    action: Literal["unlike_song"] = "unlike_song"
    song_title: str


class ShuffleQueue(BaseModel):
    """Shuffles the active playback queue."""

    action: Literal["shuffle_queue"] = "shuffle_queue"


class RepeatQueue(BaseModel):
    """Toggles repeat queue mode."""

    action: Literal["repeat_queue"] = "repeat_queue"


class ScanLibrary(BaseModel):
    """Triggers recursive scan on a folder path."""

    action: Literal["scan_library"] = "scan_library"
    folder_path: str


class OpenPlaylist(BaseModel):
    """Loads a playlist into view."""

    action: Literal["open_playlist"] = "open_playlist"
    playlist_name: str


class DeletePlaylist(BaseModel):
    """Deletes a playlist from the system."""

    action: Literal["delete_playlist"] = "delete_playlist"
    playlist_name: str


class SavePlaylist(BaseModel):
    """Saves a playlist."""

    action: Literal["save_playlist"] = "save_playlist"
    playlist_name: str


class RenamePlaylist(BaseModel):
    """Renames a playlist."""

    action: Literal["rename_playlist"] = "rename_playlist"
    playlist_name: str
    new_name: str


ActionType = Annotated[
    Union[
        SearchLibrary,
        SemanticSearch,
        RecommendSong,
        GeneratePlaylist,
        PlayPlaylist,
        PlaySong,
        Pause,
        Resume,
        Skip,
        LikeSong,
        UnlikeSong,
        ShuffleQueue,
        RepeatQueue,
        ScanLibrary,
        OpenPlaylist,
        DeletePlaylist,
        SavePlaylist,
        RenamePlaylist,
    ],
    Field(discriminator="action")
]


class ActionPlan(BaseModel):
    """List of actions to execute sequentially to fulfill user intent."""

    plan: List[ActionType] = Field(..., description="Ordered list of actions to execute")
