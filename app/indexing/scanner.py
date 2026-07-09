"""Folder scanning utility for detecting supported audio files."""

import logging
import os
from pathlib import Path
from app.config.settings import settings

logger = logging.getLogger("music_rec.indexing.scanner")


def scan_music_folder(folder: Path) -> list[Path]:
    """Recursively scans a directory for supported audio files.

    Excludes hidden files and folders (those starting with '.').

    Args:
        folder: The base directory Path to start scanning from.

    Returns:
        A list of resolved Path objects pointing to supported audio files.
    """
    supported = settings.supported_formats
    audio_files: list[Path] = []

    resolved_folder = Path(folder).resolve()
    if not resolved_folder.exists() or not resolved_folder.is_dir():
        logger.warning("Folder does not exist or is not a directory: %s", folder)
        return audio_files

    logger.info("Scanning folder: %s", resolved_folder)

    for root, dirs, files in os.walk(resolved_folder):
        # Modify dirs in-place to prune hidden directories from recursion
        dirs[:] = [d for d in dirs if not d.startswith(".")]

        for file in files:
            if file.startswith("."):
                continue

            file_path = Path(root) / file
            suffix = file_path.suffix.lower()

            if suffix in supported:
                audio_files.append(file_path.resolve())

    logger.info("Scan completed. Found %d audio files.", len(audio_files))
    return audio_files
