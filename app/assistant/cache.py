"""SQLite-backed response caching for LLM parsing prompts."""

import hashlib
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import LLMCache

logger = logging.getLogger("music_rec.assistant.cache")


class LLMCacheManager:
    """Retrieves and stores LLM query outcomes to prevent redundant processing."""

    @staticmethod
    def get_cached_response(
        prompt: str,
        session: Session,
        parser_version: str = "4",
        model: str = "",
        max_age_days: int = 90,
    ) -> str | None:
        """Fetches response from cache by computing sha256 of PARSER_VERSION, model, and prompt."""
        full_key = f"{parser_version}:{model}:{prompt.strip().lower()}"
        prompt_hash = hashlib.sha256(full_key.encode("utf-8")).hexdigest()
        cache_entry = session.get(LLMCache, prompt_hash)

        if cache_entry:
            # Check TTL aging (max_age_days)
            entry_time = getattr(cache_entry, "last_used_at", None) or getattr(cache_entry, "created_at", None)
            if entry_time:
                age = (datetime.utcnow() - entry_time).days
                if age > max_age_days:
                    logger.info("LLM Cache EXPIRED for hash %s (age %d days > %d)", prompt_hash, age, max_age_days)
                    session.delete(cache_entry)
                    session.commit()
                    return None

            # Cache hit: update usage metadata if fields exist
            now = datetime.utcnow()
            if hasattr(cache_entry, "last_used_at"):
                cache_entry.last_used_at = now
            if hasattr(cache_entry, "usage_count"):
                cache_entry.usage_count = (cache_entry.usage_count or 1) + 1
            session.commit()

            logger.info("[TRACE] 2. CACHE HIT for hash %s (key: '%s')", prompt_hash, full_key)
            return cache_entry.response

        logger.info("[TRACE] 2. CACHE MISS for hash %s (key: '%s')", prompt_hash, full_key)
        return None


    @staticmethod
    def cache_response(
        prompt: str,
        response: str,
        session: Session,
        parser_version: str = "4",
        model: str = "",
    ) -> None:
        """Persists the response string linked to the versioned prompt hash."""
        full_key = f"{parser_version}:{model}:{prompt.strip().lower()}"
        prompt_hash = hashlib.sha256(full_key.encode("utf-8")).hexdigest()
        cache_entry = session.get(LLMCache, prompt_hash)
        now = datetime.utcnow()

        if not cache_entry:
            cache_entry = LLMCache(
                prompt_hash=prompt_hash,
                prompt=prompt,
                model=model,
                parser_version=parser_version,
                response=response,
                created_at=now,
                last_used_at=now,
                usage_count=1,
            )
            session.add(cache_entry)
        else:
            cache_entry.response = response
            if hasattr(cache_entry, "last_used_at"):
                cache_entry.last_used_at = now
            if hasattr(cache_entry, "usage_count"):
                cache_entry.usage_count = (cache_entry.usage_count or 1) + 1

        session.commit()
        logger.info("Saved response to LLM Cache (hash %s, version %s)", prompt_hash, parser_version)

