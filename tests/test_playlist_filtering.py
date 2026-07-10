import json
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session

from app.database.models import Song, SemanticTags, Playlist, PlaylistSong
from app.metadata.semantic import OllamaClient
from app.services.search import SearchService, SYNONYMS
from app.services.playlist import PlaylistService, _song_matches_semantic


def test_regex_json_repair_success() -> None:
    """Verifies that OllamaClient._extract_partial_json correctly parses malformed/partial JSON."""
    client = OllamaClient(api_url="http://mock:11434/api/generate", model="mock")
    
    malformed_json_1 = """{
      "moods": ["excited", "upbeat"],
      "activities": ["running", "dancing"],
      "themes": ["adventure", "freedom"],
      "descriptors": ["fast", "energetic"],
      "energy": "high",
     ": ":", "
    """
    
    parsed = client._extract_partial_json(malformed_json_1)
    
    assert parsed["moods"] == ["excited", "upbeat"]
    assert parsed["activities"] == ["running", "dancing"]
    assert parsed["themes"] == ["adventure", "freedom"]
    assert parsed["descriptors"] == ["fast", "energetic"]
    assert parsed["energy"] == "high"
    assert parsed["vocal_style"] == ""
    assert parsed["language"] == ""

    malformed_json_2 = """{
      "moods": ["mellow", "calm"],
      "activities": ["relaxing", "meditation"],
      "themes": ["nature", "peace"],
     ": [":", "
    """
    
    parsed_2 = client._extract_partial_json(malformed_json_2)
    assert parsed_2["moods"] == ["mellow", "calm"]
    assert parsed_2["activities"] == ["relaxing", "meditation"]
    assert parsed_2["themes"] == ["nature", "peace"]
    assert parsed_2["energy"] == ""


def test_semantic_search_synonyms(db_session: Session) -> None:
    """Verifies that SearchService.semantic_search matches synonyms of query terms."""
    # 1. Create songs
    s1 = Song(path="/path/1.mp3", hash="hash1", title="Sad Melancholy", artist="Artist A", album="Album A", duration=180.0)
    s2 = Song(path="/path/2.mp3", hash="hash2", title="Chill Calm", artist="Artist B", album="Album B", duration=200.0)
    s3 = Song(path="/path/3.mp3", hash="hash3", title="Super Hype", artist="Artist C", album="Album C", duration=220.0)
    db_session.add_all([s1, s2, s3])
    db_session.commit()

    # 2. Add semantic tags
    t1 = SemanticTags(song_id=s1.id, moods=json.dumps(["melancholic"]), activities=json.dumps(["reading"]), energy="low")
    t2 = SemanticTags(song_id=s2.id, moods=json.dumps(["calm"]), activities=json.dumps(["sleeping"]), energy="low")
    t3 = SemanticTags(song_id=s3.id, moods=json.dumps(["excited"]), activities=json.dumps(["workout"]), energy="high")
    db_session.add_all([t1, t2, t3])
    db_session.commit()

    # Query "sad" should match "melancholic" (synonym)
    sad_matches = SearchService.semantic_search(moods=["sad"], session=db_session)
    assert len(sad_matches) == 1
    assert sad_matches[0]["id"] == s1.id

    # Query "relaxing" should match "calm" (synonym) and "sleeping" activity (synonym)
    relaxing_matches = SearchService.semantic_search(moods=["relaxing"], activities=["sleeping"], session=db_session)
    assert len(relaxing_matches) == 1
    assert relaxing_matches[0]["id"] == s2.id


def test_playlist_generator_post_filters_recommendations(db_session: Session) -> None:
    """Verifies that PlaylistService post-filters recommendations to ensure they match constraints."""
    # 1. Create a seed song and candidate songs
    seed = Song(path="/path/seed.mp3", hash="seedhash", title="Seed Song", artist="Artist Seed", duration=180.0)
    rec1 = Song(path="/path/rec1.mp3", hash="rec1hash", title="Rec Match 1", artist="Artist Rec1", duration=180.0)
    rec2 = Song(path="/path/rec2.mp3", hash="rec2hash", title="Rec NonMatch", artist="Artist Rec2", duration=180.0)
    rec3 = Song(path="/path/rec3.mp3", hash="rec3hash", title="Rec Match 2", artist="Artist Rec3", duration=180.0)
    rec4 = Song(path="/path/rec4.mp3", hash="rec4hash", title="Rec Match 3", artist="Artist Rec4", duration=180.0)
    rec5 = Song(path="/path/rec5.mp3", hash="rec5hash", title="Rec Match 4", artist="Artist Rec5", duration=180.0)
    rec6 = Song(path="/path/rec6.mp3", hash="rec6hash", title="Rec Match 5", artist="Artist Rec6", duration=180.0)
    db_session.add_all([seed, rec1, rec2, rec3, rec4, rec5, rec6])
    db_session.commit()

    # 2. Add tags: seed, rec1, rec3-rec6 match 'sad', rec2 is 'excited'
    tag_seed = SemanticTags(song_id=seed.id, moods=json.dumps(["sad"]), energy="low")
    tag_rec1 = SemanticTags(song_id=rec1.id, moods=json.dumps(["melancholic"]), energy="low")
    tag_rec2 = SemanticTags(song_id=rec2.id, moods=json.dumps(["excited"]), energy="high")
    tag_rec3 = SemanticTags(song_id=rec3.id, moods=json.dumps(["sad"]), energy="low")
    tag_rec4 = SemanticTags(song_id=rec4.id, moods=json.dumps(["sad"]), energy="low")
    tag_rec5 = SemanticTags(song_id=rec5.id, moods=json.dumps(["sad"]), energy="low")
    tag_rec6 = SemanticTags(song_id=rec6.id, moods=json.dumps(["sad"]), energy="low")
    db_session.add_all([tag_seed, tag_rec1, tag_rec2, tag_rec3, tag_rec4, tag_rec5, tag_rec6])
    db_session.commit()

    # Mock recommendation service to return all recs
    mock_recs = [
        {"id": rec1.id, "title": rec1.title, "artist": rec1.artist, "score": 0.95},
        {"id": rec2.id, "title": rec2.title, "artist": rec2.artist, "score": 0.90},
        {"id": rec3.id, "title": rec3.title, "artist": rec3.artist, "score": 0.85},
        {"id": rec4.id, "title": rec4.title, "artist": rec4.artist, "score": 0.80},
        {"id": rec5.id, "title": rec5.title, "artist": rec5.artist, "score": 0.75},
        {"id": rec6.id, "title": rec6.title, "artist": rec6.artist, "score": 0.70},
    ]

    with patch("app.services.recommendation.RecommendationService.recommend", return_value=mock_recs):
        playlist_data = PlaylistService.generate_playlist(
            name="Test Sad Playlist",
            strategy="hybrid",
            filters={"moods": ["sad"], "seed_song_title": "Seed"},
            target_length=5,
            session=db_session,
        )
        
        # Verify the generated playlist has the seed song and the matching recs, but NOT the non-matching rec2!
        song_ids = [s["id"] for s in playlist_data["songs"]]
        assert seed.id in song_ids
        assert rec1.id in song_ids
        assert rec2.id not in song_ids


def test_playlist_generator_relaxation_fallback(db_session: Session) -> None:
    """Verifies that step-down relaxation handles empty pools without immediate random padding."""
    # 1. Create songs
    s1 = Song(path="/path/rel1.mp3", hash="rel1", title="Calm Song", artist="Artist A", duration=180.0)
    s2 = Song(path="/path/rel2.mp3", hash="rel2", title="Chill Song", artist="Artist B", duration=180.0)
    db_session.add_all([s1, s2])
    db_session.commit()

    # s1 has 'chill' mood but 'medium' energy.
    # s2 has 'calm' mood but 'low' energy.
    t1 = SemanticTags(song_id=s1.id, moods=json.dumps(["chill"]), energy="medium")
    t2 = SemanticTags(song_id=s2.id, moods=json.dumps(["calm"]), energy="low")
    db_session.add_all([t1, t2])
    db_session.commit()

    # Query with mood "chill" and energy low.
    # Initially:
    # - semantic_search(moods=['chill'], energy_max=0.3) will return 0 matches (s1 is 0.5, s2 is 0.2 but mood is 'calm')
    # Step-down fallback should trigger:
    # - Step 5a: Drop energy filter -> returns s1 (mood 'chill' matches)
    # - Step 5c: Drop activities and energy -> returns s1
    # - We should see s1 in the playlist due to energy dropping relaxation.
    playlist_data = PlaylistService.generate_playlist(
        name="Relaxation Test",
        strategy="hybrid",
        filters={"moods": ["chill"], "energy_max": 0.3},
        target_length=5,
        session=db_session,
    )
    
    song_ids = [s["id"] for s in playlist_data["songs"]]
    assert s1.id in song_ids
