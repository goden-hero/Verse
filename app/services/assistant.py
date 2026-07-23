"""AssistantService managing natural language prompt parsing and web assistant execution."""

import logging
from sqlalchemy.orm import Session
from app.assistant import LLMParser, Planner
from app.services.playlist import PlaylistService
from app.services.search import SearchService
from app.services.library import LibraryService
from app.services.recommendation import RecommendationService

logger = logging.getLogger("music_rec.services.assistant")


class AssistantService:
    """Service handling assistant prompts and returning structured playlist responses."""

    @staticmethod
    def process_chat(message: str, session: Session) -> dict:
        """Parses user message via LLMParser and executes plan to return structured JSON."""
        clean_msg = message.strip()
        if not clean_msg:
            return {
                "message": "Please enter a valid message or prompt.",
                "success": False,
                "steps": [],
                "playlist": None,
            }

        # 1. Parse prompt into plan_dict using LLMParser
        try:
            parser = LLMParser()
            plan_dict = parser.parse_intent(clean_msg, session)
        except ConnectionError as e:
            logger.warning("Ollama connection error: %s", e)
            return {
                "message": "Could not connect to Ollama server. Please ensure Ollama is running locally.",
                "success": False,
                "steps": [],
                "playlist": None,
            }
        except ValueError as e:
            logger.warning("Ollama model error: %s", e)
            return {
                "message": f"Ollama model error: {str(e)}",
                "success": False,
                "steps": [],
                "playlist": None,
            }
        except Exception as e:
            logger.error("LLMParser unexpected error: %s", e)
            return {
                "message": "Failed to parse natural language intent. Please try rephrasing your request.",
                "success": False,
                "steps": [],
                "playlist": None,
            }

        if not plan_dict or not plan_dict.get("plan"):
            return {
                "message": "I couldn't understand that request. Try asking for a mood, genre, or artist mix!",
                "success": False,
                "steps": [],
                "playlist": None,
            }

        # 2. Build validated ActionPlan
        try:
            action_plan = Planner.create_plan(plan_dict)
        except Exception as e:
            logger.error("Planner schema validation failed: %s", e)
            return {
                "message": "Failed to validate action plan schemas.",
                "success": False,
                "steps": [],
                "playlist": None,
            }

        # 3. Execute plan steps for web (temporary previews without persisting)
        steps_out = []
        playlist_preview = None
        main_playlist_title = f"{clean_msg.title()} Mix"

        for idx, action_item in enumerate(action_plan.plan):
            action_type = action_item.action
            try:
                out_songs = []
                preview_details = None

                if action_type == "generate_playlist":
                    main_playlist_title = action_item.playlist_name or main_playlist_title
                    strategy_mapped = action_item.strategy or "hybrid"
                    req_len = action_item.target_length or 20
                    preview_details = PlaylistService.generate_playlist_preview_details(
                        strategy=strategy_mapped,
                        filters=action_item.filters or {},
                        target_length=req_len,
                        session=session,
                        name=main_playlist_title,
                    )
                    out_songs = preview_details["songs"]
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
                        out_songs = RecommendationService.recommend(
                            song_id=song["id"],
                            strategy=action_item.strategy or "hybrid",
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
                logger.error("Failed executing assistant step %s: %s", action_type, step_err)
                steps_out.append({
                    "action": action_type,
                    "status": "error",
                    "output": None,
                    "error": str(step_err)
                })

        # 4. Construct natural conversational message response
        if playlist_preview:
            if playlist_preview.get("feedback_message"):
                msg_text = f"{playlist_preview['feedback_message']} Here's your playlist:"
            else:
                msg_text = (
                    f"Perfect choice! I've created a playlist with {playlist_preview['songs_count']} tracks "
                    f"that capture the vibe of your request. Here's your playlist:"
                )
        else:
            msg_text = f"I executed your request for '{clean_msg}'."

        return {
            "message": msg_text,
            "success": True,
            "steps": steps_out,
            "playlist": playlist_preview
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
