"""Utility functions for Ollama LLM integration."""

import logging
from urllib.parse import urlparse
from functools import lru_cache
import requests

logger = logging.getLogger("music_rec.utils.ollama")


@lru_cache(maxsize=32)
def resolve_ollama_model(api_url: str, configured_model: str) -> str:
    """Checks if the configured model is installed in the local Ollama instance.

    If not, it queries /api/tags to fall back to an available model.
    """
    try:
        # Use urllib.parse to robustly construct the tags endpoint URL
        parsed = urlparse(api_url)
        tags_url = f"{parsed.scheme}://{parsed.netloc}/api/tags"

        logger.info("Checking installed Ollama models at: %s", tags_url)
        response = requests.get(tags_url, timeout=2.0)
        if response.status_code == 200:
            models_data = response.json().get("models", [])
            installed_models = [m.get("name") for m in models_data if m.get("name")]

            if not installed_models:
                logger.warning("Ollama has no installed models. Defaulting to: %s", configured_model)
                return configured_model

            # 1. Exact match
            if configured_model in installed_models:
                return configured_model

            # 2. Tag-less base match (e.g. "llama3" matches "llama3:latest" or vice versa)
            configured_clean = configured_model.split(":")[0].lower()
            for model_name in installed_models:
                if model_name.split(":")[0].lower() == configured_clean:
                    logger.info("Found model matching base name: using '%s' instead of '%s'", model_name, configured_model)
                    return model_name

            # 3. Fallback to first available installed model
            fallback = installed_models[0]
            logger.warning(
                "Configured Ollama model '%s' not found. Dynamically falling back to installed model: '%s'. "
                "Installed models: %s",
                configured_model,
                fallback,
                installed_models,
            )
            return fallback
        else:
            logger.warning("Failed to query Ollama tags API (status code: %d)", response.status_code)

    except Exception as e:
        logger.debug("Failed to connect to Ollama to discover installed models: %s", e)

    return configured_model
