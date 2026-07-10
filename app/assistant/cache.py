"""SQLite-backed response caching for LLM parsing prompts."""

import hashlib
import logging
from sqlalchemy.orm import Session
from app.database.models import LLMCache

logger = logging.getLogger("music_rec.assistant.cache")


class LLMCacheManager:
    """Retrieves and stores LLM query outcomes to prevent redundant processing."""

    @staticmethod
    def get_cached_response(prompt: str, session: Session) -> str | None:
        """Fetches response from cache by computing sha256 of the prompt."""
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        cache_entry = session.get(LLMCache, prompt_hash)
        if cache_entry:
            logger.info("LLM Cache HIT for hash %s", prompt_hash)
            return cache_entry.response
        logger.info("LLM Cache MISS for hash %s", prompt_hash)
        return None

    @staticmethod
    def cache_response(prompt: str, response: str, session: Session) -> None:
        """Persists the response string linked to the prompt's hash."""
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        cache_entry = session.get(LLMCache, prompt_hash)
        if not cache_entry:
            cache_entry = LLMCache(prompt_hash=prompt_hash, response=response)
            session.add(cache_entry)
        else:
            cache_entry.response = response
        session.commit()
        logger.info("Saved response to LLM Cache (hash %s)", prompt_hash)
