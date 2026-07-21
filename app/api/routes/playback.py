from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.dependencies import get_db
from app.api.schemas import PlayRecordRequest, SkipRecordRequest, LikeRecordRequest
from app.services.history import HistoryService

router = APIRouter(tags=["Playback"])

@router.post("/history/play", status_code=status.HTTP_200_OK)
def record_play(payload: PlayRecordRequest, db: Session = Depends(get_db)):
    """Records a song play event and its duration in the database."""
    try:
        HistoryService.record_play(song_id=payload.song_id, duration=payload.duration, session=db)
        return {"status": "success", "message": "Play recorded successfully."}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record play: {str(e)}"
        )

@router.post("/history/skip", status_code=status.HTTP_200_OK)
def record_skip(payload: SkipRecordRequest, db: Session = Depends(get_db)):
    """Records a song skip event in the database."""
    try:
        HistoryService.record_skip(song_id=payload.song_id, session=db)
        return {"status": "success", "message": "Skip recorded successfully."}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record skip: {str(e)}"
        )

@router.post("/history/like", status_code=status.HTTP_200_OK)
def record_like(payload: LikeRecordRequest, db: Session = Depends(get_db)):
    """Toggles or updates the liked/favorite status of a song in the database."""
    try:
        HistoryService.set_like_status(song_id=payload.song_id, liked=payload.liked, session=db)
        return {"status": "success", "message": "Like status updated successfully."}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update like status: {str(e)}"
        )
