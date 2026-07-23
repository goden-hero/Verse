"""Phase 10: Verification strategy test suite for Quality-First AI Playlist Generation.

Audits pipeline metrics across intent variations:
1. Large matching candidate set ("give me 25 energetic songs")
2. Sparse / niche matching set ("give me 25 songs for a very specific mood")
3. Recommendation expansion set ("give me 15 acoustic songs")

Verification Matrix Metrics:
- Target requested length
- Initial retrieval count
- Recommendation expansion count
- Rejected songs count
- Final playlist length
- Semantic consistency check (100% required)
- Average candidate confidence
"""

import json
from unittest.mock import patch
import pytest
from sqlalchemy.orm import Session

from app.database.models import Song, SemanticTags
from app.services.playlist import (
    PlaylistCandidate,
    PlaylistService,
    _construct_playlist_candidates,
    _song_matches_semantic,
)


def _calculate_verification_matrix(
    candidates: list[PlaylistCandidate],
    target_length: int,
    filters: dict,
    session: Session,
) -> dict:
    """Calculates verification matrix metrics for a set of candidates against target filters."""
    retrieval_count = sum(1 for c in candidates if "semantic" in c.source)
    expansion_count = sum(1 for c in candidates if "recommendation" in c.source)
    
    final_length = min(len(candidates), target_length)
    final_candidates = candidates[:final_length]

    # Verify 100% semantic consistency for accepted tracks
    matching_count = sum(
        1
        for c in final_candidates
        if _song_matches_semantic(
            c.song_id,
            filters.get("moods", []),
            filters.get("activities", []),
            filters.get("energy_min"),
            filters.get("energy_max"),
            session,
        )
    )

    semantic_consistency_pct = (matching_count / final_length * 100.0) if final_length > 0 else 100.0
    avg_confidence = (sum(c.confidence for c in final_candidates) / final_length) if final_length > 0 else 0.0

    return {
        "target_length": target_length,
        "initial_retrieval_count": retrieval_count,
        "recommendation_expansion_count": expansion_count,
        "final_playlist_length": final_length,
        "semantic_consistency_pct": semantic_consistency_pct,
        "average_confidence": avg_confidence,
    }


def test_verification_matrix_large_candidate_set(db_session: Session) -> None:
    """Scenario 1: 'give me 25 energetic songs' (Large library candidate pool)."""
    # Populate 30 energetic songs
    songs = []
    tags = []
    for i in range(30):
        s = Song(
            path=f"/path/energetic_{i}.mp3",
            hash=f"hash_e_{i}",
            title=f"Energetic Track {i}",
            artist=f"Artist {i % 5}",
            duration=180.0,
        )
        songs.append(s)
    db_session.add_all(songs)
    db_session.commit()

    for s in songs:
        t = SemanticTags(song_id=s.id, moods=json.dumps(["energetic"]), energy="high")
        tags.append(t)
    db_session.add_all(tags)
    db_session.commit()

    target_length = 25
    filters = {"moods": ["energetic"], "energy_min": 0.7}

    candidates = _construct_playlist_candidates(
        strategy="hybrid",
        filters=filters,
        target_length=target_length,
        session=db_session,
    )

    matrix = _calculate_verification_matrix(candidates, target_length, filters, db_session)

    assert len(candidates) == 25
    assert matrix["target_length"] == 25
    assert matrix["final_playlist_length"] == 25
    assert matrix["semantic_consistency_pct"] == 100.0
    assert matrix["average_confidence"] >= 0.85


def test_verification_matrix_sparse_candidate_set(db_session: Session) -> None:
    """Scenario 2: 'give me 25 songs for a very specific mood' (Niche candidate pool)."""
    # Populate only 6 niche songs matching 'hyperpop'
    songs = []
    tags = []
    for i in range(6):
        s = Song(
            path=f"/path/niche_{i}.mp3",
            hash=f"hash_n_{i}",
            title=f"Niche Track {i}",
            artist=f"Niche Artist {i}",
            duration=180.0,
        )
        songs.append(s)
    db_session.add_all(songs)
    db_session.commit()

    for s in songs:
        t = SemanticTags(song_id=s.id, moods=json.dumps(["hyperpop"]), energy="high")
        tags.append(t)
    db_session.add_all(tags)
    db_session.commit()

    # Add 10 non-matching songs in the DB to test zero random padding
    non_matching = []
    for i in range(10):
        nm = Song(
            path=f"/path/nm_{i}.mp3",
            hash=f"hash_nm_{i}",
            title=f"Unrelated Track {i}",
            artist="Other Artist",
            duration=180.0,
        )
        non_matching.append(nm)
    db_session.add_all(non_matching)
    db_session.commit()

    for nm in non_matching:
        t = SemanticTags(song_id=nm.id, moods=json.dumps(["ambient"]), energy="low")
        db_session.add(t)
    db_session.commit()

    playlist = PlaylistService.generate_playlist(
        name="Niche Hyperpop Mix",
        strategy="hybrid",
        filters={"moods": ["hyperpop"]},
        target_length=25,
        session=db_session,
        enable_naming=False,
    )

    assert playlist["songs_count"] == 6
    assert playlist["requested_length"] == 25
    assert playlist["found_length"] == 6
    assert "Only 6 song(s) strongly matched" in playlist["shortfall_reason"]
    assert "Found 6 high-quality match(es) matching your request (requested 25)." in playlist["feedback_message"]

    # Verify zero random padding occurred
    playlist_song_ids = [s["id"] for s in playlist["songs"]]
    nm_ids = [nm.id for nm in non_matching]
    for nm_id in nm_ids:
        assert nm_id not in playlist_song_ids


def test_verification_matrix_recommendation_expansion(db_session: Session) -> None:
    """Scenario 3: 'give me 15 acoustic songs' (Recommendation expansion scenario)."""
    # 3 direct acoustic matches, 5 acoustic recommendations, 5 non-acoustic recommendations
    direct = []
    for i in range(3):
        s = Song(path=f"/path/ac_dir_{i}.mp3", hash=f"ac_d_{i}", title=f"Acoustic Direct {i}", artist=f"Artist {i}", duration=180.0)
        direct.append(s)
    db_session.add_all(direct)
    db_session.commit()

    for s in direct:
        t = SemanticTags(song_id=s.id, moods=json.dumps(["acoustic"]), energy="low")
        db_session.add(t)
    db_session.commit()

    rec_matching = []
    for i in range(5):
        s = Song(path=f"/path/ac_rec_{i}.mp3", hash=f"ac_r_{i}", title=f"Acoustic Rec {i}", artist=f"Artist Rec {i}", duration=180.0)
        rec_matching.append(s)
    db_session.add_all(rec_matching)
    db_session.commit()

    for s in rec_matching:
        t = SemanticTags(song_id=s.id, moods=json.dumps(["acoustic"]), energy="low")
        db_session.add(t)
    db_session.commit()

    rec_unrelated = []
    for i in range(5):
        s = Song(path=f"/path/unrel_{i}.mp3", hash=f"unrel_{i}", title=f"Heavy Metal {i}", artist=f"Metal Artist {i}", duration=180.0)
        rec_unrelated.append(s)
    db_session.add_all(rec_unrelated)
    db_session.commit()

    for s in rec_unrelated:
        t = SemanticTags(song_id=s.id, moods=json.dumps(["metal"]), energy="high")
        db_session.add(t)
    db_session.commit()

    # Mock recommendation engine to return both matching and unrelated recs
    def mock_recommend(song_id: int, strategy: str, limit: int, session: Session) -> list[dict]:
        return [
            {"id": rm.id, "title": rm.title, "artist": rm.artist, "score": 0.90}
            for rm in rec_matching
        ] + [
            {"id": ru.id, "title": ru.title, "artist": ru.artist, "score": 0.85}
            for ru in rec_unrelated
        ]

    with patch("app.services.recommendation.RecommendationService.recommend", side_effect=mock_recommend):
        playlist = PlaylistService.generate_playlist(
            name="Acoustic Session",
            strategy="hybrid",
            filters={"moods": ["acoustic"]},
            target_length=15,
            session=db_session,
            enable_naming=False,
        )

    # 3 direct + 5 matching recs = 8 total high-quality matches
    assert playlist["songs_count"] == 8
    accepted_ids = [s["id"] for s in playlist["songs"]]

    # Verify all direct and matching recs are included, and zero unrelated metal songs are included
    for s in direct:
        assert s.id in accepted_ids
    for s in rec_matching:
        assert s.id in accepted_ids
    for s in rec_unrelated:
        assert s.id not in accepted_ids
