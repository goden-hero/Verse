import logging
import time
import uuid
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.assistant import LLMParser, Planner
from app.assistant.parser import (
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMJSONDecodeError,
    LLMSchemaValidationError,
)
from app.services.playlist import PlaylistService
from app.services.search import SearchService
from app.services.library import LibraryService
from app.services.recommendation import RecommendationService
from app.recommendations.selector import map_ui_to_backend_strategy

logger = logging.getLogger("music_rec.services.assistant")


class AssistantService:
    """Service handling assistant prompts and returning structured playlist responses."""

    @staticmethod
    def process_chat(
        message: str,
        session: Session,
        request_id: str | None = None,
    ) -> dict:
        """Parses user message via LLMParser and executes plan to return structured JSON."""
        clean_msg = message.strip()
        if not clean_msg:
            return {
                "message": "Please enter a valid message or prompt.",
                "success": False,
                "steps": [],
                "playlist": None,
            }

        req_id = request_id or uuid.uuid4().hex[:8]
        t_start_total = time.perf_counter()

        logger.info("\n=================== ASSISTANT TRACE MODE [%s] ===================", req_id)
        logger.info("[%s] [TRACE] REQUEST RECEIVED: '%s'", req_id, clean_msg)

        # 1. Parse prompt into plan_dict using LLMParser
        t_parser_start = time.perf_counter()
        try:
            parser = LLMParser()
            plan_dict = parser.parse_intent(clean_msg, session, request_id=req_id)
            t_parser_end = time.perf_counter()
            parser_ms = int((t_parser_end - t_parser_start) * 1000)
            logger.info("[%s] [TRACE] PARSED ACTION PLAN JSON: %s", req_id, plan_dict)

        except (LLMConnectionError, ConnectionError) as e:
            logger.warning("[%s] [TRACE] FAIL: Ollama connection error: %s", req_id, e)
            return {
                "message": f"Could not connect to Ollama server ({settings.ollama_url}). Please ensure Ollama is running locally.",
                "success": False,
                "steps": [],
                "playlist": None,
            }
        except (LLMModelNotFoundError, ValueError) as e:
            if "Model" in str(e):
                logger.warning("[%s] [TRACE] FAIL: Ollama model error: %s", req_id, e)
                return {
                    "message": f"Ollama Model Error: {str(e)}",
                    "success": False,
                    "steps": [],
                    "playlist": None,
                }
            raise
        except LLMJSONDecodeError as e:
            logger.error("[%s] [TRACE] FAIL: LLM JSON Decode Error: %s", req_id, e)
            return {
                "message": f"LLM Output Format Error: {str(e)}",
                "success": False,
                "steps": [],
                "playlist": None,
            }
        except LLMSchemaValidationError as e:
            logger.error("[%s] [TRACE] FAIL: LLM Schema Validation Error: %s", req_id, e)
            return {
                "message": f"LLM Schema Validation Error: {str(e)}",
                "success": False,
                "steps": [],
                "playlist": None,
            }
        except Exception as e:
            logger.error("[%s] [TRACE] FAIL: LLMParser unexpected error: %s", req_id, e)
            return {
                "message": f"Parsing Error: {str(e)}",
                "success": False,
                "steps": [],
                "playlist": None,
            }

        if not plan_dict or not plan_dict.get("plan"):
            logger.info("[%s] [TRACE] Empty ActionPlan generated for prompt: '%s'", req_id, clean_msg)
            return {
                "message": "I couldn't understand that request. Try asking for a mood, genre, or artist mix!",
                "success": False,
                "steps": [],
                "playlist": None,
            }

        # 2. Build validated ActionPlan
        t_executor_start = time.perf_counter()
        try:
            action_plan = Planner.create_plan(plan_dict)
            logger.info("[%s] [TRACE] VALIDATED ACTION PLAN: %s", req_id, action_plan.model_dump())
        except Exception as e:
            logger.error("[%s] [TRACE] FAIL: Planner schema validation failed: %s", req_id, e)
            return {
                "message": f"Action Plan Validation Error: {str(e)}",
                "success": False,
                "steps": [],
                "playlist": None,
            }

        # 3. Execute plan steps for web (temporary previews without persisting)
        steps_out = []
        playlist_preview = None
        main_playlist_title = f"{clean_msg.title()} Mix"
        playlist_ms = 0

        for idx, action_item in enumerate(action_plan.plan):
            action_type = action_item.action
            logger.info("[%s] [TRACE] EXECUTING ACTION #%d: '%s' | %s", req_id, idx + 1, action_type, action_item)
            try:
                out_songs = []
                preview_details = None

                if action_type == "generate_playlist":
                    main_playlist_title = action_item.playlist_name or main_playlist_title
                    strategy_mapped = map_ui_to_backend_strategy(action_item.strategy or "automatic", session=session)
                    req_len = action_item.target_length or 25
                    
                    t_pl_start = time.perf_counter()
                    logger.info("[%s] [TRACE] SERVICE INVOCATION: PlaylistService.generate_playlist_preview_details (strategy=%s, filters=%s, target_length=%d)", req_id, strategy_mapped, action_item.filters, req_len)
                    preview_details = PlaylistService.generate_playlist_preview_details(
                        strategy=strategy_mapped,
                        filters=action_item.filters or {},
                        target_length=req_len,
                        session=session,
                        name=main_playlist_title,
                    )
                    t_pl_end = time.perf_counter()
                    playlist_ms = int((t_pl_end - t_pl_start) * 1000)

                    out_songs = preview_details["songs"]
                    logger.info("[%s] [TRACE] RESULT: PlaylistService returned %d preview tracks (title: '%s')", req_id, len(out_songs), preview_details.get("name"))

                elif action_type == "semantic_search":
                    matches = SearchService.semantic_search(
                        moods=action_item.moods,
                        activities=action_item.activities,
                        energy_min=action_item.energy_min,
                        energy_max=action_item.energy_max,
                        session=session,
                    )
                    out_songs = matches
                elif action_type == "search_library":
                    matches = SearchService.ranked_metadata_search(query=action_item.query, session=session)
                    out_songs = matches
                elif action_type == "recommend_song":
                    song = LibraryService.get_song_by_title(action_item.song_title, session=session)
                    if song:
                        strategy_mapped = map_ui_to_backend_strategy(action_item.strategy or "automatic", session=session)
                        out_songs = RecommendationService.recommend(
                            song_id=song["id"],
                            strategy=strategy_mapped,
                            limit=action_item.limit or 10,
                            session=session,
                        )

                steps_out.append({
                    "action": action_type,
                    "status": "success",
                    "output": {"songs_count": len(out_songs)},
                    "error": None
                })

                if not playlist_preview:
                    if preview_details:
                        playlist_preview = preview_details
                    elif out_songs:
                        detailed_songs = []
                        for s in out_songs:
                            detailed_songs.append({
                                "id": s["id"],
                                "title": s.get("title", "Unknown"),
                                "artist": s.get("artist", "Unknown"),
                                "album": s.get("album", "Unknown"),
                                "duration": s.get("duration", 0.0),
                                "genre": s.get("original_genre") or s.get("genre") or "Unknown",
                                "artwork_available": s.get("artwork_available", False)
                            })

                        total_dur = sum((s.get("duration") or 0.0) for s in detailed_songs)
                        playlist_preview = {
                            "name": main_playlist_title,
                            "songs_count": len(detailed_songs),
                            "total_duration": total_dur,
                            "strategy": action_type,
                            "requested_length": None,
                            "found_length": len(detailed_songs),
                            "shortfall_reason": None,
                            "feedback_message": None,
                            "songs": detailed_songs
                        }

            except Exception as step_err:
                logger.error("[%s] [TRACE] FAIL executing assistant step %s: %s", req_id, action_type, step_err)
                steps_out.append({
                    "action": action_type,
                    "status": "error",
                    "output": None,
                    "error": str(step_err)
                })

        t_end_total = time.perf_counter()
        executor_ms = int((t_end_total - t_executor_start) * 1000)
        total_ms = int((t_end_total - t_start_total) * 1000)

        logger.info(
            "[%s] [TRACE] STAGE TIMINGS: Parser = %d ms | Executor = %d ms | Playlist = %d ms | Total = %d ms",
            req_id, parser_ms, executor_ms, playlist_ms, total_ms
        )
        logger.info("============================================================\n")

        # 4. Construct natural conversational message response
        if playlist_preview:
            found_count = playlist_preview.get("songs_count", 0)
            feedback = playlist_preview.get("feedback_message")

            if found_count == 0:
                if feedback:
                    msg_text = f"{feedback} Try scanning more music or searching for different moods."
                else:
                    msg_text = f"No matching songs were found in your library for '{clean_msg}'. Try scanning your music collection."
            elif feedback:
                msg_text = f"{feedback} Here's your playlist:"
            else:
                msg_text = (
                    f"Perfect choice! I've created a playlist with {found_count} tracks "
                    f"that capture the vibe of your request. Here's your playlist:"
                )
        else:
            total_songs_found = sum(
                s.get("output", {}).get("songs_count", 0)
                for s in steps_out
                if isinstance(s.get("output"), dict)
            )
            if total_songs_found == 0:
                msg_text = f"No songs matching '{clean_msg}' were found in your music library. Try scanning your music collection or trying another search."
            else:
                msg_text = f"I executed your request for '{clean_msg}' and found {total_songs_found} matching tracks."

        return {
            "message": msg_text,
            "success": True,
            "steps": steps_out,
            "playlist": playlist_preview if (playlist_preview and playlist_preview.get("songs_count", 0) > 0) else playlist_preview,
        }





    @staticmethod
    def regenerate_playlist(playlist_id: int, session: Session) -> dict:
        """Regenerates a playlist preview with a fresh selection of songs."""
        from app.database.models import Playlist
        pl = session.get(Playlist, playlist_id) if playlist_id > 0 else None
        
        name = pl.name if pl else "Regenerated Mix"
        strategy = pl.strategy if pl else "hybrid"
        prompt = pl.prompt if pl else name

        filters = {}
        if prompt:
            filters["moods"] = [prompt.lower()]

        songs = PlaylistService.generate_playlist_preview(
            strategy=strategy or "hybrid",
            filters=filters,
            target_length=20,
            session=session
        )

        total_dur = sum((s.get("duration") or 0.0) for s in songs)
        return {
            "name": f"Fresh {name}",
            "songs_count": len(songs),
            "total_duration": total_dur,
            "strategy": strategy,
            "songs": songs
        }
