"""SQLAlchemy models for the Music Recommendation System database."""

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base class for SQLAlchemy models."""

    pass


class Song(Base):
    """Represents a song in the library."""

    __tablename__ = "songs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hash: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    artist: Mapped[str | None] = mapped_column(String, nullable=True)
    album: Mapped[str | None] = mapped_column(String, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_genre: Mapped[str | None] = mapped_column(String, nullable=True)
    cover_art: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Relationships
    technical_metadata: Mapped["TechnicalMetadata"] = relationship(
        back_populates="song", cascade="all, delete-orphan", uselist=False
    )
    audio_features: Mapped["AudioFeatures"] = relationship(
        back_populates="song", cascade="all, delete-orphan", uselist=False
    )
    musicbrainz_metadata: Mapped["MusicBrainzMetadata"] = relationship(
        back_populates="song", cascade="all, delete-orphan", uselist=False
    )
    embeddings: Mapped["Embeddings"] = relationship(
        back_populates="song", cascade="all, delete-orphan", uselist=False
    )
    semantic_tags: Mapped["SemanticTags"] = relationship(
        back_populates="song", cascade="all, delete-orphan", uselist=False
    )
    listening_history: Mapped["ListeningHistory"] = relationship(
        back_populates="song", cascade="all, delete-orphan", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Song(id={self.id}, title='{self.title}', artist='{self.artist}')>"


class TechnicalMetadata(Base):
    """Represents detailed, low-level technical features of the audio file."""

    __tablename__ = "technical_metadata"

    song_id: Mapped[int] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True
    )
    codec: Mapped[str | None] = mapped_column(String, nullable=True)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bit_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relationship
    song: Mapped["Song"] = relationship(back_populates="technical_metadata")

    def __repr__(self) -> str:
        return f"<TechnicalMetadata(song_id={self.song_id}, format='{self.format}')>"


class AudioFeatures(Base):
    """Represents features extracted using librosa (e.g. BPM, MFCCs)."""

    __tablename__ = "audio_features"

    song_id: Mapped[int] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True
    )
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    chroma: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    mfcc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    spectral_centroid: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    spectral_contrast: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    rms: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    zero_crossing_rate: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    key_estimation: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relationship
    song: Mapped["Song"] = relationship(back_populates="audio_features")

    def __repr__(self) -> str:
        return f"<AudioFeatures(song_id={self.song_id}, bpm={self.bpm})>"


class MusicBrainzMetadata(Base):
    """Represents enriched metadata downloaded from MusicBrainz."""

    __tablename__ = "musicbrainz_metadata"

    song_id: Mapped[int] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True
    )
    canonical_artist: Mapped[str | None] = mapped_column(String, nullable=True)
    canonical_album: Mapped[str | None] = mapped_column(String, nullable=True)
    release_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    canonical_genre: Mapped[str | None] = mapped_column(String, nullable=True)
    musicbrainz_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relationship
    song: Mapped["Song"] = relationship(back_populates="musicbrainz_metadata")

    def __repr__(self) -> str:
        return (
            f"<MusicBrainzMetadata(song_id={self.song_id}, "
            f"canonical_artist='{self.canonical_artist}')>"
        )


class Embeddings(Base):
    """Represents vector embeddings for search (e.g. from OpenL3)."""

    __tablename__ = "embeddings"

    song_id: Mapped[int] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True
    )
    vector: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Relationship
    song: Mapped["Song"] = relationship(back_populates="embeddings")

    def __repr__(self) -> str:
        return f"<Embeddings(song_id={self.song_id})>"


class SemanticTags(Base):
    """Represents LLM-generated semantic tags for moods and themes."""

    __tablename__ = "semantic_tags"

    song_id: Mapped[int] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True
    )
    moods: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON-encoded array
    activities: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON-encoded array
    themes: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON-encoded array
    descriptors: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON-encoded array
    energy: Mapped[str | None] = mapped_column(String, nullable=True)
    vocal_style: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relationship
    song: Mapped["Song"] = relationship(back_populates="semantic_tags")

    def __repr__(self) -> str:
        return f"<SemanticTags(song_id={self.song_id})>"


class ListeningHistory(Base):
    """Tracks local user listening counts and history."""

    __tablename__ = "listening_history"

    song_id: Mapped[int] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True
    )
    play_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skips: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    likes: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_played: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    play_duration: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Relationship
    song: Mapped["Song"] = relationship(back_populates="listening_history")

    def __repr__(self) -> str:
        return (
            f"<ListeningHistory(song_id={self.song_id}, play_count={self.play_count}, "
            f"likes={self.likes})>"
        )
