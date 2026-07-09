"""Unit tests for the technical metadata extraction module."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from app.metadata.technical import extract_technical_metadata


def test_extract_technical_metadata_nonexistent_file() -> None:
    """Verifies that analyzing a non-existent file returns empty metadata."""
    info = extract_technical_metadata(Path("/nonexistent/file.mp3"))
    assert info.codec is None
    assert info.bitrate is None


def test_extract_technical_metadata_success(mocker, tmp_path: Path) -> None:
    """Verifies successful technical metadata extraction with mock ffprobe output."""
    dummy_file = tmp_path / "song.mp3"
    dummy_file.write_text("audio contents")

    # Mock JSON output from ffprobe
    mock_stdout = """
    {
        "streams": [
            {
                "codec_name": "mp3",
                "sample_rate": "44100",
                "channels": 2,
                "bits_per_sample": 0
            }
        ],
        "format": {
            "format_name": "mp3",
            "bit_rate": "320000"
        }
    }
    """
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = mocker.Mock(stdout=mock_stdout, stderr="", returncode=0)

    info = extract_technical_metadata(dummy_file)

    assert info.codec == "mp3"
    assert info.sample_rate == 44100
    assert info.channels == 2
    assert info.bit_depth is None  # MP3 has 0 bits_per_sample, which is skipped
    assert info.format == "mp3"
    assert info.bitrate == 320000

    # Ensure correct arguments were passed to subprocess.run
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "ffprobe"
    assert "-select_streams" in cmd
    assert "a:0" in cmd
    assert str(dummy_file.resolve()) in cmd


def test_extract_technical_metadata_lossless(mocker, tmp_path: Path) -> None:
    """Verifies bit depth is successfully parsed for lossless files (e.g. FLAC)."""
    dummy_file = tmp_path / "song.flac"
    dummy_file.write_text("audio contents")

    mock_stdout = """
    {
        "streams": [
            {
                "codec_name": "flac",
                "sample_rate": "96000",
                "channels": 6,
                "bits_per_raw_sample": 24
            }
        ],
        "format": {
            "format_name": "flac",
            "bit_rate": "1048000"
        }
    }
    """
    mocker.patch("subprocess.run", return_value=mocker.Mock(stdout=mock_stdout, returncode=0))

    info = extract_technical_metadata(dummy_file)

    assert info.codec == "flac"
    assert info.sample_rate == 96000
    assert info.channels == 6
    assert info.bit_depth == 24
    assert info.format == "flac"
    assert info.bitrate == 1048000


def test_extract_technical_metadata_timeout(mocker, tmp_path: Path) -> None:
    """Verifies that timeouts are handled gracefully and return empty metadata."""
    dummy_file = tmp_path / "song.mp3"
    dummy_file.write_text("audio contents")

    mocker.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=5.0))

    info = extract_technical_metadata(dummy_file)

    assert info.codec is None
    assert info.bitrate is None


def test_extract_technical_metadata_error(mocker, tmp_path: Path) -> None:
    """Verifies that command errors are handled gracefully and return empty metadata."""
    dummy_file = tmp_path / "song.mp3"
    dummy_file.write_text("audio contents")

    mocker.patch(
        "subprocess.run",
        side_effect=subprocess.CalledProcessError(returncode=1, cmd=["ffprobe"], stderr="error output"),
    )

    info = extract_technical_metadata(dummy_file)

    assert info.codec is None
    assert info.bitrate is None
