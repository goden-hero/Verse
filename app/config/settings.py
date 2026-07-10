"""Configuration settings for the Music Recommendation System.

Loads settings from environment variables and an optional .env file.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

# Find project root to construct defaults
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class Settings:
    """Application settings class."""

    # Database URL
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", f"sqlite:///{PROJECT_ROOT}/data/music_rec.db"
        )
    )

    # Log Level
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper()
    )

    # Log File Path
    log_file: Path = field(
        default_factory=lambda: Path(
            os.getenv("LOG_FILE", str(PROJECT_ROOT / "data" / "music_rec.log"))
        )
    )

    # Supported audio file formats (lower case with dots)
    supported_formats: set[str] = field(
        default_factory=lambda: {
            ext.strip().lower()
            for ext in os.getenv(
                "SUPPORTED_FORMATS", ".mp3,.flac,.wav,.m4a,.ogg"
            ).split(",")
            if ext.strip()
        }
    )

    # Ollama endpoint URL
    ollama_url: str = field(
        default_factory=lambda: os.getenv(
            "OLLAMA_URL", "http://localhost:11434/api/generate"
        )
    )

    # Ollama model name
    ollama_model: str = field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3")
    )

    # Ollama timeouts
    ollama_connect_timeout: float = field(
        default_factory=lambda: float(os.getenv("OLLAMA_CONNECT_TIMEOUT", "5.0"))
    )

    # Ollama read/inference timeout (120.0s)
    ollama_read_timeout: float = field(
        default_factory=lambda: float(os.getenv("OLLAMA_READ_TIMEOUT", "120.0"))
    )

    # Ollama model keep alive ("20m" default)
    ollama_keep_alive: str = field(
        default_factory=lambda: os.getenv("OLLAMA_KEEP_ALIVE", "20m")
    )


# Global settings instance
settings = Settings()
