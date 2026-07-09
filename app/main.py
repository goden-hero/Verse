"""Main CLI entry point for the Music Recommendation System."""

import argparse
import logging
import sys
from sqlalchemy.orm import Session
from app.config.settings import settings
from app.database.connection import get_session
from app.database.models import Song
from app.metadata.semantic import enrich_song_semantics
from app.utils.logging import setup_logging

logger = logging.getLogger("music_rec.main")


def run_enrich_semantic(args) -> None:
    """CLI handler for semantic enrichment."""
    logger.info("Starting semantic enrichment process...")
    session_factory = get_session()
    
    with session_factory() as session:
        # Fetch songs
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


def main() -> None:
    """Initializes the application and boots the CLI."""
    setup_logging()
    logger.debug("Application logging initialized.")

    # Fallback to simple print if no arguments are provided (Phase 1 baseline compatibility)
    if len(sys.argv) == 1:
        print("Music Recommendation System")
        print("Ready.")
        return

    parser = argparse.ArgumentParser(
        description="AI-powered Local Music Recommendation System CLI."
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")

    # enrich-semantic subcommand
    enrich_parser = subparsers.add_parser(
        "enrich-semantic",
        help="Generate semantic tags (moods, themes, energy, etc.) using local Ollama LLM.",
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

    args = parser.parse_argv = parser.parse_args()

    if args.command == "enrich-semantic":
        run_enrich_semantic(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
