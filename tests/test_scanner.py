"""Unit tests for the folder scanner module."""

from pathlib import Path
from app.indexing.scanner import scan_music_folder


def test_scan_music_folder_finds_supported_files(mock_music_library: Path) -> None:
    """Verifies that all supported audio formats are successfully detected."""
    files = scan_music_folder(mock_music_library)
    # Expected: song1.mp3, song2.FLAC (case insensitive), song3.wav, song4.m4a, song5.ogg
    # Total: 5 files
    assert len(files) == 5

    filenames = {f.name for f in files}
    assert "song1.mp3" in filenames
    assert "song2.FLAC" in filenames
    assert "song3.wav" in filenames
    assert "song4.m4a" in filenames
    assert "song5.ogg" in filenames


def test_scan_music_folder_ignores_hidden_and_unsupported(
    mock_music_library: Path,
) -> None:
    """Verifies that hidden files/folders and unsupported formats are ignored."""
    files = scan_music_folder(mock_music_library)
    filenames = {f.name for f in files}

    # Verify hidden/unsupported files are NOT in the scanned files
    assert "readme.txt" not in filenames
    assert "unsupported.mp4" not in filenames
    assert "song6.mp3" not in filenames  # inside .hidden_folder
    assert ".hidden_song.mp3" not in filenames  # hidden file


def test_scan_music_folder_nonexistent_path() -> None:
    """Verifies scanner handles non-existent paths gracefully."""
    non_existent = Path("/nonexistent/path/for/tests")
    files = scan_music_folder(non_existent)
    assert files == []
