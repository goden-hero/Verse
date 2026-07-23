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
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "mistral")
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


def set_ollama_model(model_name: str, persist: bool = True) -> str:
    """Sets the active Ollama LLM model name for the application.

    Args:
        model_name: The target model name (e.g. 'mistral', 'llama3:latest').
        persist: If True, writes the update to the root .env file.

    Returns:
        The updated model name.
    """
    model_name = model_name.strip()
    object.__setattr__(settings, "ollama_model", model_name)
    os.environ["OLLAMA_MODEL"] = model_name

    # Clear Ollama model resolution cache if loaded
    try:
        from app.utils.ollama import resolve_ollama_model
        resolve_ollama_model.cache_clear()
    except Exception:
        pass

    # Reset health check state in LLMParser if loaded
    try:
        from app.assistant.parser import LLMParser
        LLMParser._health_checked = False
        LLMParser._is_healthy = False
    except Exception:
        pass

    if persist:
        env_path = PROJECT_ROOT / ".env"
        lines = []
        key_found = False
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                if line.strip().startswith("OLLAMA_MODEL="):
                    new_lines.append(f"OLLAMA_MODEL={model_name}\n")
                    key_found = True
                else:
                    new_lines.append(line)
            lines = new_lines

        if not key_found:
            if lines and not lines[-1].endswith("\n"):
                lines.append("\n")
            lines.append(f"OLLAMA_MODEL={model_name}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    return model_name

