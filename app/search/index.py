"""FAISS-based vector similarity search index for song embeddings."""

import logging
from pathlib import Path
import faiss
import numpy as np

logger = logging.getLogger("music_rec.search.index")

# Dimension of our embedding vectors
EMBEDDING_DIM = 512


class FAISSIndex:
    """Wrapper class managing a persistent FAISS vector index for fast similarity search."""

    def __init__(self, index_path: str | Path, dim: int = 512) -> None:
        """Initializes the FAISS index.

        Args:
            index_path: Local filesystem path where the FAISS index is saved.
            dim: Dimension of the vectors in this index (default: 512).
        """
        self.index_path = Path(index_path)
        self.dim = dim
        self.index: faiss.IndexIDMap | None = None
        self._initialize_empty_index()

    def _initialize_empty_index(self) -> None:
        """Creates a fresh, empty Inner Product index wrapped in an ID mapper."""
        # IndexFlatIP computes Inner Product. Since our embeddings are L2 unit-normalized,
        # Inner Product is mathematically equivalent to Cosine Similarity.
        flat_index = faiss.IndexFlatIP(self.dim)
        # Wrap in IndexIDMap to associate vectors with database song IDs
        self.index = faiss.IndexIDMap(flat_index)

    def load(self) -> bool:
        """Loads the FAISS index from disk. Returns True if successful, False otherwise."""
        if not self.index_path.exists():
            logger.info("No existing FAISS index found at %s. Starting fresh.", self.index_path)
            self._initialize_empty_index()
            return False

        try:
            # FAISS C++ load call
            loaded = faiss.read_index(str(self.index_path))
            # Verify it's an IndexIDMap
            if isinstance(loaded, faiss.IndexIDMap):
                self.index = loaded
            else:
                # Wrap it if it isn't
                self.index = faiss.IndexIDMap(loaded)
            logger.info("Successfully loaded FAISS index containing %d vectors from %s",
                        self.index.ntotal, self.index_path)
            return True
        except Exception as e:
            logger.error("Failed to load FAISS index from %s: %s", self.index_path, e)
            self._initialize_empty_index()
            return False

    def save(self) -> bool:
        """Saves the FAISS index to disk. Returns True if successful, False otherwise."""
        try:
            # Create parent directories if they don't exist
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            # FAISS C++ save call
            faiss.write_index(self.index, str(self.index_path))
            logger.info("Successfully saved FAISS index containing %d vectors to %s",
                        self.index.ntotal, self.index_path)
            return True
        except Exception as e:
            logger.error("Failed to save FAISS index to %s: %s", self.index_path, e)
            return False

    def add_songs(self, song_ids: list[int], embeddings: list[list[float]]) -> None:
        """Adds song embeddings with their corresponding database IDs to the index.

        Args:
            song_ids: List of database song primary keys.
            embeddings: List of 512-dimensional embedding lists.
        """
        if not song_ids or not embeddings:
            return

        if len(song_ids) != len(embeddings):
            raise ValueError("Size mismatch: song_ids and embeddings must have the same length.")

        # Cast to NumPy arrays with appropriate types
        vectors = np.array(embeddings, dtype=np.float32)
        ids = np.array(song_ids, dtype=np.int64)

        # Validate dimensions
        if vectors.shape[1] != self.dim:
            raise ValueError(f"Embedding dimension mismatch: expected {self.dim}, got {vectors.shape[1]}")

        # Add to index
        self.index.add_with_ids(vectors, ids)
        logger.info("Added %d songs to the FAISS index. Total index count: %d",
                    len(song_ids), self.index.ntotal)

    def remove_songs(self, song_ids: list[int]) -> None:
        """Removes songs from the index by their database IDs.

        Args:
            song_ids: List of database song primary keys to remove.
        """
        if not song_ids:
            return

        ids = np.array(song_ids, dtype=np.int64)
        # FAISS C++ deletion call
        removed_count = self.index.remove_ids(ids)
        logger.info("Removed %d vectors from FAISS index. Total index count: %d",
                    removed_count, self.index.ntotal)

    def search(self, query_embedding: list[float], k: int = 5) -> list[tuple[int, float]]:
        """Searches the index for the k most similar songs.

        Args:
            query_embedding: 512-dimensional query vector.
            k: Number of nearest neighbors to retrieve.

        Returns:
            List of tuples of (song_id, similarity_score) sorted by similarity descending.
        """
        if self.index.ntotal == 0:
            return []

        # Format query vector
        query = np.array([query_embedding], dtype=np.float32)
        # Search
        # distances returns the inner products (cosine similarities since vectors are unit normalized)
        distances, ids = self.index.search(query, k)

        results = []
        for idx, score in zip(ids[0], distances[0]):
            # FAISS returns -1 for empty slots if k > total index count
            if idx != -1:
                # Clip similarity score between -1.0 and 1.0
                clipped_score = float(np.clip(score, -1.0, 1.0))
                results.append((int(idx), clipped_score))

        return results
