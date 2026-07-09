"""Logging configuration for the Music Recommendation System.

Provides structured file and console logging based on settings.
"""

import logging
import sys
from pathlib import Path
from app.config.settings import settings


def setup_logging() -> None:
    """Configures system-wide logging.

    Logs are written to both standard output and a file specified in the settings.
    """
    # Ensure log file directory exists
    log_file_path = Path(settings.log_file)
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    # Get log level from settings
    numeric_level = getattr(logging, settings.log_level, logging.INFO)

    # Formatters
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers if setup is called multiple times
    if root_logger.handlers:
        return

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(numeric_level)
    root_logger.addHandler(console_handler)

    # File Handler
    try:
        file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(numeric_level)
        root_logger.addHandler(file_handler)
    except OSError as e:
        # Fallback if log file cannot be created
        logging.warning("Failed to initialize file logger at %s: %s", log_file_path, e)
