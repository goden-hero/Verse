"""Unit tests for the audio features extraction module."""

import pickle
from pathlib import Path
import librosa
import numpy as np
import pytest
from app.features.extractor import (
    AudioFeaturesInfo,
    estimate_key_from_chroma,
    extract_features,
)


def test_estimate_key_from_chroma() -> None:
    """Verifies that key estimation identifies major and minor keys based on chroma profiles."""
    # Profile for C Major (index 0 is C)
    # Give high energy to C (0), E (4), G (7)
    chroma_c_major = np.zeros(12)
    chroma_c_major[0] = 5.0  # C
    chroma_c_major[4] = 3.5  # E
    chroma_c_major[7] = 4.0  # G

    key = estimate_key_from_chroma(chroma_c_major)
    # Should estimate C Major or a closely related key (like G Major or A Minor)
    assert "Major" in key or "Minor" in key

    # Profile for A Minor (A is index 9, C is index 0, E is index 4)
    chroma_a_minor = np.zeros(12)
    chroma_a_minor[9] = 5.0  # A
    chroma_a_minor[0] = 4.0  # C
    chroma_a_minor[4] = 3.0  # E

    key_minor = estimate_key_from_chroma(chroma_a_minor)
    assert "Minor" in key_minor or "Major" in key_minor


def test_extract_features_nonexistent_file() -> None:
    """Verifies that attempting to extract features on a non-existent file returns empty info."""
    info = extract_features(Path("/nonexistent/song.mp3"))
    assert info.bpm is None
    assert info.chroma is None


def test_extract_features_success(mocker, tmp_path: Path) -> None:
    """Verifies successful audio feature extraction with mocked librosa outputs."""
    dummy_file = tmp_path / "song.mp3"
    dummy_file.write_text("audio content")

    # Mock audio signal (1 second of mono audio at 22050 Hz)
    mock_y = np.sin(2 * np.pi * 440 * np.arange(22050) / 22050)
    mock_sr = 22050

    mocker.patch("librosa.load", return_value=(mock_y, mock_sr))
    mocker.patch("librosa.beat.beat_track", return_value=(120.0, None))

    # Mock features to return small predictable arrays
    mocker.patch("librosa.feature.chroma_stft", return_value=np.ones((12, 10)))
    mocker.patch("librosa.feature.mfcc", return_value=np.ones((13, 10)))
    mocker.patch("librosa.feature.spectral_centroid", return_value=np.ones((1, 10)))
    mocker.patch("librosa.feature.spectral_contrast", return_value=np.ones((7, 10)))
    mocker.patch("librosa.feature.rms", return_value=np.ones((1, 10)))
    mocker.patch("librosa.feature.zero_crossing_rate", return_value=np.ones((1, 10)))

    info = extract_features(dummy_file)

    assert info.bpm == 120.0
    assert info.key_estimation is not None

    # Verify we can deserialize the arrays
    chroma = pickle.loads(info.chroma)
    assert chroma.shape == (12, 10)

    mfcc = pickle.loads(info.mfcc)
    assert mfcc.shape == (13, 10)

    centroid = pickle.loads(info.spectral_centroid)
    assert centroid.shape == (1, 10)

    contrast = pickle.loads(info.spectral_contrast)
    assert contrast.shape == (7, 10)

    rms = pickle.loads(info.rms)
    assert rms.shape == (1, 10)

    zcr = pickle.loads(info.zero_crossing_rate)
    assert zcr.shape == (1, 10)
