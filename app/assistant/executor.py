"""Executor running the validated ActionPlan steps using the Service Layer."""

import logging
import random
from sqlalchemy.orm import Session
from app.assistant.schemas import ActionPlan
from app.services import (
    HistoryService,
    LibraryService,
    PlaybackService,
    PlaylistService,
    RecommendationService,
    SearchService,
)

logger = logging.getLogger("music_rec.assistant.executor")


class Executor:
    """Translates the ActionPlan sequences into sequential calls against backend Service Layer."""

    @staticmethod
    def execute_plan(plan: ActionPlan, session: Session, progress_callback=None) -> dict:
        """Executes the sequence of steps and returns outcome status dictionary."""
        results = []
        success = True

        for idx, action_item in enumerate(plan.plan):
            action_type = action_item.action
            step_name = f"Step {idx + 1}: {action_type}"

            if progress_callback:
                progress_callback(step_name, {"status": "running"})

            logger.info("Executing plan step: %s", action_type)

            try:
                out = None
                if action_type == "search_library":
                    out = SearchService.metadata_search(query=action_item.query, session=session)
                elif action_type == "semantic_search":
                    out = SearchService.semantic_search(
                        moods=action_item.moods,
                        activities=action_item.activities,
                        energy_min=action_item.energy_min,
                        energy_max=action_item.energy_max,
                        session=session,
                    )
                elif action_type == "recommend_song":
                    song = LibraryService.get_song_by_title(action_item.song_title, session=session)
                    if song:
                        out = RecommendationService.recommend(
                            song_id=song["id"],
                            strategy=action_item.strategy,
                            limit=action_item.limit,
                            session=session,
                        )
                    else:
                        raise ValueError(f"Song not found: {action_item.song_title}")
                elif action_type == "generate_playlist":
                    out = PlaylistService.generate_playlist(
                        name=action_item.playlist_name,
                        strategy=action_item.strategy,
                        filters=action_item.filters,
                        target_length=action_item.target_length,
                        session=session,
                    )
                elif action_type == "play_playlist":
                    playlists = PlaylistService.get_playlists(session=session)
                    target = next(
                        (p for p in playlists if p["name"].lower() == action_item.playlist_name.lower()),
                        None,
                    )
                    if target:
                        songs = PlaylistService.get_playlist_songs(target["id"], session=session)
                        if songs:
                            handler = PlaybackService._handler
                            if handler:
                                handler.playback_queue = [s["id"] for s in songs]
                                handler.current_queue_index = 0
                                PlaybackService.play_song(songs[0]["id"])
                                out = {"status": "playing", "songs_count": len(songs)}
                            else:
                                out = {"status": "no_ui_handler"}
                        else:
                            raise ValueError(f"Playlist '{action_item.playlist_name}' has no songs.")
                    else:
                        raise ValueError(f"Playlist not found: {action_item.playlist_name}")
                elif action_type == "play_song":
                    song = LibraryService.get_song_by_title(action_item.song_title, session=session)
                    if song:
                        handler = PlaybackService._handler
                        if handler:
                            handler.playback_queue = [song["id"]]
                            handler.current_queue_index = 0
                            PlaybackService.play_song(song["id"])
                            out = {"status": "playing", "song_title": song["title"]}
                        else:
                            out = {"status": "no_ui_handler"}
                    else:
                        raise ValueError(f"Song not found: {action_item.song_title}")
                elif action_type == "pause":
                    PlaybackService.pause()
                    out = {"status": "paused"}
                elif action_type == "resume":
                    PlaybackService.resume()
                    out = {"status": "resumed"}
                elif action_type == "skip":
                    PlaybackService.skip()
                    out = {"status": "skipped"}
                elif action_type == "like_song":
                    song = LibraryService.get_song_by_title(action_item.song_title, session=session)
                    if song:
                        HistoryService.set_like_status(song_id=song["id"], liked=True, session=session)
                        out = {"status": "liked", "song_title": song["title"]}
                    else:
                        raise ValueError(f"Song not found: {action_item.song_title}")
                elif action_type == "unlike_song":
                    song = LibraryService.get_song_by_title(action_item.song_title, session=session)
                    if song:
                        HistoryService.set_like_status(song_id=song["id"], liked=False, session=session)
                        out = {"status": "unliked", "song_title": song["title"]}
                    else:
                        raise ValueError(f"Song not found: {action_item.song_title}")
                elif action_type == "shuffle_queue":
                    handler = PlaybackService._handler
                    if handler and len(handler.playback_queue) > 1:
                        q = list(handler.playback_queue)
                        current_song = q[handler.current_queue_index]
                        other = [sid for sid in q if sid != current_song]
                        random.shuffle(other)
                        handler.playback_queue = [current_song] + other
                        handler.current_queue_index = 0
                        out = {"status": "shuffled", "queue_length": len(handler.playback_queue)}
                    else:
                        out = {"status": "skipped_shuffle"}
                elif action_type == "repeat_queue":
                    handler = PlaybackService._handler
                    if handler:
                        handler.repeat_queue_mode = not handler.repeat_queue_mode
                        out = {"status": "toggled_repeat", "repeat": handler.repeat_queue_mode}
                    else:
                        out = {"status": "no_ui_handler"}
                elif action_type == "scan_library":
                    LibraryService.scan_library(action_item.folder_path, session=session)
                    out = {"status": "scan_started"}
                elif action_type == "open_playlist":
                    playlists = PlaylistService.get_playlists(session=session)
                    target = next(
                        (p for p in playlists if p["name"].lower() == action_item.playlist_name.lower()),
                        None,
                    )
                    if target:
                        handler = PlaybackService._handler
                        if handler and hasattr(handler, "playlists_tab"):
                            handler.tabs.setCurrentWidget(handler.playlists_tab)
                            handler.playlists_tab.open_playlist_by_id(target["id"])
                            out = {"status": "opened_playlist", "playlist_id": target["id"]}
                        else:
                            out = {"status": "no_ui_handler"}
                    else:
                        raise ValueError(f"Playlist not found: {action_item.playlist_name}")
                elif action_type == "delete_playlist":
                    playlists = PlaylistService.get_playlists(session=session)
                    target = next(
                        (p for p in playlists if p["name"].lower() == action_item.playlist_name.lower()),
                        None,
                    )
                    if target:
                        PlaylistService.delete_playlist(target["id"], session=session)
                        out = {"status": "deleted_playlist", "playlist_id": target["id"]}
                    else:
                        raise ValueError(f"Playlist not found: {action_item.playlist_name}")
                elif action_type == "save_playlist":
                    out = {"status": "saved"}
                elif action_type == "rename_playlist":
                    playlists = PlaylistService.get_playlists(session=session)
                    target = next(
                        (p for p in playlists if p["name"].lower() == action_item.playlist_name.lower()),
                        None,
                    )
                    if target:
                        PlaylistService.rename_playlist(target["id"], action_item.new_name, session=session)
                        out = {"status": "renamed_playlist", "playlist_id": target["id"]}
                    else:
                        raise ValueError(f"Playlist not found: {action_item.playlist_name}")
                else:
                    raise NotImplementedError(f"Action '{action_type}' execution not configured.")

                results.append({"action": action_type, "status": "success", "output": out})
                if progress_callback:
                    progress_callback(step_name, {"status": "success", "output": out})
            except Exception as e:
                logger.error("Failed executing plan step: %s. Error: %s", action_type, e)
                results.append({"action": action_type, "status": "error", "error": str(e)})
                if progress_callback:
                    progress_callback(step_name, {"status": "error", "error": str(e)})
                success = False
                break

        return {"success": success, "steps": results}
