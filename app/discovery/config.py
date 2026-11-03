import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DiscoveryConfig:
    provider: str = "auto"
    client_id: str = field(default="", repr=False)
    client_secret: str = field(default="", repr=False)
    contact: str = ""
    music_dir: Path | None = None
    timeout: int = 600
    attempts: int = 3
    spotdl_executable: str = ""

    @property
    def catalogue(self):
        return ("spotify" if self.client_id and self.client_secret else "musicbrainz") if self.provider == "auto" else self.provider

    @classmethod
    def load(cls):
        music = os.getenv("VERSE_MUSIC_DIR", "").strip()
        return cls(provider=os.getenv("VERSE_CATALOGUE", "auto").lower(),
            client_id=os.getenv("VERSE_SPOTIFY_CLIENT_ID", os.getenv("SPOTIPY_CLIENT_ID", "")),
            client_secret=os.getenv("VERSE_SPOTIFY_CLIENT_SECRET", os.getenv("SPOTIPY_CLIENT_SECRET", "")),
            contact=os.getenv("VERSE_CATALOGUE_CONTACT", ""), music_dir=Path(music).expanduser().resolve() if music else None,
            timeout=max(30, min(1800, int(os.getenv("VERSE_DOWNLOAD_TIMEOUT", "600")))),
            attempts=max(1, min(5, int(os.getenv("VERSE_REQUEST_ATTEMPTS", "3")))),
            spotdl_executable=os.getenv("VERSE_SPOTDL_EXECUTABLE", ""))
