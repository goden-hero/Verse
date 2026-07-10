"""Background QThread workers for heavy operations in the desktop UI."""

import hashlib
import logging
import pickle
import time
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from sqlalchemy.orm import Session
from app.database.connection import get_session
from app.database.models import AudioFeatures, Embeddings, Song, TechnicalMetadata
from app.indexing.scanner import scan_music_folder
from app.metadata.extractor import extract_metadata
from app.metadata.technical import extract_technical_metadata
from app.features.extractor import extract_features
from app.embeddings.generator import generate_embedding
from app.search.index import FAISSIndex
from app.recommendations.content_pipeline import rebuild_content_pipeline
from app.recommendations.registry import get_recommender
from app.metadata.semantic import OllamaClient

logger = logging.getLogger("music_rec.ui.workers")


def compute_file_hash(file_path: Path) -> str:
    """Computes SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


class ScanWorker(QThread):
    """Background worker for scanning folders and extracting features/embeddings."""

    progress = Signal(int, str)  # percentage (0-100), status message
    finished = Signal(int)       # number of new/updated songs
    error = Signal(str)          # error message

    def __init__(self, folder_path: str | Path, vector_index_path: str | Path) -> None:
        super().__init__()
        self.folder_path = Path(folder_path)
        self.vector_index_path = Path(vector_index_path)

    def run(self) -> None:
        try:
            with get_session() as session:
                # 1. Scan folder
                self.progress.emit(5, "Scanning directory for music files...")
                files = scan_music_folder(self.folder_path)
                if not files:
                    self.progress.emit(100, "No supported audio files found.")
                    self.finished.emit(0)
                    return

                total_files = len(files)
                processed_count = 0
                new_songs_count = 0

                # Ensure data folder exists
                self.vector_index_path.parent.mkdir(parents=True, exist_ok=True)

                for idx, file_path in enumerate(files):
                    self.progress.emit(
                        int(5 + (idx / total_files) * 80),
                        f"Processing ({idx+1}/{total_files}): {file_path.name}",
                    )

                    file_hash = compute_file_hash(file_path)

                    # Check if song exists with same path and hash
                    existing = session.query(Song).filter_by(path=str(file_path)).first()
                    if existing:
                        if existing.hash == file_hash:
                            # Song exists and is unchanged
                            continue
                        else:
                            # Song path exists but content changed -> delete and recreate to trigger cascade
                            session.delete(existing)
                            session.commit()

                    # Check if hash already exists under different path (avoid duplicate content)
                    duplicate_hash = session.query(Song).filter_by(hash=file_hash).first()
                    if duplicate_hash:
                        continue

                    # Index new song
                    try:
                        # Extract tags
                        meta = extract_metadata(file_path)
                        song = Song(
                            path=str(file_path),
                            hash=file_hash,
                            title=meta.title or file_path.stem,
                            artist=meta.artist or "Unknown",
                            album=meta.album or "Unknown",
                            duration=meta.duration,
                            original_genre=meta.genre,
                        )
                        session.add(song)
                        session.commit()  # commit to generate ID

                        # Extract technical metadata
                        tech_meta = extract_technical_metadata(file_path)
                        tech = TechnicalMetadata(
                            song_id=song.id,
                            codec=tech_meta.codec,
                            bitrate=tech_meta.bitrate,
                            sample_rate=tech_meta.sample_rate,
                            channels=tech_meta.channels,
                            bit_depth=tech_meta.bit_depth,
                            format=tech_meta.format,
                        )
                        session.add(tech)

                        # Extract audio features
                        feat_info = extract_features(file_path)
                        features = AudioFeatures(
                            song_id=song.id,
                            bpm=feat_info.bpm,
                            chroma=feat_info.chroma,
                            mfcc=feat_info.mfcc,
                            spectral_centroid=feat_info.spectral_centroid,
                            spectral_contrast=feat_info.spectral_contrast,
                            rms=feat_info.rms,
                            zero_crossing_rate=feat_info.zero_crossing_rate,
                            key_estimation=feat_info.key_estimation,
                        )
                        session.add(features)

                        # Generate 512-dim embedding
                        vector = generate_embedding(feat_info, file_path)
                        emb = Embeddings(
                            song_id=song.id,
                            vector=pickle.dumps(vector),
                        )
                        session.add(emb)

                        session.commit()
                        new_songs_count += 1

                    except Exception as e:
                        logger.error("Failed to index %s: %s", file_path, e)
                        session.rollback()

                # 2. Sync / rebuild FAISS vector index
                self.progress.emit(90, "Rebuilding FAISS similarity search index...")
                idx_dim_512 = FAISSIndex(self.vector_index_path, dim=512)
                idx_dim_512._initialize_empty_index()

                all_embs = session.query(Embeddings).all()
                song_ids = []
                vectors = []
                for emb_rec in all_embs:
                    if emb_rec.vector:
                        try:
                            v = pickle.loads(emb_rec.vector)
                            if len(v) == 512:
                                song_ids.append(emb_rec.song_id)
                                vectors.append(v)
                        except Exception:
                            pass

                if song_ids:
                    idx_dim_512.add_songs(song_ids, vectors)
                idx_dim_512.save()

                # 3. Rebuild classical Content Recommender MIR index
                self.progress.emit(95, "Rebuilding classical MIR content recommender index...")
                rebuild_content_pipeline(
                    session,
                    scaler_path=Path("data/content_scaler.pkl"),
                    pca_path=Path("data/content_pca.pkl"),
                    index_path=Path("data/content_index.bin"),
                )

                self.progress.emit(100, "Done.")
                self.finished.emit(new_songs_count)

        except Exception as e:
            logger.error("ScanWorker crashed: %s", e)
            self.error.emit(str(e))


class RecommendWorker(QThread):
    """Background worker for querying recommendations."""

    finished = Signal(list)  # list of tuples (Song, score)
    error = Signal(str)

    def __init__(
        self,
        strategy: str,
        song_id: int,
        limit: int = 10,
        vector_index_path: str | Path = "data/vector_index.bin",
    ) -> None:
        super().__init__()
        self.strategy = strategy.lower()
        self.song_id = song_id
        self.limit = limit
        self.vector_index_path = Path(vector_index_path)

    def run(self) -> None:
        try:
            with get_session() as session:
                # Retrieve recommender from registry
                recommender = get_recommender(self.strategy)
                if not recommender:
                    self.error.emit(f"Unknown recommendation strategy: {self.strategy}")
                    return

                # If Vector or Hybrid, we need to pass the vector index path dynamically
                # using the design of VectorRecommender
                if self.strategy in ["vector", "hybrid"]:
                    # Create recommender with configured vector index path
                    recommender.index_path = self.vector_index_path
                    recommender.faiss_index = None

                results = recommender.recommend(
                    song_id=self.song_id,
                    limit=self.limit,
                    db_session=session,
                )

                # Convert tuples of (song_id, score) to tuples of (Song, score)
                detailed_results = []
                for song_id, score in results:
                    song = session.get(Song, song_id)
                    if song:
                        # detach from session to allow threading safely
                        session.expunge(song)
                        detailed_results.append((song, score))

                self.finished.emit(detailed_results)

        except Exception as e:
            logger.error("RecommendWorker crashed: %s", e)
            self.error.emit(str(e))


class AssistantWorker(QThread):
    """Background worker that orchestrates local LLM parsing, planning, and execution steps."""

    progress = Signal(str, str)            # step_name, status ("running", "success", "error")
    playlist_generated = Signal(dict)      # generated playlist details
    finished = Signal(str, list)           # final outcome message, steps execution log
    error = Signal(str)                    # error message

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def run(self) -> None:
        from app.assistant.parser import LLMParser
        from app.assistant.planner import Planner
        from app.assistant.executor import Executor
        from app.assistant.history import AssistantHistoryManager

        try:
            with get_session() as session:
                # 1. Parse natural language intent into JSON plan
                self.progress.emit("Parsing user intent using Ollama LLM...", "running")
                parser = LLMParser()
                plan_dict = parser.parse_intent(self.message, session)
                if not plan_dict or not plan_dict.get("plan"):
                    self.progress.emit("Parsing user intent using Ollama LLM...", "error")
                    self.error.emit("Could not parse or validate an action plan from prompt.")
                    return
                self.progress.emit("Parsing user intent using Ollama LLM...", "success")

                # 2. Build validated ActionPlan
                self.progress.emit("Validating action plan schemas...", "running")
                action_plan = Planner.create_plan(plan_dict)
                self.progress.emit("Validating action plan schemas...", "success")

                # 3. Execute plan steps
                def progress_cb(step_name: str, status_dict: dict) -> None:
                    status = status_dict.get("status")
                    self.progress.emit(step_name, status)

                result_dict = Executor.execute_plan(action_plan, session, progress_callback=progress_cb)

                # 4. Log conversation history
                AssistantHistoryManager.log_conversation(
                    prompt=self.message,
                    plan=plan_dict["plan"],
                    result=result_dict,
                    session=session,
                )

                # 5. Check if any playlist was generated to emit details, or fall back to search/recommendation previews
                playlist_found = False
                for step in result_dict.get("steps", []):
                    if step.get("action") == "generate_playlist" and step.get("status") == "success":
                        playlist_data = step.get("output", {})
                        self.playlist_generated.emit(playlist_data)
                        playlist_found = True
                        break

                if not playlist_found:
                    for step in result_dict.get("steps", []):
                        if step.get("action") in ["semantic_search", "search_library", "recommend_song"] and step.get("status") == "success":
                            songs = step.get("output", [])
                            if songs:
                                temp_playlist = {
                                    "id": None,
                                    "name": f"Results for: '{self.message}'",
                                    "songs_count": len(songs),
                                    "total_duration": sum((s.get("duration") or 180.0) for s in songs if isinstance(s, dict)),
                                    "strategy": step.get("action"),
                                    "songs": songs
                                }
                                self.playlist_generated.emit(temp_playlist)
                                break

                # 6. Signal completion
                if result_dict["success"]:
                    summary = "Successfully completed all execution plan steps."
                    self.finished.emit(summary, result_dict["steps"])
                else:
                    failed_step = next((s for s in result_dict["steps"] if s.get("status") == "error"), None)
                    err_msg = failed_step.get("error", "Unknown execution error") if failed_step else "Step failed"
                    self.error.emit(f"Plan execution failed at step '{failed_step.get('action') if failed_step else 'unknown'}': {err_msg}")

        except Exception as e:
            logger.error("AssistantWorker crashed: %s", e)
            self.error.emit(str(e))
