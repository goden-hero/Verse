"""Extracts musical and acoustic features from audio files using librosa."""

import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
import librosa
import numpy as np

logger = logging.getLogger("music_rec.features.extractor")

# Krumhansl-Schmuckler Key Profiles (12-dim arrays for C Major and C Minor)
MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)
PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


@dataclass
class AudioFeaturesInfo:
    """Dataclass containing the raw and serialized acoustic features of a song."""

    bpm: float | None = None
    chroma: bytes | None = None
    mfcc: bytes | None = None
    spectral_centroid: bytes | None = None
    spectral_contrast: bytes | None = None
    rms: bytes | None = None
    zero_crossing_rate: bytes | None = None
    key_estimation: str | None = None


def estimate_key_from_chroma(chroma_mean: np.ndarray) -> str:
    """Estimates the musical key from a mean chromagram vector.

    Correlates the chromagram mean with shifted major/minor Krumhansl-Schmuckler profiles.
    """
    if len(chroma_mean) != 12:
        return "Unknown"

    best_corr = -2.0
    best_key = "Unknown"

    # Zero-mean and normalize the chroma vector
    chroma_std = np.std(chroma_mean)
    if chroma_std == 0:
        return "Unknown"
    chroma_norm = (chroma_mean - np.mean(chroma_mean)) / chroma_std

    for is_major, profile in [(True, MAJOR_PROFILE), (False, MINOR_PROFILE)]:
        profile_norm = (profile - np.mean(profile)) / np.std(profile)
        for shift in range(12):
            shifted_profile = np.roll(profile_norm, shift)
            corr = np.corrcoef(chroma_norm, shifted_profile)[0, 1]
            if corr > best_corr:
                best_corr = corr
                key_name = PITCH_NAMES[shift]
                mode = "Major" if is_major else "Minor"
                best_key = f"{key_name} {mode}"

    return best_key


def extract_features(file_path: Path, max_duration: float = 60.0) -> AudioFeaturesInfo:
    """Loads an audio file and extracts musical features using librosa.

    Extracts: BPM, chromagram (STFT), MFCCs, spectral centroid, spectral contrast,
    RMS energy, zero crossing rate, and estimates the key.

    To conserve system memory and CPU cycles, only the first `max_duration` (default 60s)
    of the song is processed.

    Args:
        file_path: Path to the audio file.
        max_duration: Maximum duration of the audio clip to load (seconds).

    Returns:
        AudioFeaturesInfo dataclass populated with parsed/serialized values.
    """
    resolved_path = Path(file_path).resolve()
    info = AudioFeaturesInfo()

    if not resolved_path.exists() or not resolved_path.is_file():
        logger.warning("File does not exist or is not a file: %s", file_path)
        return info

    try:
        # Load audio (downsample to 22050 Hz and convert to mono)
        y, sr = librosa.load(str(resolved_path), sr=22050, mono=True, duration=max_duration)

        if len(y) == 0:
            logger.warning("Empty audio array loaded for %s", file_path)
            return info

        # 1. BPM / Tempo estimation
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        # librosa 0.10+ tempo can return a scalar or array depending on input. Normalize to float.
        if isinstance(tempo, np.ndarray):
            info.bpm = float(tempo[0]) if len(tempo) > 0 else None
        else:
            info.bpm = float(tempo)

        # 2. Chromagram (12-dim pitch energy representation)
        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        info.chroma = pickle.dumps(chroma)

        # 3. Key Estimation from mean chromagram
        chroma_mean = np.mean(chroma, axis=1)
        info.key_estimation = estimate_key_from_chroma(chroma_mean)

        # 4. MFCCs (Mel-Frequency Cepstral Coefficients)
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        info.mfcc = pickle.dumps(mfcc)

        # 5. Spectral Centroid
        centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
        info.spectral_centroid = pickle.dumps(centroid)

        # 6. Spectral Contrast
        contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
        info.spectral_contrast = pickle.dumps(contrast)

        # 7. RMS Energy
        rms = librosa.feature.rms(y=y)
        info.rms = pickle.dumps(rms)

        # 8. Zero Crossing Rate
        zcr = librosa.feature.zero_crossing_rate(y=y)
        info.zero_crossing_rate = pickle.dumps(zcr)

        logger.info("Successfully extracted audio features for: %s (estimated key: %s, BPM: %.2f)",
                    resolved_path.name, info.key_estimation, info.bpm or 0.0)

    except Exception as e:
        logger.error("Failed to extract audio features for %s: %s", resolved_path, e, exc_info=True)

    return info
