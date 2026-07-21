"""Main CLI entry point for the Music Recommendation System."""

import argparse
import logging
import sys
from pathlib import Path
from sqlalchemy.orm import Session
from app.config.settings import settings
from app.database.connection import get_session
from app.database.models import Song
from app.metadata.semantic import enrich_song_semantics
from app.history import get_history, record_play, record_skip, set_like_status
from app.utils.logging import setup_logging

logger = logging.getLogger("music_rec.main")


def _default_vector_index_path() -> Path:
    """Place the vector index beside the configured SQLite database."""
    sqlite_prefix = "sqlite:///"
    if settings.database_url.startswith(sqlite_prefix):
        return Path(settings.database_url.removeprefix(sqlite_prefix)).parent / "vector_index.bin"
    return Path("data") / "vector_index.bin"


def run_scan(args) -> None:
    """CLI handler for scanning and indexing a music folder."""
    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        print(f"Scan failed: '{folder}' is not a directory.")
        return

    # Keep the full indexing behaviour shared with the desktop UI: metadata,
    # features, embeddings, and both search indexes are refreshed together.
    from app.ui.workers import ScanWorker

    resolved_folder = folder.resolve()
    worker = ScanWorker(
        folder_path=resolved_folder,
        vector_index_path=_default_vector_index_path(),
    )
    result: dict[str, int | str | None] = {"count": None, "error": None}
    worker.finished.connect(lambda count: result.update(count=count))
    worker.error.connect(lambda message: result.update(error=message))

    print(f"Scanning and indexing music in '{resolved_folder}'...")
    worker.run()

    if result["error"]:
        print(f"Scan failed: {result['error']}")
    elif result["count"] is None:
        print("Scan finished without a result.")
    else:
        print(f"Scan complete. Indexed {result['count']} new or updated song(s).")


def run_enrich_semantic(args) -> None:
    """CLI handler for semantic enrichment."""
    logger.info("Starting semantic enrichment process...")
    
    with get_session() as session:
        query = session.query(Song)
        songs = query.all()
        if not songs:
            print("No songs found in the database. Please scan a music folder first.")
            return

        print(f"Found {len(songs)} songs in database.")
        processed = 0
        enriched_count = 0

        for song in songs:
            if args.limit and enriched_count >= args.limit:
                print(f"Reached processing limit of {args.limit} songs.")
                break

            print(f"[{processed+1}/{len(songs)}] Processing '{song.title}' by '{song.artist}'...")
            success = enrich_song_semantics(
                song_id=song.id,
                db_session=session,
                force_refresh=args.force,
            )
            
            if success:
                enriched_count += 1
            processed += 1

        print(f"Semantic enrichment complete. Successfully enriched {enriched_count} songs.")


def run_play(args) -> None:
    """CLI handler for recording a play."""
    with get_session() as session:
        try:
            record_play(args.song_id, args.duration, session)
            print(f"Recorded play for song {args.song_id} (duration: {args.duration}s).")
        except ValueError as e:
            print(f"Error: {e}")


def run_skip(args) -> None:
    """CLI handler for recording a skip."""
    with get_session() as session:
        try:
            record_skip(args.song_id, session)
            print(f"Recorded skip for song {args.song_id}.")
        except ValueError as e:
            print(f"Error: {e}")


def run_like(args) -> None:
    """CLI handler for toggling like status."""
    with get_session() as session:
        try:
            liked = not args.unlike
            set_like_status(args.song_id, liked, session)
            action = "Liked" if liked else "Unliked"
            print(f"{action} song {args.song_id}.")
        except ValueError as e:
            print(f"Error: {e}")


def run_show_history(args) -> None:
    """CLI handler for displaying history details."""
    with get_session() as session:
        history = get_history(args.song_id, session)
        if not history:
            print(f"No listening history found for song ID {args.song_id}.")
            return

        print(f"Listening History for Song ID {args.song_id}:")
        print(f"  Play Count:    {history['play_count']}")
        print(f"  Skips:         {history['skips']}")
        print(f"  Liked:         {history['likes']}")
        print(f"  Last Played:   {history['last_played'] or 'Never'}")
        print(f"  Play Duration: {history['play_duration']:.2f} seconds")


def run_gui(args) -> None:
    """CLI handler for launching the PySide6 Desktop GUI."""
    logger.info("Initializing PySide6 GUI Application...")
    from PySide6.QtWidgets import QApplication
    from app.ui import MainWindow
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def run_web(args) -> None:
    """CLI handler for launching the FastAPI web server."""
    logger.info("Initializing FastAPI Web Application...")
    import uvicorn
    uvicorn.run("app.api.server:app", host=args.host, port=args.port, reload=args.reload)


def main() -> None:
    """Initializes the application and boots the CLI."""
    setup_logging()
    logger.debug("Application logging initialized.")

    if len(sys.argv) == 1:
        print("Music Recommendation System")
        print("Ready.")
        return

    parser = argparse.ArgumentParser(
        description="AI-powered Local Music Recommendation System CLI."
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")

    # scan subcommand
    scan_parser = subparsers.add_parser(
        "scan",
        help="Recursively scan and index a music folder.",
    )
    scan_parser.add_argument(
        "folder",
        help="Path to the music folder to scan.",
    )

    # enrich-semantic subcommand
    enrich_parser = subparsers.add_parser(
        "enrich-semantic",
        help="Generate semantic tags using local Ollama LLM.",
    )
    enrich_parser.add_argument(
        "--force",
        action="store_true",
        help="Force regeneration and overwrite existing cached semantic tags.",
    )
    enrich_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of songs to enrich in this run.",
    )

    # play subcommand
    play_parser = subparsers.add_parser("play", help="Record a play event for a song.")
    play_parser.add_argument("song_id", type=int, help="Database ID of the song.")
    play_parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Duration of the play in seconds (default: 10.0).",
    )

    # skip subcommand
    skip_parser = subparsers.add_parser("skip", help="Record a skip event for a song.")
    skip_parser.add_argument("song_id", type=int, help="Database ID of the song.")

    # like subcommand
    like_parser = subparsers.add_parser("like", help="Toggle like/unlike status for a song.")
    like_parser.add_argument("song_id", type=int, help="Database ID of the song.")
    like_parser.add_argument(
        "--unlike", action="store_true", help="Remove like status (unlike) the song."
    )

    # show-history subcommand
    history_parser = subparsers.add_parser("show-history", help="Show listening history stats for a song.")
    history_parser.add_argument("song_id", type=int, help="Database ID of the song.")

    # gui subcommand
    gui_parser = subparsers.add_parser("gui", help="Boot the PySide6 Desktop GUI.")

    # web subcommand
    web_parser = subparsers.add_parser("web", help="Boot the FastAPI Web Server.")
    # serve subcommand (alias for web)
    serve_parser = subparsers.add_parser("serve", help="Boot the FastAPI Web Server (alias for web).")
    
    for parser_obj in [web_parser, serve_parser]:
        parser_obj.add_argument(
            "--host",
            type=str,
            default="127.0.0.1",
            help="Host address to bind to (default: 127.0.0.1).",
        )
        parser_obj.add_argument(
            "--port",
            type=int,
            default=8000,
            help="Port to listen on (default: 8000).",
        )
        parser_obj.add_argument(
            "--reload",
            action="store_true",
            help="Enable auto-reload.",
        )

    args = parser.parse_args()

    if args.command == "scan":
        run_scan(args)
    elif args.command == "enrich-semantic":
        run_enrich_semantic(args)
    elif args.command == "play":
        run_play(args)
    elif args.command == "skip":
        run_skip(args)
    elif args.command == "like":
        run_like(args)
    elif args.command == "show-history":
        run_show_history(args)
    elif args.command == "gui":
        run_gui(args)
    elif args.command in ("web", "serve"):
        run_web(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
