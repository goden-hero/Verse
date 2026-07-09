"""Unit tests for the metadata extraction module."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from app.metadata.extractor import extract_metadata
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4


def test_extract_metadata_file_not_found() -> None:
    """Verifies that non-existent files return empty metadata."""
    metadata = extract_metadata(Path("/nonexistent/file.mp3"))
    assert metadata.title is None
    assert metadata.duration is None


def test_extract_metadata_invalid_file(tmp_path: Path) -> None:
    """Verifies that unreadable/invalid files handle exceptions gracefully."""
    invalid_file = tmp_path / "corrupted.mp3"
    invalid_file.write_text("not an audio file")
    metadata = extract_metadata(invalid_file)
    assert metadata.title is None
    assert metadata.duration is None


def test_extract_mp3_metadata(mocker, tmp_path: Path) -> None:
    """Tests metadata extraction from an MP3 file with mock tags."""
    # Create dummy file path
    file_path = tmp_path / "test.mp3"
    file_path.write_text("mock mp3 content")

    # Mock audio and its attributes
    mock_audio = mocker.Mock(spec=MP3)
    mock_audio.info = mocker.Mock()
    mock_audio.info.length = 180.5

    # Mock ID3 tags
    mock_tags = {
        "TIT2": mocker.Mock(FrameID="TIT2", text=["Test Title"]),
        "TPE1": mocker.Mock(FrameID="TPE1", text=["Test Artist"]),
        "TALB": mocker.Mock(FrameID="TALB", text=["Test Album"]),
        "TPE2": mocker.Mock(FrameID="TPE2", text=["Album Artist"]),
        "TCON": mocker.Mock(FrameID="TCON", text=["Rock"]),
        "TDRC": mocker.Mock(FrameID="TDRC", text=["2023-11"]),
        "TRCK": mocker.Mock(FrameID="TRCK", text=["03/12"]),
        "TPOS": mocker.Mock(FrameID="TPOS", text=["1/2"]),
        "APIC": mocker.Mock(FrameID="APIC", data=b"fake_image_bytes"),
    }
    mock_audio.tags = mock_tags
    mock_audio.values.return_value = mock_tags.values()

    # Stub mutagen.File to return our mock MP3 object
    mocker.patch("mutagen.File", return_value=mock_audio)

    metadata = extract_metadata(file_path)

    assert metadata.title == "Test Title"
    assert metadata.artist == "Test Artist"
    assert metadata.album == "Test Album"
    assert metadata.album_artist == "Album Artist"
    assert metadata.genre == "Rock"
    assert metadata.year == 2023
    assert metadata.duration == 180.5
    assert metadata.track_number == 3
    assert metadata.disc_number == 1
    assert metadata.cover_art == b"fake_image_bytes"


def test_extract_flac_metadata(mocker, tmp_path: Path) -> None:
    """Tests metadata extraction from a FLAC file with mock tags."""
    file_path = tmp_path / "test.flac"
    file_path.write_text("mock flac content")

    mock_audio = mocker.Mock(spec=FLAC)
    mock_audio.info = mocker.Mock()
    mock_audio.info.length = 240.2

    # FLAC uses dict-like lookups
    tag_dict = {
        "title": ["FLAC Title"],
        "artist": ["FLAC Artist"],
        "album": ["FLAC Album"],
        "albumartist": ["FLAC Album Artist"],
        "genre": ["Electronic"],
        "date": ["1999-05-15"],
        "tracknumber": ["5"],
        "discnumber": ["2"],
    }
    mock_audio.get.side_effect = lambda key, default=None: tag_dict.get(key, default)

    # Mock cover art picture
    mock_picture = mocker.Mock(spec=Picture)
    mock_picture.data = b"flac_image_bytes"
    mock_audio.pictures = [mock_picture]

    mocker.patch("mutagen.File", return_value=mock_audio)

    metadata = extract_metadata(file_path)

    assert metadata.title == "FLAC Title"
    assert metadata.artist == "FLAC Artist"
    assert metadata.album == "FLAC Album"
    assert metadata.album_artist == "FLAC Album Artist"
    assert metadata.genre == "Electronic"
    assert metadata.year == 1999
    assert metadata.duration == 240.2
    assert metadata.track_number == 5
    assert metadata.disc_number == 2
    assert metadata.cover_art == b"flac_image_bytes"


def test_extract_mp4_metadata(mocker, tmp_path: Path) -> None:
    """Tests metadata extraction from an MP4 (M4A) file with mock tags."""
    file_path = tmp_path / "test.m4a"
    file_path.write_text("mock m4a content")

    mock_audio = mocker.Mock(spec=MP4)
    mock_audio.info = mocker.Mock()
    mock_audio.info.length = 120.0

    # MP4 uses iTunes specific atom keys
    tag_dict = {
        "\xa9nam": ["M4A Title"],
        "\xa9ART": ["M4A Artist"],
        "\xa9alb": ["M4A Album"],
        "aART": ["M4A Album Artist"],
        "\xa9gen": ["Jazz"],
        "\xa9day": ["2015"],
        "trkn": [(8, 10)],
        "disk": [(1, 1)],
        "covr": [b"m4a_image_bytes"],
    }
    mock_audio.get.side_effect = lambda key, default=None: tag_dict.get(key, default)

    mocker.patch("mutagen.File", return_value=mock_audio)

    metadata = extract_metadata(file_path)

    assert metadata.title == "M4A Title"
    assert metadata.artist == "M4A Artist"
    assert metadata.album == "M4A Album"
    assert metadata.album_artist == "M4A Album Artist"
    assert metadata.genre == "Jazz"
    assert metadata.year == 2015
    assert metadata.duration == 120.0
    assert metadata.track_number == 8
    assert metadata.disc_number == 1
    assert metadata.cover_art == b"m4a_image_bytes"
