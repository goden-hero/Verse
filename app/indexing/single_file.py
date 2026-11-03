"""Essential indexing only: no Qt, librosa, embeddings, or AI on the ready path."""
import math
import re
from pathlib import Path
import mutagen
from sqlalchemy.dialects.sqlite import insert
from app.database.models import Song, SongSource, TechnicalMetadata
from app.indexing.scanner import compute_file_hash
from app.metadata.extractor import extract_metadata
from app.metadata.technical import extract_technical_metadata


class InvalidAudio(ValueError):
    """A completed acquisition is not the selected playable recording."""


def spotify_id_from_file(path):
    try: audio = mutagen.File(path)
    except (mutagen.MutagenError, OSError): return None
    if audio is None or not audio.tags: return None
    for name in ("WOAS", "woas", "----:spotdl:WOAS"):
        value = audio.tags.get(name)
        if hasattr(value, "url"): value = value.url
        if isinstance(value, list): value = value[0] if value else None
        if isinstance(value, bytes): value = value.decode("utf-8", errors="replace")
        match = re.fullmatch(r"https://open\.spotify\.com/(?:intl-[a-z]+/)?track/([A-Za-z0-9]{22})(?:\?[^\s]*)?", str(value or ""))
        if match: return match[1]
    return None


def audio_source_url_from_file(path):
    try: audio = mutagen.File(path)
    except (mutagen.MutagenError, OSError): return None
    if audio is None or not audio.tags: return None
    if hasattr(audio.tags, 'getall'):
        for comment in audio.tags.getall('COMM'):
            for text in comment.text:
                if re.fullmatch(r'https://(?:www\.|music\.)?youtube\.com/watch\?v=[A-Za-z0-9_-]{11}', str(text)):
                    return str(text)
    return None


def verify_audio_file(path, selected):
    path = Path(path)
    if path.suffix.lower() not in (".mp3", ".flac", ".m4a", ".wav", ".ogg") or not path.is_file() or path.stat().st_size == 0:
        raise InvalidAudio("The downloaded audio file is missing or incomplete.")
    metadata = extract_metadata(path)
    if not metadata.title or not metadata.artist or not metadata.duration or not math.isfinite(metadata.duration) or metadata.duration <= 0:
        raise InvalidAudio("Downloaded file has no valid duration, title or artist tags.")
    try:
        technical = extract_technical_metadata(path)
    except FileNotFoundError as error:
        raise ValueError("ffprobe is not installed. Install the audio tools, then retry indexing.") from error
    if not technical.codec or not technical.sample_rate or not technical.channels:
        raise ValueError("ffprobe could not verify a playable audio stream. The completed file is retained for indexing retry.")
    if path.suffix.lower() == '.mp3' and technical.codec != 'mp3':
        raise InvalidAudio("Downloaded file does not contain the requested MP3 audio format.")
    expected = selected.get("duration", 0)
    if expected and abs(metadata.duration - expected) > max(3, expected * .02):
        raise InvalidAudio("Downloaded audio duration does not match the selected recording.")
    if spotify_id_from_file(path) != selected["recording_id"]:
        raise InvalidAudio("Downloaded source tag does not match the selected Spotify recording.")
    source = selected.get('audio_source')
    if source:
        actual = audio_source_url_from_file(path)
        if not actual or actual.rsplit('v=', 1)[-1] != source['url'].rsplit('v=', 1)[-1]:
            raise InvalidAudio('Downloaded audio source does not match the verified song/album source.')
    return metadata, technical


def index_single_file(path, selected, keys, session):
    metadata, technical = verify_audio_file(path, selected)
    digest = compute_file_hash(path)
    existing = session.query(Song.id, Song.hash).filter(Song.path == str(Path(path).resolve())).first()
    if existing and existing.hash != digest:
        raise ValueError("An existing library path has different contents; it will not be replaced.")
    song_id = existing.id if existing else session.query(Song.id).filter(Song.hash == digest).scalar()
    if song_id is None:
        song = Song(path=str(Path(path).resolve()), hash=digest, title=metadata.title, artist=metadata.artist,
            album=metadata.album or selected.get("album") or "Unknown", duration=metadata.duration,
            original_genre=metadata.genre, cover_art=metadata.cover_art)
        session.add(song); session.flush(); song_id = song.id
        session.add(TechnicalMetadata(song_id=song_id, **vars(technical)))
    for key in dict.fromkeys(keys):
        session.execute(insert(SongSource).values(identity_key=key, song_id=song_id).on_conflict_do_nothing())
    session.flush()
    return song_id
