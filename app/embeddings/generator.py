"""Generates 512-dimensional audio embeddings for songs using OpenL3 or a deterministic feature projection fallback."""

import logging
import pickle
import numpy as np
from app.features.extractor import AudioFeaturesInfo

logger = logging.getLogger("music_rec.embeddings.generator")

HAS_OPENL3 = False


def check_openl3_availability() -> bool:
    """Checks if OpenL3 is installed and its underlying ML dependencies are functional.

    Returns:
        True if OpenL3 is fully loaded and ready to use, False otherwise.
    """
    global HAS_OPENL3
    try:
        import openl3  # type: ignore

        HAS_OPENL3 = True
        logger.info("OpenL3 integration successfully verified.")
        return True
    except ImportError as e:
        HAS_OPENL3 = False
        logger.warning(
            "OpenL3 package import failed: %s. "
            "Please check if tensorflow/openl3 is installed in the current environment. "
            "Falling back to deterministic random projection mode.",
            e,
        )
        return False
    except Exception as e:
        HAS_OPENL3 = False
        logger.error(
            "OpenL3 failed to initialize due to configuration or dependency issues: %s. "
            "Falling back to deterministic random projection mode.",
            e,
            exc_info=True,
        )
        return False


# Run check on module import
check_openl3_availability()


def _deserialize_array(data: bytes | None) -> np.ndarray | None:
    """Safely deserializes a NumPy array from bytes."""
    if not data:
        return None
    try:
        return pickle.loads(data)
    except Exception as e:
        logger.warning("Failed to deserialize array: %s", e)
        return None


def generate_fallback_embedding(info: AudioFeaturesInfo) -> list[float]:
    """Generates a deterministic 512-dimensional embedding using random projection.

    Extracts statistical features (means and standard deviations) from the acoustic
    features of the song, constructs a 1D vector, projects it to a 512-dimensional
    space using a fixed random projection matrix, and normalizes it to unit length.

    Args:
        info: AudioFeaturesInfo dataclass populated with acoustic features.

    Returns:
        A list of 512 floats representing the unit-normalized embedding vector.
    """
    # 1. Extract statistical feature arrays
    features = []

    # BPM (1-dim)
    features.append([info.bpm or 120.0])

    # Chroma (12-dim mean, 12-dim std)
    chroma = _deserialize_array(info.chroma)
    if chroma is not None and chroma.size > 0:
        features.append(np.mean(chroma, axis=1))
        features.append(np.std(chroma, axis=1))
    else:
        features.append(np.zeros(24))

    # MFCC (13-dim mean, 13-dim std)
    mfcc = _deserialize_array(info.mfcc)
    if mfcc is not None and mfcc.size > 0:
        features.append(np.mean(mfcc, axis=1))
        features.append(np.std(mfcc, axis=1))
    else:
        features.append(np.zeros(26))

    # Spectral Centroid (1-dim mean, 1-dim std)
    centroid = _deserialize_array(info.spectral_centroid)
    if centroid is not None and centroid.size > 0:
        features.append(np.mean(centroid, axis=1))
        features.append(np.std(centroid, axis=1))
    else:
        features.append(np.zeros(2))

    # Spectral Contrast (7-dim mean, 7-dim std)
    contrast = _deserialize_array(info.spectral_contrast)
    if contrast is not None and contrast.size > 0:
        features.append(np.mean(contrast, axis=1))
        features.append(np.std(contrast, axis=1))
    else:
        features.append(np.zeros(14))

    # RMS (1-dim mean, 1-dim std)
    rms = _deserialize_array(info.rms)
    if rms is not None and rms.size > 0:
        features.append(np.mean(rms, axis=1))
        features.append(np.std(rms, axis=1))
    else:
        features.append(np.zeros(2))

    # Zero Crossing Rate (1-dim mean, 1-dim std)
    zcr = _deserialize_array(info.zero_crossing_rate)
    if zcr is not None and zcr.size > 0:
        features.append(np.mean(zcr, axis=1))
        features.append(np.std(zcr, axis=1))
    else:
        features.append(np.zeros(2))

    # Concatenate all features into a single 1D summary vector
    flat_vector = np.concatenate([np.atleast_1d(f) for f in features])

    # Standardize the feature vector to prevent scale distortion
    vec_mean = np.mean(flat_vector)
    vec_std = np.std(flat_vector) + 1e-6
    flat_vector_norm = (flat_vector - vec_mean) / vec_std

    # 2. Generate deterministic random projection matrix (dimension: len(flat_vector) x 512)
    # Using a fixed seed (42) guarantees the exact same projection on every machine
    rng = np.random.RandomState(42)
    projection_matrix = rng.normal(loc=0.0, scale=1.0, size=(len(flat_vector), 512))

    # Multiply normalized vector by the projection matrix to map to 512-dim
    projected = np.dot(flat_vector_norm, projection_matrix)

    # 3. L2 Normalize to unit vector (critical for Cosine / Inner Product similarity search)
    l2_norm = np.linalg.norm(projected)
    if l2_norm > 0:
        projected = projected / l2_norm
    else:
        # Fallback to a zero-filled vector if norm is zero
        projected = np.zeros(512)

    return projected.tolist()


def generate_embedding(info: AudioFeaturesInfo, file_path: Path | None = None) -> list[float]:
    """Generates a 512-dimensional audio embedding vector for a song.

    Attempts to use OpenL3 first. If OpenL3 is not installed or raises an error,
    falls back to the deterministic random projection method.

    Args:
        info: AudioFeaturesInfo containing the extracted acoustic features.
        file_path: Optional path to the audio file, used if querying OpenL3.

    Returns:
        A list of 512 floats representing the unit-normalized embedding vector.
    """
    if HAS_OPENL3 and file_path is not None:
        try:
            logger.info("Generating embedding using OpenL3 for: %s", file_path)
            # Load audio using librosa
            y, sr = librosa.load(str(file_path), sr=48000, mono=True)
            # Compute OpenL3 embedding
            emb, _ = openl3.get_audio_embedding(y, sr, content_type="music", embedding_size=512)
            # Average embeddings across all frames to get a single vector per song
            avg_emb = np.mean(emb, axis=0)
            # L2 Normalize
            norm = np.linalg.norm(avg_emb)
            if norm > 0:
                avg_emb = avg_emb / norm
            return avg_emb.tolist()
        except Exception as e:
            logger.error(
                "OpenL3 embedding execution failed for %s. "
                "Triggering fallback projection. Error details: %s",
                file_path,
                e,
                exc_info=True,
            )

    # Use deterministic fallback
    return generate_fallback_embedding(info)
