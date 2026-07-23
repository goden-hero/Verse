import json
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session

from app.database.models import Song, SemanticTags, Playlist, PlaylistSong
from app.metadata.semantic import OllamaClient
from app.services.search import SearchService, SYNONYMS
from app.services.playlist import (
    PlaylistCandidate,
    PlaylistService,
    _apply_confidence_threshold,
    _construct_playlist_candidates,
    _rank_candidates,
    _score_candidate_confidence,
    _song_matches_semantic,
)


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


def test_sparse_semantic_matches_return_short_playlist(db_session: Session) -> None:
    """Verifies sparse strong matches are returned without relaxed or random padding."""
    # 1. Create songs
    s1 = Song(path="/path/rel1.mp3", hash="rel1", title="Calm Song", artist="Artist A", duration=180.0)
    s2 = Song(path="/path/rel2.mp3", hash="rel2", title="Chill Song", artist="Artist B", duration=180.0)
    s3 = Song(path="/path/rel3.mp3", hash="rel3", title="Random Song", artist="Artist C", duration=180.0)
    db_session.add_all([s1, s2, s3])
    db_session.commit()

    # s1 has 'chill' mood but 'medium' energy.
    # s2 has 'calm' mood but 'low' energy.
    t1 = SemanticTags(song_id=s1.id, moods=json.dumps(["chill"]), energy="medium")
    t2 = SemanticTags(song_id=s2.id, moods=json.dumps(["calm"]), energy="low")
    db_session.add_all([t1, t2])
    db_session.commit()

    playlist_data = PlaylistService.generate_playlist(
        name="Relaxation Test",
        strategy="hybrid",
        filters={"moods": ["chill"], "energy_max": 0.3},
        target_length=5,
        session=db_session,
    )

    song_ids = [s["id"] for s in playlist_data["songs"]]
    assert song_ids == [s2.id]
    assert playlist_data["songs_count"] == 1


def test_recommendation_expansion_uses_top_semantic_matches(db_session: Session) -> None:
    """Verifies recommendations expand from direct semantic matches, not only a seed title."""
    sem1 = Song(path="/path/sem1.mp3", hash="sem1", title="Workout One", artist="Artist A", duration=180.0)
    sem2 = Song(path="/path/sem2.mp3", hash="sem2", title="Workout Two", artist="Artist B", duration=180.0)
    valid1 = Song(path="/path/valid1.mp3", hash="valid1", title="Valid One", artist="Artist C", duration=180.0)
    valid2 = Song(path="/path/valid2.mp3", hash="valid2", title="Valid Two", artist="Artist D", duration=180.0)
    invalid = Song(path="/path/invalid.mp3", hash="invalid", title="Sad Piano", artist="Artist E", duration=180.0)
    db_session.add_all([sem1, sem2, valid1, valid2, invalid])
    db_session.commit()

    tags = [
        SemanticTags(song_id=sem1.id, moods=json.dumps(["energetic"]), activities=json.dumps(["workout"]), energy="high"),
        SemanticTags(song_id=sem2.id, moods=json.dumps(["energetic"]), activities=json.dumps(["workout"]), energy="high"),
        SemanticTags(song_id=valid1.id, moods=json.dumps(["energetic"]), activities=json.dumps(["workout"]), energy="high"),
        SemanticTags(song_id=valid2.id, moods=json.dumps(["energetic"]), activities=json.dumps(["workout"]), energy="high"),
        SemanticTags(song_id=invalid.id, moods=json.dumps(["sad"]), activities=json.dumps(["sleeping"]), energy="low"),
    ]
    db_session.add_all(tags)
    db_session.commit()

    def mock_recommend(song_id: int, strategy: str, limit: int, session: Session) -> list[dict]:
        if song_id == sem1.id:
            return [
                {"id": valid1.id, "title": valid1.title, "artist": valid1.artist, "score": 0.95},
                {"id": invalid.id, "title": invalid.title, "artist": invalid.artist, "score": 0.90},
            ]
        if song_id == sem2.id:
            return [{"id": valid2.id, "title": valid2.title, "artist": valid2.artist, "score": 0.94}]
        return []

    with patch("app.services.recommendation.RecommendationService.recommend", side_effect=mock_recommend) as rec_mock:
        playlist_data = PlaylistService.generate_playlist(
            name="Workout Expansion",
            strategy="hybrid",
            filters={"moods": ["energetic"], "activities": ["workout"]},
            target_length=10,
            session=db_session,
        )

    seed_ids = [call.kwargs["song_id"] for call in rec_mock.call_args_list]
    song_ids = [s["id"] for s in playlist_data["songs"]]

    assert seed_ids == [sem1.id, sem2.id, valid1.id]
    assert valid1.id in song_ids
    assert valid2.id in song_ids
    assert invalid.id not in song_ids


def test_recommendation_candidates_receive_source_confidence(db_session: Session) -> None:
    """Verifies recommendation confidence reflects its source strategy."""
    seed = Song(path="/path/conf-seed.mp3", hash="conf-seed", title="Confidence Seed", artist="Artist A", duration=180.0)
    rec = Song(path="/path/conf-rec.mp3", hash="conf-rec", title="Confidence Rec", artist="Artist B", duration=180.0)
    db_session.add_all([seed, rec])
    db_session.commit()

    mock_recs = [{"id": rec.id, "title": rec.title, "artist": rec.artist, "score": 0.88}]

    with patch("app.services.recommendation.RecommendationService.recommend", return_value=mock_recs):
        candidates = _construct_playlist_candidates(
            strategy="vector",
            filters={"seed_song_title": "Confidence Seed"},
            target_length=5,
            session=db_session,
        )

    rec_candidate = next(candidate for candidate in candidates if candidate.song_id == rec.id)
    assert rec_candidate.source == "vector_recommendation"
    assert rec_candidate.similarity_score == 0.88
    assert rec_candidate.confidence == pytest.approx(0.90)


def test_confidence_scoring_applies_semantic_boosts(db_session: Session) -> None:
    """Verifies matching semantic dimensions boost recommendation confidence internally."""
    song = Song(path="/path/boost.mp3", hash="boost", title="Boosted Rec", artist="Artist C", duration=180.0)
    db_session.add(song)
    db_session.commit()

    tags = SemanticTags(
        song_id=song.id,
        moods=json.dumps(["energetic"]),
        activities=json.dumps(["workout"]),
        energy="high",
    )
    db_session.add(tags)
    db_session.commit()

    scored = _score_candidate_confidence(
        PlaylistCandidate(song_id=song.id, source="content_recommendation", similarity_score=0.77),
        filters={"moods": ["energetic"], "activities": ["workout"], "energy_min": 0.7},
        session=db_session,
    )

    assert scored.confidence == pytest.approx(0.91)
    assert scored.similarity_score == 0.77


def test_candidate_ranking_prioritizes_confidence_similarity_and_diversity(db_session: Session) -> None:
    """Verifies ranking uses confidence first, then similarity and artist diversity."""
    s1 = Song(path="/path/rank1.mp3", hash="rank1", title="Rank One", artist="Artist A", duration=180.0)
    s2 = Song(path="/path/rank2.mp3", hash="rank2", title="Rank Two", artist="Artist A", duration=180.0)
    s3 = Song(path="/path/rank3.mp3", hash="rank3", title="Rank Three", artist="Artist B", duration=180.0)
    s4 = Song(path="/path/rank4.mp3", hash="rank4", title="Rank Four", artist="Artist C", duration=180.0)
    db_session.add_all([s1, s2, s3, s4])
    db_session.commit()

    ranked = _rank_candidates(
        [
            PlaylistCandidate(song_id=s1.id, source="hybrid_recommendation", similarity_score=0.90, confidence=0.95),
            PlaylistCandidate(song_id=s2.id, source="hybrid_recommendation", similarity_score=0.90, confidence=0.95),
            PlaylistCandidate(song_id=s3.id, source="hybrid_recommendation", similarity_score=0.90, confidence=0.95),
            PlaylistCandidate(song_id=s4.id, source="semantic", similarity_score=0.10, confidence=1.00),
        ],
        session=db_session,
    )

    assert [candidate.song_id for candidate in ranked] == [s4.id, s1.id, s3.id, s2.id]


def test_confidence_threshold_stops_at_first_weak_candidate() -> None:
    """Verifies low-confidence candidates stop playlist construction."""
    candidates = [
        PlaylistCandidate(song_id=1, source="semantic", confidence=1.0),
        PlaylistCandidate(song_id=2, source="vector_recommendation", confidence=0.90),
        PlaylistCandidate(song_id=3, source="unknown", confidence=0.72),
        PlaylistCandidate(song_id=4, source="semantic", confidence=1.0),
    ]

    accepted = _apply_confidence_threshold(candidates)

    assert [candidate.song_id for candidate in accepted] == [1, 2]


def test_sparse_semantic_matches_expose_shortfall_feedback(db_session: Session) -> None:
    """Phase 8: Verifies sparse matches expose shortfall metadata without silent padding."""
    s1 = Song(path="/path/sp1.mp3", hash="sp1", title="Chill Track", artist="Artist A", duration=180.0)
    db_session.add(s1)
    db_session.commit()

    t1 = SemanticTags(song_id=s1.id, moods=json.dumps(["chill"]), energy="low")
    db_session.add(t1)
    db_session.commit()

    playlist_data = PlaylistService.generate_playlist(
        name="Phase 8 Test",
        strategy="hybrid",
        filters={"moods": ["chill"]},
        target_length=25,
        session=db_session,
    )

    assert playlist_data["requested_length"] == 25
    assert playlist_data["found_length"] == 1
    assert "Only 1 song(s) strongly matched" in playlist_data["shortfall_reason"]
    assert "Found 1 high-quality match(es) matching your request (requested 25)." in playlist_data["feedback_message"]

    preview_details = PlaylistService.generate_playlist_preview_details(
        strategy="hybrid",
        filters={"moods": ["chill"]},
        target_length=20,
        session=db_session,
    )
    assert preview_details["requested_length"] == 20
    assert preview_details["found_length"] == 1
    assert preview_details["shortfall_reason"] is not None
    assert preview_details["feedback_message"] is not None


def test_post_construction_playlist_naming_generated_from_final_songs(db_session: Session) -> None:
    """Phase 9: Verifies LLM generates title/description after song selection from final tracks."""
    s1 = Song(path="/path/p9_1.mp3", hash="p91", title="Neon City", artist="Synthwave Band", duration=200.0)
    db_session.add(s1)
    db_session.commit()

    t1 = SemanticTags(song_id=s1.id, moods=json.dumps(["synthwave", "nocturnal"]), energy="high")
    db_session.add(t1)
    db_session.commit()

    with patch("app.assistant.parser.LLMParser.generate_playlist_name", return_value=("Midnight Neon", "A nocturnal synthwave vibe.")) as mock_naming:
        playlist_data = PlaylistService.generate_playlist(
            name="Generic Synthwave Mix",
            strategy="hybrid",
            filters={"moods": ["synthwave"]},
            target_length=10,
            session=db_session,
        )

    # Verify naming was called with final selected songs AFTER song selection
    mock_naming.assert_called_once()
    assert playlist_data["name"] == "Midnight Neon"
    assert playlist_data["description"] == "A nocturnal synthwave vibe."


def test_post_construction_playlist_naming_fallback_on_error(db_session: Session) -> None:
    """Phase 9: Verifies LLM naming failure gracefully falls back to default name without breaking execution."""
    s1 = Song(path="/path/p9_2.mp3", hash="p92", title="Quiet Rain", artist="Lofi Beats", duration=180.0)
    db_session.add(s1)
    db_session.commit()

    t1 = SemanticTags(song_id=s1.id, moods=json.dumps(["calm"]), energy="low")
    db_session.add(t1)
    db_session.commit()

    with patch("requests.post", side_effect=Exception("Ollama offline")):
        playlist_data = PlaylistService.generate_playlist(
            name="Default Rain Mix",
            strategy="hybrid",
            filters={"moods": ["calm"]},
            target_length=5,
            session=db_session,
        )

    # Falls back gracefully to original name
    assert playlist_data["name"] == "Default Rain Mix"
    assert playlist_data["description"] is None


