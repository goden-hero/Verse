"""Rigorous unit tests for Phase 15 covering edge cases across scanner, metadata, database, features, embeddings, FAISS, and recommendation modules."""

import os
import pickle
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Scanner
from app.indexing.scanner import scan_music_folder
# Metadata
from app.metadata.extractor import extract_metadata
# Database
from app.database.models import Song, Playlist, PlaylistSong, AssistantHistory, LLMCache, AudioFeatures, Embeddings
# Features
from app.features.extractor import extract_features, estimate_key_from_chroma, AudioFeaturesInfo
# Embeddings
from app.embeddings.generator import generate_embedding, generate_fallback_embedding
# FAISS
from app.search.index import FAISSIndex
# Recommendations
from app.recommendations.content import ContentRecommender
from app.recommendations.hybrid import HybridRecommender


# =====================================================================
# 1. Scanner Edge Cases
# =====================================================================

def test_scanner_deeply_nested_directories(tmp_path: Path) -> None:
    """Verifies that the scanner resolves audio files located in deeply nested directories."""
    nested_dir = tmp_path / "Pop" / "2020" / "Remixes" / "Indie"
    nested_dir.mkdir(parents=True)
    
    song_file = nested_dir / "indie_song.mp3"
    song_file.write_text("audio contents")
    
    files = scan_music_folder(tmp_path)
    assert len(files) == 1
    assert files[0].name == "indie_song.mp3"


def test_scanner_pruning_nested_hidden_directories(tmp_path: Path) -> None:
    """Verifies that hidden directories starting with '.' are pruned from traversal recursively."""
    # Visible folder
    visible_dir = tmp_path / "Jazz"
    visible_dir.mkdir()
    visible_song = visible_dir / "classic.mp3"
    visible_song.write_text("jazz")
    
    # Hidden folder nested inside visible folder
    hidden_dir = visible_dir / ".hidden_records"
    hidden_dir.mkdir()
    hidden_song = hidden_dir / "secret.mp3"
    hidden_song.write_text("secret jazz")
    
    files = scan_music_folder(tmp_path)
    # Only classic.mp3 should be found; hidden folder must be pruned
    assert len(files) == 1
    assert files[0].name == "classic.mp3"


def test_scanner_mixed_case_extensions(tmp_path: Path) -> None:
    """Verifies that file extension matching is case-insensitive for supported formats."""
    (tmp_path / "track1.Mp3").write_text("audio")
    (tmp_path / "track2.flAC").write_text("audio")
    (tmp_path / "track3.Wav").write_text("audio")
    (tmp_path / "readme.TXT").write_text("docs") # Unsupported
    
    files = scan_music_folder(tmp_path)
    filenames = {f.name for f in files}
    assert len(files) == 3
    assert "track1.Mp3" in filenames
    assert "track2.flAC" in filenames
    assert "track3.Wav" in filenames
    assert "readme.TXT" not in filenames


# =====================================================================
# 2. Metadata Edge Cases
# =====================================================================

def test_metadata_missing_all_tags(tmp_path: Path, mocker) -> None:
    """Verifies metadata extraction yields empty fields when files contain no tag structures."""
    no_tags_file = tmp_path / "blank.mp3"
    no_tags_file.write_text("some audio bytes")
    
    # Mock mutagen to return an audio file object with no tags
    mock_audio = mocker.Mock()
    mock_audio.info = mocker.Mock()
    mock_audio.info.length = 120.0
    mock_audio.tags = None
    mocker.patch("mutagen.File", return_value=mock_audio)
    
    meta = extract_metadata(no_tags_file)
    assert meta.duration == 120.0
    assert meta.title is None
    assert meta.artist is None
    assert meta.album is None


def test_metadata_negative_duration_handling(tmp_path: Path, mocker) -> None:
    """Verifies scanner/extractor handles empty or negative length values gracefully."""
    song_file = tmp_path / "negative.mp3"
    song_file.write_text("bytes")
    
    mock_audio = mocker.Mock()
    mock_audio.info = mocker.Mock()
    # Negative duration returned from corrupt headers
    mock_audio.info.length = -10.0
    mock_audio.tags = None
    mocker.patch("mutagen.File", return_value=mock_audio)
    
    meta = extract_metadata(song_file)
    assert meta.duration == -10.0  # Kept as is without raising exception


def test_metadata_mutagen_exception_fallback(tmp_path: Path, mocker) -> None:
    """Verifies that if mutagen throws an unhandled exception during read, extractor handles it without crashing."""
    broken_file = tmp_path / "crash.mp3"
    broken_file.write_text("bytes")
    
    mocker.patch("mutagen.File", side_effect=ValueError("Mutagen crashed!"))
    
    # Should not crash; returns empty dataclass
    meta = extract_metadata(broken_file)
    assert meta.title is None
    assert meta.duration is None


# =====================================================================
# 3. Database Integrity & Rollback Cases
# =====================================================================

def test_db_unique_constraints_and_rollback(db_session: Session) -> None:
    """Verifies database constraints correctly roll back transactions on violation."""
    # Write a song
    s1 = Song(path="/path/track.mp3", hash="hash123", title="T1", artist="A1")
    db_session.add(s1)
    db_session.commit()
    
    # Attempt to write duplicate path song inside nested transaction/session
    s2 = Song(path="/path/track.mp3", hash="hash456", title="T2", artist="A2")
    db_session.add(s2)
    
    with pytest.raises(IntegrityError):
        db_session.commit()
        
    db_session.rollback()
    
    # Confirm DB is still healthy and first song exists
    songs = db_session.query(Song).all()
    assert len(songs) == 1
    assert songs[0].hash == "hash123"


def test_db_cascade_deletes_playlists(db_session: Session) -> None:
    """Verifies that deleting a playlist cascades and deletes entries in playlist_songs."""
    # Seed song and playlist
    song = Song(path="/path/track.mp3", hash="hash123", title="T1", artist="A1")
    db_session.add(song)
    db_session.commit()
    
    pl = Playlist(name="My Favs", generated_by="MANUAL")
    db_session.add(pl)
    db_session.commit()
    
    pl_song = PlaylistSong(playlist_id=pl.id, song_id=song.id, position=0)
    db_session.add(pl_song)
    db_session.commit()
    
    # Check exists
    assert db_session.query(PlaylistSong).count() == 1
    
    # Delete playlist
    db_session.delete(pl)
    db_session.commit()
    
    # Verify playlist_songs entry is cascades deleted
    assert db_session.query(PlaylistSong).count() == 0


def test_db_assistant_history_isolation(db_session: Session) -> None:
    """Verifies insertion and serialization of assistant chat history records."""
    hist = AssistantHistory(
        prompt="Play some upbeat pop songs",
        plan=pickle.dumps([{"action": "play_song", "song_title": "Happy"}]),
        result=pickle.dumps({"success": True})
    )
    db_session.add(hist)
    db_session.commit()
    
    # Verify saved
    record = db_session.query(AssistantHistory).first()
    assert record.prompt == "Play some upbeat pop songs"
    assert pickle.loads(record.result) == {"success": True}


# =====================================================================
# 4. Feature Extraction Boundary Cases
# =====================================================================

def test_features_empty_audio_array(mocker, tmp_path: Path) -> None:
    """Verifies extract_features behavior when audio file loads as empty array."""
    dummy_file = tmp_path / "empty_sound.mp3"
    dummy_file.write_text("zero bytes")
    
    # Mock empty loaded audio
    mocker.patch("librosa.load", return_value=(np.array([]), 22050))
    
    info = extract_features(dummy_file)
    assert info.bpm is None
    assert info.chroma is None
    assert info.key_estimation is None


def test_features_key_estimation_corrupted_chroma() -> None:
    """Verifies estimate_key_from_chroma handles flat/zero chromagram vectors gracefully."""
    flat_chroma = np.zeros(12)
    key = estimate_key_from_chroma(flat_chroma)
    assert key == "Unknown"
    
    wrong_dim = np.ones(5)
    key2 = estimate_key_from_chroma(wrong_dim)
    assert key2 == "Unknown"


def test_features_librosa_extraction_failure(mocker, tmp_path: Path) -> None:
    """Verifies that exceptions raised inside librosa feature calculations don't crash extractor."""
    dummy_file = tmp_path / "crash_features.mp3"
    dummy_file.write_text("bytes")
    
    mocker.patch("librosa.load", return_value=(np.ones(10000), 22050))
    # Mock a crash in librosa feature stft and beat track
    mocker.patch("librosa.beat.beat_track", side_effect=RuntimeError("BPM crash!"))
    mocker.patch("librosa.feature.chroma_stft", side_effect=RuntimeError("Librosa crash!"))
    
    info = extract_features(dummy_file)
    # The extraction fails, so we expect empty feature details returned gracefully
    assert info.chroma is None
    assert info.bpm is None


# =====================================================================
# 5. Embeddings Generation Edge Cases
# =====================================================================

def test_embeddings_empty_features_fallback() -> None:
    """Verifies generate_fallback_embedding constructs valid vectors when AudioFeaturesInfo is empty."""
    empty_info = AudioFeaturesInfo()
    embedding = generate_fallback_embedding(empty_info)
    
    assert len(embedding) == 512
    # Should be unit-normalized
    assert np.allclose(np.linalg.norm(embedding), 1.0)


def test_embeddings_shape_verification() -> None:
    """Ensures deterministic random projection outputs exactly 512 elements and is repeatable."""
    info1 = AudioFeaturesInfo(
        bpm=120.0,
        chroma=pickle.dumps(np.ones((12, 5))),
        mfcc=pickle.dumps(np.zeros((13, 5)))
    )
    
    emb1 = generate_fallback_embedding(info1)
    emb2 = generate_fallback_embedding(info1)
    
    assert len(emb1) == 512
    # Verify determinism
    assert emb1 == emb2


# =====================================================================
# 6. FAISS Search Edge Cases
# =====================================================================

def test_faiss_empty_index_search(tmp_path: Path) -> None:
    """Verifies that searching an empty index before loading/adding returns empty matches."""
    index = FAISSIndex(tmp_path / "index.bin")
    # Empty index has ntotal == 0
    assert index.index.ntotal == 0
    
    query = [0.1] * 512
    results = index.search(query)
    assert results == []


def test_faiss_mismatched_query_vector_dimensions(tmp_path: Path) -> None:
    """Verifies adding a vector of incorrect dimension (e.g. 100 instead of 512) raises ValueError."""
    index = FAISSIndex(tmp_path / "index.bin")
    bad_embedding = [[1.0] * 100]
    
    with pytest.raises(ValueError) as exc:
        index.add_songs([1], bad_embedding)
    assert "dimension mismatch" in str(exc.value)


def test_faiss_file_io_errors(tmp_path: Path) -> None:
    """Verifies loading a corrupt FAISS index file falls back to a fresh empty index instead of crashing."""
    corrupt_file = tmp_path / "corrupt.bin"
    corrupt_file.write_text("corrupted content bytes")
    
    index = FAISSIndex(corrupt_file)
    success = index.load()
    
    assert success is False
    assert index.index.ntotal == 0


# =====================================================================
# 7. Recommendation Engines Boundary Cases
# =====================================================================

def test_content_recommender_pipeline_empty(db_session: Session) -> None:
    """Verifies ContentRecommender fails gracefully when no songs exist in DB."""
    recommender = ContentRecommender()
    
    results = recommender.recommend(song_id=1, limit=5, db_session=db_session)
    assert results == []


def test_hybrid_recommender_weight_fallback(db_session: Session, mocker) -> None:
    """Verifies HybridRecommender routes successfully when scaler/feature files are missing."""
    from app.recommendations.vector import VectorRecommender
    # Seed 1 song in DB
    song = Song(path="/path/t.mp3", hash="h123", title="T1", artist="A1")
    db_session.add(song)
    db_session.commit()
    
    # Add embedding
    emb = Embeddings(song_id=song.id, vector=pickle.dumps(([0.1] * 512)))
    db_session.add(emb)
    db_session.commit()
    
    vector_rec = VectorRecommender()
    content_rec = ContentRecommender()
    recommender = HybridRecommender([vector_rec, content_rec])
    
    # Mock content recommender to throw exception or return empty list
    mocker.patch("app.recommendations.content.ContentRecommender.recommend", return_value=[])
    
    # Mock vector recommender to return a mock match
    mocker.patch("app.recommendations.vector.VectorRecommender.recommend", return_value=[(song.id, 0.95)])
    
    results = recommender.recommend(song_id=song.id, limit=5, db_session=db_session)
    # Should fall back cleanly and return vector recommendation results
    assert len(results) == 1
    assert results[0][0] == song.id
