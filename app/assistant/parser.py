"""LLM Parser module responsible for translating natural language into structured JSON actions."""

import json
import logging
import time
import requests
from datetime import datetime
from urllib.parse import urlparse
from sqlalchemy.orm import Session
from pydantic import ValidationError
from app.config.settings import settings
from app.assistant.schemas import ActionPlan
from app.assistant.prompts import SYSTEM_PROMPT, RETRY_PROMPT_TEMPLATE
from app.assistant.cache import LLMCacheManager
from app.utils.ollama import resolve_ollama_model

logger = logging.getLogger("music_rec.assistant.parser")


class LLMParser:
    """Interacts with local Ollama instance to translate text input into validated plans."""

    _health_checked = False
    _is_healthy = False

    def __init__(
        self,
        api_url: str | None = None,
        model: str | None = None,
        disable_health_check: bool = False,
    ) -> None:
        self.api_url = api_url or settings.ollama_url
        configured_model = model or settings.ollama_model
        self.model = resolve_ollama_model(self.api_url, configured_model)
        self.disable_health_check = disable_health_check

    def verify_health(self) -> None:
        """Verifies Ollama connectivity and model availability.
        
        Runs only once per session if successful. Raises ConnectionError or ValueError.
        """
        if self.disable_health_check:
            return

        if LLMParser._health_checked and LLMParser._is_healthy:
            return

        parsed = urlparse(self.api_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        # 1. Connection check with a fast timeout
        try:
            resp = requests.get(base_url, timeout=settings.ollama_connect_timeout)
        except requests.exceptions.RequestException as e:
            raise ConnectionError(
                f"Ollama server is unreachable at {base_url}. Please make sure Ollama is running."
            ) from e
            
        # 2. Check if the model is installed
        tags_url = f"{base_url}/api/tags"
        try:
            resp = requests.get(tags_url, timeout=settings.ollama_connect_timeout)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                installed_names = [m.get("name") for m in models if m.get("name")]
                
                # Check for exact or base match
                found = False
                if self.model in installed_names:
                    found = True
                else:
                    configured_clean = self.model.split(":")[0].lower()
                    for name in installed_names:
                        if name.split(":")[0].lower() == configured_clean:
                            found = True
                            break
                            
                if not found:
                    raise ValueError(
                        f"Model '{self.model}' is not installed in Ollama. "
                        f"Installed models: {installed_names}. Please download it or configure an available model."
                    )
            else:
                raise ValueError(f"Ollama tags API returned HTTP status {resp.status_code}")
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to query Ollama tags API at {tags_url}: {e}") from e

        # 3. Check if the model is loaded in memory. If not, preload it.
        try:
            ps_url = f"{base_url}/api/ps"
            ps_resp = requests.get(ps_url, timeout=settings.ollama_connect_timeout)
            if ps_resp.status_code == 200:
                loaded_models = ps_resp.json().get("models", [])
                loaded_names = [m.get("name") for m in loaded_models if m.get("name")]
                
                model_is_loaded = False
                if self.model in loaded_names:
                    model_is_loaded = True
                else:
                    configured_clean = self.model.split(":")[0].lower()
                    for name in loaded_names:
                        if name.split(":")[0].lower() == configured_clean:
                            model_is_loaded = True
                            break
                
                if not model_is_loaded:
                    logger.info("Model '%s' is not loaded in memory. Preloading to memory...", self.model)
                    preload_url = f"{base_url}/api/generate"
                    preload_payload = {
                        "model": self.model,
                        "keep_alive": settings.ollama_keep_alive
                    }
                    # Synchronously wait up to 30.0s for the first-time preloading
                    requests.post(
                        preload_url,
                        json=preload_payload,
                        timeout=(settings.ollama_connect_timeout, 30.0)
                    )
                    logger.info("Model '%s' preloaded successfully.", self.model)
        except Exception as e:
            logger.warning("Failed to check or preload model '%s': %s", self.model, e)

        # If we got here, it's healthy
        LLMParser._health_checked = True
        LLMParser._is_healthy = True

    def parse_intent(self, user_prompt: str, session: Session, max_retries: int = 3) -> dict | None:
        """Parses the user prompt into a validated dictionary matching ActionPlan schema.

        Leverages SQLite cache and implements error-aware retries for schema conformance.
        """
        # 1. Check cache first
        cached = LLMCacheManager.get_cached_response(user_prompt, session)
        if cached:
            try:
                parsed = json.loads(cached)
                # Ensure it still validates against the current schema
                ActionPlan.model_validate(parsed)
                return parsed
            except Exception as e:
                logger.warning("Cached plan validation failed, recalculating: %s", e)

        # Verify connectivity and model availability before first request
        self.verify_health()

        # 2. Prepare payload for Ollama
        current_prompt = f"{SYSTEM_PROMPT}\nUser: {user_prompt}"
        response_text = ""

        for attempt in range(max_retries):
            payload = {
                "model": self.model,
                "prompt": current_prompt,
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_predict": 256,
                },
                "keep_alive": settings.ollama_keep_alive,
            }

            start_time_dt = datetime.now()
            start_time_str = start_time_dt.isoformat()
            client_start = time.perf_counter()
            
            prompt_len = len(current_prompt)
            # Estimate tokens: ~4 chars per token is a standard rough heuristic
            approx_prompt_tokens = int(prompt_len / 4)
            
            success = False
            error_msg = None
            
            ollama_total_sec = 0.0
            ollama_load_sec = 0.0
            ollama_prompt_eval_sec = 0.0
            ollama_eval_sec = 0.0
            prompt_eval_count = approx_prompt_tokens
            eval_count = 0

            try:
                logger.info(
                    "Querying LLM Parser (model: %s, attempt %d/%d)...",
                    self.model,
                    attempt + 1,
                    max_retries,
                )
                response = requests.post(
                    self.api_url, 
                    json=payload, 
                    timeout=(settings.ollama_connect_timeout, settings.ollama_read_timeout)
                )
                
                client_duration = time.perf_counter() - client_start
                end_time_str = datetime.now().isoformat()
                
                if response.status_code != 200:
                    error_msg = f"API request failed (status {response.status_code}): {response.text}"
                    logger.warning(
                        "LLM Parser API request failed (status %d) on attempt %d: %s",
                        response.status_code,
                        attempt + 1,
                        response.text,
                    )
                    
                    # Structured log output for HTTP error
                    logger.info(
                        "\nParser Request\n"
                        "----------------------------\n"
                        "Prompt length: %d chars (approx %d tokens)\n"
                        "Model: %s\n"
                        "Start time: %s\n"
                        "End time: %s\n"
                        "Client total duration: %.4f s\n"
                        "Success/Failure: Failure\n"
                        "Error (if any): %s\n"
                        "----------------------------",
                        prompt_len,
                        approx_prompt_tokens,
                        self.model,
                        start_time_str,
                        end_time_str,
                        client_duration,
                        error_msg
                    )
                    
                    if response.status_code == 404 and "not found" in response.text.lower():
                        try:
                            # Attempt to query available models to suggest to the user
                            tags_url = self.api_url.replace("/generate", "").replace("/api/generate", "") + "/api/tags"
                            tags_resp = requests.get(tags_url, timeout=5.0)
                            if tags_resp.status_code == 200:
                                models = [m.get("name") for m in tags_resp.json().get("models", [])]
                                logger.error(
                                    "Model '%s' not found. Installed local models: %s. "
                                    "Please configure one of these models in the Settings tab.",
                                    self.model, models
                                )
                        except Exception as tag_err:
                            logger.debug("Failed to fetch available tags: %s", tag_err)
                    continue

                data = response.json()
                response_text = data.get("response", "").strip()
                if not response_text and "thinking" in data:
                    response_text = data.get("thinking", "").strip()

                response_len = len(response_text)
                
                # Extract Ollama stats
                total_duration = data.get("total_duration", 0)
                load_duration = data.get("load_duration", 0)
                prompt_eval_duration = data.get("prompt_eval_duration", 0)
                eval_duration = data.get("eval_duration", 0)
                
                prompt_eval_count = data.get("prompt_eval_count", approx_prompt_tokens)
                eval_count = data.get("eval_count", 0)
                
                ollama_total_sec = total_duration / 1e9
                ollama_load_sec = load_duration / 1e9
                ollama_prompt_eval_sec = prompt_eval_duration / 1e9
                ollama_eval_sec = eval_duration / 1e9
                network_overhead = max(0.0, client_duration - ollama_total_sec)

                if not response_text:
                    error_msg = "Empty response received from parser"
                    logger.warning("Empty response from parser on attempt %d.", attempt + 1)
                    
                    # Structured log output for empty response
                    logger.info(
                        "\nParser Request\n"
                        "----------------------------\n"
                        "Prompt length: %d chars (approx %d tokens)\n"
                        "Model: %s\n"
                        "Start time: %s\n"
                        "End time: %s\n"
                        "Client total duration: %.4f s\n"
                        "Ollama total duration: %.4f s\n"
                        "  - Connection/Network overhead: %.4f s\n"
                        "  - Model load duration: %.4f s\n"
                        "  - Prompt evaluation duration: %.4f s\n"
                        "  - Token generation duration: %.4f s\n"
                        "Success/Failure: Failure\n"
                        "Error (if any): %s\n"
                        "----------------------------",
                        prompt_len,
                        prompt_eval_count,
                        self.model,
                        start_time_str,
                        end_time_str,
                        client_duration,
                        ollama_total_sec,
                        network_overhead,
                        ollama_load_sec,
                        ollama_prompt_eval_sec,
                        ollama_eval_sec,
                        error_msg
                    )
                    continue

                # 3. Parse and validate JSON
                parsed_json = json.loads(response_text)
                # Validates against Pydantic ActionPlan model
                ActionPlan.model_validate(parsed_json)

                success = True
                
                # Structured log output for success
                logger.info(
                    "\nParser Request\n"
                    "----------------------------\n"
                    "Prompt length: %d chars (approx %d tokens)\n"
                    "Model: %s\n"
                    "Start time: %s\n"
                    "End time: %s\n"
                    "Client total duration: %.4f s\n"
                    "Ollama total duration: %.4f s\n"
                    "  - Connection/Network overhead: %.4f s\n"
                    "  - Model load duration: %.4f s\n"
                    "  - Prompt evaluation duration: %.4f s\n"
                    "  - Token generation duration: %.4f s\n"
                    "Response tokens: %d tokens\n"
                    "Response length: %d chars\n"
                    "Success/Failure: Success\n"
                    "Error (if any): None\n"
                    "----------------------------",
                    prompt_len,
                    prompt_eval_count,
                    self.model,
                    start_time_str,
                    end_time_str,
                    client_duration,
                    ollama_total_sec,
                    network_overhead,
                    ollama_load_sec,
                    ollama_prompt_eval_sec,
                    ollama_eval_sec,
                    eval_count,
                    response_len
                )

                # Successful validation - write to cache and return
                LLMCacheManager.cache_response(user_prompt, response_text, session)
                return parsed_json

            except ValidationError as e:
                error_msg = f"Pydantic Validation Error: {str(e)}"
                logger.warning(
                    "Pydantic Validation failed on attempt %d: %s. Response was: %s",
                    attempt + 1,
                    e,
                    response_text,
                )
                
                # Log structured failure
                logger.info(
                    "\nParser Request\n"
                    "----------------------------\n"
                    "Prompt length: %d chars (approx %d tokens)\n"
                    "Model: %s\n"
                    "Start time: %s\n"
                    "End time: %s\n"
                    "Client total duration: %.4f s\n"
                    "Success/Failure: Failure\n"
                    "Error (if any): %s\n"
                    "----------------------------",
                    prompt_len,
                    prompt_eval_count,
                    self.model,
                    start_time_str,
                    datetime.now().isoformat(),
                    time.perf_counter() - client_start,
                    error_msg
                )
                
                # Construct error-aware retry prompt
                error_details = str(e)
                retry_instruct = RETRY_PROMPT_TEMPLATE.format(error_details=error_details)
                current_prompt = (
                    f"{SYSTEM_PROMPT}\nUser: {user_prompt}\n"
                    f"Assistant: {response_text}\n"
                    f"System: {retry_instruct}"
                )
            except json.JSONDecodeError as e:
                error_msg = f"JSON Decode Error: {str(e)}"
                logger.warning("JSON decode failure on attempt %d: %s. Content: %s", attempt + 1, e, response_text)
                
                # Log structured failure
                logger.info(
                    "\nParser Request\n"
                    "----------------------------\n"
                    "Prompt length: %d chars (approx %d tokens)\n"
                    "Model: %s\n"
                    "Start time: %s\n"
                    "End time: %s\n"
                    "Client total duration: %.4f s\n"
                    "Success/Failure: Failure\n"
                    "Error (if any): %s\n"
                    "----------------------------",
                    prompt_len,
                    prompt_eval_count,
                    self.model,
                    start_time_str,
                    datetime.now().isoformat(),
                    time.perf_counter() - client_start,
                    error_msg
                )
                
                current_prompt = (
                    f"{SYSTEM_PROMPT}\nUser: {user_prompt}\n"
                    f"Assistant: {response_text}\n"
                    f"System: Your response was not valid JSON. Please return valid JSON matching the schema."
                )
            except requests.exceptions.ConnectTimeout as e:
                error_msg = f"Connection Timeout: {str(e)}"
                logger.error("Connection timeout to Ollama parser on attempt %d: %s", attempt + 1, e)
                
                # Log structured failure
                logger.info(
                    "\nParser Request\n"
                    "----------------------------\n"
                    "Prompt length: %d chars (approx %d tokens)\n"
                    "Model: %s\n"
                    "Start time: %s\n"
                    "End time: %s\n"
                    "Client total duration: %.4f s\n"
                    "Success/Failure: Failure\n"
                    "Error (if any): %s\n"
                    "----------------------------",
                    prompt_len,
                    prompt_eval_count,
                    self.model,
                    start_time_str,
                    datetime.now().isoformat(),
                    time.perf_counter() - client_start,
                    error_msg
                )
                raise ConnectionError("Connection to Ollama timed out. Check if Ollama is running.") from e
            except requests.exceptions.ReadTimeout as e:
                error_msg = f"Read/Inference Timeout: {str(e)}"
                logger.error("Read/Inference timeout from Ollama parser on attempt %d: %s", attempt + 1, e)
                
                # Log structured failure
                logger.info(
                    "\nParser Request\n"
                    "----------------------------\n"
                    "Prompt length: %d chars (approx %d tokens)\n"
                    "Model: %s\n"
                    "Start time: %s\n"
                    "End time: %s\n"
                    "Client total duration: %.4f s\n"
                    "Success/Failure: Failure\n"
                    "Error (if any): %s\n"
                    "----------------------------",
                    prompt_len,
                    prompt_eval_count,
                    self.model,
                    start_time_str,
                    datetime.now().isoformat(),
                    time.perf_counter() - client_start,
                    error_msg
                )
                
                if attempt == max_retries - 1:
                    raise TimeoutError(f"Ollama inference timed out after {settings.ollama_read_timeout}s.") from e
            except requests.exceptions.RequestException as e:
                error_msg = f"Request Exception: {str(e)}"
                logger.warning("Connection failure to Ollama parser on attempt %d: %s", attempt + 1, e)
                
                # Log structured failure
                logger.info(
                    "\nParser Request\n"
                    "----------------------------\n"
                    "Prompt length: %d chars (approx %d tokens)\n"
                    "Model: %s\n"
                    "Start time: %s\n"
                    "End time: %s\n"
                    "Client total duration: %.4f s\n"
                    "Success/Failure: Failure\n"
                    "Error (if any): %s\n"
                    "----------------------------",
                    prompt_len,
                    prompt_eval_count,
                    self.model,
                    start_time_str,
                    datetime.now().isoformat(),
                    time.perf_counter() - client_start,
                    error_msg
                )
                raise ConnectionError(f"Failed to communicate with Ollama server: {e}") from e
            except Exception as e:
                error_msg = f"Unexpected Error: {str(e)}"
                logger.error("Unexpected error in LLMParser on attempt %d: %s", attempt + 1, e)
                
                # Log structured failure
                logger.info(
                    "\nParser Request\n"
                    "----------------------------\n"
                    "Prompt length: %d chars (approx %d tokens)\n"
                    "Model: %s\n"
                    "Start time: %s\n"
                    "End time: %s\n"
                    "Client total duration: %.4f s\n"
                    "Success/Failure: Failure\n"
                    "Error (if any): %s\n"
                    "----------------------------",
                    prompt_len,
                    prompt_eval_count,
                    self.model,
                    start_time_str,
                    datetime.now().isoformat(),
                    time.perf_counter() - client_start,
                    error_msg
                )
                break

        logger.error("All %d parser attempts failed or produced invalid plans.", max_retries)
        return None

    def generate_playlist_name(
        self,
        songs: list[dict],
        prompt: str | None,
        filters: dict,
        default_name: str,
    ) -> tuple[str, str | None]:
        """Generates evocative creative title and description for a playlist based on final selected songs.
        
        Runs strictly AFTER song selection. Returns (title, description).
        Falls back to (default_name, None) on any LLM error or timeout.
        """
        if not songs:
            return default_name, None

        moods = filters.get("moods", [])
        activities = filters.get("activities", [])

        song_descriptions = []
        artists = set()
        genres = set()
        for s in songs[:15]:
            title = s.get("title", "Unknown")
            artist = s.get("artist", "Unknown")
            song_descriptions.append(f"'{title}' by {artist}")
            if artist and artist != "Unknown":
                artists.add(artist)
            g = s.get("original_genre") or s.get("genre")
            if g and g != "Unknown":
                genres.add(g)

        llm_prompt = (
            "You are an expert music curator and album title writer.\n"
            "Generate a creative, evocative title and a 1-sentence description for a music playlist.\n"
            f"User Prompt/Theme: {prompt or default_name}\n"
            f"Moods: {', '.join(moods) if moods else 'Various'}\n"
            f"Activities: {', '.join(activities) if activities else 'General'}\n"
            f"Genres: {', '.join(list(genres)[:5]) if genres else 'Various'}\n"
            f"Artists: {', '.join(list(artists)[:5]) if artists else 'Various'}\n"
            f"Final Selected Songs:\n- " + "\n- ".join(song_descriptions[:10]) + "\n\n"
            "Output ONLY a valid JSON object matching this schema:\n"
            "{\n"
            '  "title": "Creative Evocative Title",\n'
            '  "description": "Short 1-sentence description of the playlist vibe."\n'
            "}\n"
            "Do NOT output generic titles like 'Workout Mix' or 'Chill Playlist'. Output atmospheric names like 'Midnight Neon', 'Steel & Sweat', 'Echoes of Autumn', 'Clouds Over Kyoto'."
        )

        payload = {
            "model": self.model,
            "prompt": llm_prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.7,
            }
        }

        try:
            resp = requests.post(
                self.api_url,
                json=payload,
                timeout=settings.ollama_read_timeout,
            )
            if resp.status_code == 200:
                body = resp.json()
                raw_text = body.get("response", "")
                parsed = json.loads(raw_text)
                title = parsed.get("title")
                description = parsed.get("description")
                if title and isinstance(title, str) and title.strip():
                    return title.strip(), description if isinstance(description, str) else None
        except Exception as err:
            logger.warning("LLM playlist naming failed, falling back to default name: %s", err)

        return default_name, None

