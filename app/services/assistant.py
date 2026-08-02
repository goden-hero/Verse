"""AssistantService to handle AI assistant prompt processing, plan execution, and playlist regeneration."""

import logging
import time
from sqlalchemy.orm import Session
from app.assistant.executor import Executor
from app.assistant.parser import LLMParser
from app.assistant.schemas import ActionPlan
from app.identity import CurrentUser

logger = logging.getLogger("music_rec.services.assistant")


class AssistantService:
    """Service handling assistant prompts and returning structured playlist responses."""

    @staticmethod
    def process_chat(
        current_user: CurrentUser,
        message: str,
        session: Session,
        request_id: str | None = None,
    ) -> dict:
        """Parses user message via LLMParser and executes plan to return structured JSON."""
        clean_msg = message.strip()
        if not clean_msg:
            return {
                "message": "I didn't receive a prompt. Please tell me what kind of music or playlist you're looking for!",
                "success": False,
                "steps": [],
                "playlist": None,
            }

        req_id = request_id or "REQ-PROMPT"
        logger.info("\n============================================================")
        logger.info("[%s] [START] Processing assistant prompt for user %s: '%s'", req_id, current_user.id, clean_msg)
        t_start_total = time.perf_counter()

        # 1. Parse prompt into structured ActionPlan
        t_parser_start = time.perf_counter()
        parser = LLMParser(disable_health_check=True)
        try:
            raw_plan = parser.parse_intent(clean_msg, session=session, request_id=req_id)
            if raw_plan and "plan" in raw_plan:
                plan = ActionPlan.model_validate(raw_plan)
                is_fallback = False
            else:
                plan = ActionPlan(plan=[])
                is_fallback = True
        except Exception as e:
            logger.warning("[%s] LLM Parser unavailable or failed: %s", req_id, e)
            plan = ActionPlan(plan=[])
            is_fallback = True
        t_parser_end = time.perf_counter()
        parser_ms = int((t_parser_end - t_parser_start) * 1000)

        logger.info("[%s] [PARSER] Plan generated in %d ms (fallback=%s): %s", req_id, parser_ms, is_fallback, plan.model_dump())

        # 2. Execute plan steps
        t_executor_start = time.perf_counter()
        exec_res = Executor.execute_plan(current_user=current_user, plan=plan, session=session)
        t_executor_end = time.perf_counter()
        executor_ms = int((t_executor_end - t_executor_start) * 1000)

        # 3. Process execution steps for playlist previews / feedback
        playlist_preview = None
        playlist_ms = 0
        steps_out = []

        for s in exec_res.get("steps", []):
            action_type = s.get("action")
            step_status = s.get("status")
            step_output = s.get("output")
            step_err = s.get("error")

            if step_status == "success":
                if action_type == "generate_playlist" and isinstance(step_output, dict):
                    t_pl_start = time.perf_counter()
                    playlist_preview = step_output
                    t_pl_end = time.perf_counter()
                    playlist_ms += int((t_pl_end - t_pl_start) * 1000)

                steps_out.append({
                    "action": action_type,
                    "status": "success",
                    "output": step_output,
                    "error": None
                })
            else:
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
    def regenerate_playlist(
        current_user: CurrentUser,
        playlist_id: int,
        session: Session,
    ) -> dict:
        """Regenerates a playlist preview with a fresh selection of songs for current_user."""
        from app.database.models import Playlist
        from app.services.playlist import PlaylistService
        pl = (
            session.query(Playlist)
            .filter_by(id=playlist_id, user_id=current_user.id or 1)
            .first()
            if playlist_id > 0
            else None
        )
        
        name = pl.name if pl else "Regenerated Mix"
        strategy = pl.strategy if pl else "hybrid"
        prompt = pl.prompt if pl else name

        filters = {}
        if prompt:
            filters["moods"] = [prompt.lower()]

        songs = PlaylistService.generate_playlist_preview(
            current_user=current_user,
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
