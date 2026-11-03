"""Optional expensive per-song analysis, explicitly separate from acquisition."""
import pickle
from pathlib import Path
from app.database.connection import get_session
from app.database.models import AudioFeatures, Embeddings, Song
from app.indexing.scanner import compute_file_hash


def enrich_single_song(song_id, index_path):
    from app.features.extractor import extract_features
    from app.embeddings.generator import generate_embedding
    from app.search.index import FAISSIndex
    from app.recommendations.content_pipeline import rebuild_content_pipeline
    with get_session() as db:
        song = db.query(Song.path, Song.hash).filter(Song.id == song_id).first()
        if not song: raise ValueError("Song not found.")
        path, expected = Path(song.path), song.hash
    if compute_file_hash(path) != expected: raise ValueError("File changed; do not enrich a different recording.")
    features = extract_features(path)
    vector = generate_embedding(features, path)
    with get_session() as db:
        db.merge(AudioFeatures(song_id=song_id, **vars(features)))
        db.merge(Embeddings(song_id=song_id, vector=pickle.dumps(vector)))
        db.flush()
        # Rebuild numeric indexes from stored features, not from rescanning audio.
        index = FAISSIndex(index_path, dim=512)
        ids, vectors = [], []
        for record in db.query(Embeddings).all():
            if record.vector:
                value = pickle.loads(record.vector)
                if len(value) == 512: ids.append(record.song_id); vectors.append(value)
        if ids: index.add_songs(ids, vectors)
        Path(index_path).parent.mkdir(parents=True, exist_ok=True)
        index.save()
        parent = Path(index_path).parent
        rebuild_content_pipeline(db, scaler_path=parent / "content_scaler.pkl",
            pca_path=parent / "content_pca.pkl", index_path=parent / "content_index.bin")
