from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from app.api.dependencies import get_db
from app.api.schemas import SongResponse
from app.services.search import SearchService

router = APIRouter(tags=["Search"])

@router.get("/search", response_model=List[SongResponse])
def search_songs(
    q: str = Query(default="", description="Search query string matching title, artist, or album"),
    db: Session = Depends(get_db)
):
    """Searches the complete library by title, artist, or album."""
    # Ignore leading/trailing whitespace
    clean_query = q.strip()
    if not clean_query:
        return []
    
    results = SearchService.ranked_metadata_search(query=clean_query, session=db)
    return results
