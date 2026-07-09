"""Metadata extractor using the mutagen library to parse audio files."""

import base64
import logging
from pathlib import Path
import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from app.metadata.models import SongMetadata

logger = logging.getLogger("music_rec.metadata.extractor")


def _parse_text(value: str | list | tuple) -> str | None:
    """Helper to convert list/tuple metadata values to string."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return _parse_text(value[0]) if value else None
    val_str = str(value).strip()
    return val_str if val_str else None


def _parse_int(value: str | int | list | tuple) -> int | None:
    """Helper to parse integers from string or tuple values (e.g., track/disc number)."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return _parse_int(value[0]) if value else None
    if isinstance(value, int):
        return value
    val_str = str(value).strip()
    if "/" in val_str:
        val_str = val_str.split("/")[0]
    # Keep only digits
    digits = "".join(c for c in val_str if c.isdigit())
    try:
        return int(digits) if digits else None
    except ValueError:
        return None


def _parse_year(value: str | int | list | tuple) -> int | None:
    """Helper to parse year (usually a 4 digit integer) from tags."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return _parse_year(value[0]) if value else None
    if isinstance(value, int):
        return value
    val_str = str(value).strip()
    # Extract first 4 digits if present
    digits = ""
    for char in val_str:
        if char.isdigit():
            digits += char
            if len(digits) == 4:
                break
        elif digits:
            # Stop if non-digit appears after we started collecting digits
            break
    try:
        return int(digits) if len(digits) == 4 else None
    except ValueError:
        return None


def extract_metadata(file: Path) -> SongMetadata:
    """Extracts tag metadata and duration from an audio file.

    Handles MP3, FLAC, M4A, OGG, and WAV files. Graces missing tags.

    Args:
        file: Path to the audio file.

    Returns:
        A SongMetadata dataclass populated with found tags.
    """
    metadata = SongMetadata()
    resolved_path = Path(file).resolve()

    if not resolved_path.exists() or not resolved_path.is_file():
        logger.warning("File does not exist or is not a file: %s", file)
        return metadata

    try:
        audio = mutagen.File(resolved_path)
        if audio is None:
            logger.warning("Mutagen could not recognize file: %s", file)
            return metadata

        # Get duration
        if audio.info:
            metadata.duration = getattr(audio.info, "length", None)

        # Parse specific formats
        if isinstance(audio, MP3):
            _extract_mp3_metadata(audio, metadata)
        elif isinstance(audio, FLAC):
            _extract_flac_metadata(audio, metadata)
        elif isinstance(audio, MP4):
            _extract_mp4_metadata(audio, metadata)
        elif isinstance(audio, OggVorbis):
            _extract_vorbis_metadata(audio, metadata)
        elif isinstance(audio, WAVE):
            _extract_wave_metadata(audio, metadata)
        else:
            # General fallback if it's another format mutagen parsed
            _extract_vorbis_metadata(audio, metadata)

    except Exception as e:
        logger.exception("Error extracting metadata from %s: %s", file, e)

    return metadata


def _extract_mp3_metadata(audio: MP3, metadata: SongMetadata) -> None:
    """Extracts fields from ID3 tags of MP3 files."""
    tags = audio.tags
    if not tags:
        return

    def _get_id3_val(frame) -> str | list | tuple | None:
        if frame is None:
            return None
        if hasattr(frame, "text"):
            return frame.text
        return frame

    metadata.title = _parse_text(_get_id3_val(tags.get("TIT2")))
    metadata.artist = _parse_text(_get_id3_val(tags.get("TPE1")))
    metadata.album = _parse_text(_get_id3_val(tags.get("TALB")))
    metadata.album_artist = _parse_text(_get_id3_val(tags.get("TPE2")))
    metadata.genre = _parse_text(_get_id3_val(tags.get("TCON")))
    # Prefer TDRC (date/recording time) then TYER (year)
    metadata.year = _parse_year(_get_id3_val(tags.get("TDRC") or tags.get("TYER")))
    metadata.track_number = _parse_int(_get_id3_val(tags.get("TRCK")))
    metadata.disc_number = _parse_int(_get_id3_val(tags.get("TPOS")))

    # Extract APIC cover art
    for frame in tags.values():
        if getattr(frame, "FrameID", None) == "APIC":
            metadata.cover_art = getattr(frame, "data", None)
            break


def _extract_flac_metadata(audio: FLAC, metadata: SongMetadata) -> None:
    """Extracts fields from FLAC tags."""
    # FLAC has dictionary-like access for tags and a dedicated pictures list
    metadata.title = _parse_text(audio.get("title"))
    metadata.artist = _parse_text(audio.get("artist"))
    metadata.album = _parse_text(audio.get("album"))
    metadata.album_artist = _parse_text(audio.get("albumartist") or audio.get("album artist"))
    metadata.genre = _parse_text(audio.get("genre"))
    metadata.year = _parse_year(audio.get("date") or audio.get("year"))
    metadata.track_number = _parse_int(audio.get("tracknumber"))
    metadata.disc_number = _parse_int(audio.get("discnumber"))

    # Extract Cover Art
    if audio.pictures:
        metadata.cover_art = audio.pictures[0].data


def _extract_mp4_metadata(audio: MP4, metadata: SongMetadata) -> None:
    """Extracts fields from MP4 (M4A) tags."""
    # iTunes atom dictionary keys
    metadata.title = _parse_text(audio.get("\xa9nam"))
    metadata.artist = _parse_text(audio.get("\xa9ART"))
    metadata.album = _parse_text(audio.get("\xa9alb"))
    metadata.album_artist = _parse_text(audio.get("aART"))
    metadata.genre = _parse_text(audio.get("\xa9gen"))
    metadata.year = _parse_year(audio.get("\xa9day"))

    # trkn and disk are usually tuples: (num, total)
    metadata.track_number = _parse_int(audio.get("trkn"))
    metadata.disc_number = _parse_int(audio.get("disk"))

    # Extract Cover Art
    covr = audio.get("covr")
    if covr:
        cover_val = covr[0]
        if isinstance(cover_val, MP4Cover):
            metadata.cover_art = bytes(cover_val)
        elif isinstance(cover_val, bytes):
            metadata.cover_art = cover_val


def _extract_vorbis_metadata(audio: mutagen.FileType, metadata: SongMetadata) -> None:
    """Extracts fields from generic Vorbis Comments / Ogg files."""
    if not audio.tags:
        return

    metadata.title = _parse_text(audio.tags.get("title"))
    metadata.artist = _parse_text(audio.tags.get("artist"))
    metadata.album = _parse_text(audio.tags.get("album"))
    metadata.album_artist = _parse_text(audio.tags.get("albumartist") or audio.tags.get("album artist"))
    metadata.genre = _parse_text(audio.tags.get("genre"))
    metadata.year = _parse_year(audio.tags.get("date") or audio.tags.get("year"))
    metadata.track_number = _parse_int(audio.tags.get("tracknumber"))
    metadata.disc_number = _parse_int(audio.tags.get("discnumber"))

    # Extract Cover Art if stored in standard base64 picture comment
    pic_tag = audio.tags.get("metadata_block_picture")
    if pic_tag:
        try:
            pic_b64 = _parse_text(pic_tag)
            if pic_b64:
                pic_data = base64.b64decode(pic_b64)
                picture = Picture(pic_data)
                metadata.cover_art = picture.data
        except Exception:
            logger.debug("Failed to decode Vorbis metadata_block_picture.")


def _extract_wave_metadata(audio: WAVE, metadata: SongMetadata) -> None:
    """Extracts fields from WAVE files (ID3 if present)."""
    # WAV files might store standard ID3 tags in a sub-chunk
    if audio.tags:
        # Re-use ID3 parsing logic since WAVE tags subclass ID3
        _extract_mp3_metadata(audio, metadata)
