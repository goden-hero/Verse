import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Setup logging
logger = logging.getLogger("music_rec.api.server")

# Define paths relative to the file location to ensure robust mounting
API_DIR = Path(__file__).resolve().parent
WEB_DIR = API_DIR.parent / "web"

app = FastAPI(
    title="Verse Music Library API",
    description="HTTP adapter API layer for the self-hosted music recommendation system.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS for ease of access during local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.routes import songs, search, playlists, playback, assistant

app.include_router(songs.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(playlists.router, prefix="/api/v1")
app.include_router(playback.router, prefix="/api/v1")
app.include_router(assistant.router, prefix="/api/v1")

# Mount Web static files at the root
# Ensure directory exists
WEB_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="static")

logger.info("FastAPI application setup completed.")
