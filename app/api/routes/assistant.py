from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.dependencies import get_db
from app.api.schemas import ChatRequest, ChatResponse, PlaylistPreviewResponse
from app.services.assistant import AssistantService

router = APIRouter(tags=["Assistant"])

@router.post("/assistant/chat", response_model=ChatResponse)
def assistant_chat(payload: ChatRequest, db: Session = Depends(get_db)):
    """Handles natural language chat prompts for music recommendation and returns structured plans and playlist previews."""
    try:
        res = AssistantService.process_chat(message=payload.message, session=db)
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Assistant failed to process request: {str(e)}"
        )

@router.post("/playlists/{playlist_id}/regenerate", response_model=PlaylistPreviewResponse)
def regenerate_playlist(playlist_id: int, db: Session = Depends(get_db)):
    """Regenerates a playlist preview with fresh recommendations."""
    try:
        res = AssistantService.regenerate_playlist(playlist_id=playlist_id, session=db)
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate playlist: {str(e)}"
        )
