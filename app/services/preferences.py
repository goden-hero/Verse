"""UserPreferencesService to manage user-scoped application settings."""

import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import UserPreferences
from app.identity import CurrentUser

logger = logging.getLogger("music_rec.services.preferences")


class UserPreferencesService:
    """Manages user-scoped preferences and settings."""

    @staticmethod
    def get_preferences(current_user: CurrentUser, session: Session) -> dict:
        """Retrieves preferences for the current user, providing defaults if unset."""
        if not current_user.id:
            return {
                "theme": "dark",
                "accent_color": None,
                "volume": 1.0,
                "crossfade": 0.0,
                "equalizer": None,
            }

        prefs = session.get(UserPreferences, current_user.id)
        if not prefs:
            return {
                "user_id": current_user.id,
                "theme": "dark",
                "accent_color": None,
                "volume": 1.0,
                "crossfade": 0.0,
                "equalizer": None,
            }

        return {
            "user_id": prefs.user_id,
            "theme": prefs.theme or "dark",
            "accent_color": prefs.accent_color,
            "volume": prefs.volume,
            "crossfade": prefs.crossfade,
            "equalizer": prefs.equalizer,
            "updated_at": prefs.updated_at.isoformat() if prefs.updated_at else None,
        }

    @staticmethod
    def save_preferences(
        current_user: CurrentUser,
        prefs: dict,
        session: Session,
    ) -> dict:
        """Saves or updates preferences for the current user."""
        if not current_user.id:
            raise ValueError("User must be authenticated to save preferences.")

        db_prefs = session.get(UserPreferences, current_user.id)
        now = datetime.utcnow()
        if not db_prefs:
            db_prefs = UserPreferences(
                user_id=current_user.id,
                theme=prefs.get("theme", "dark"),
                accent_color=prefs.get("accent_color"),
                volume=prefs.get("volume", 1.0),
                crossfade=prefs.get("crossfade", 0.0),
                equalizer=prefs.get("equalizer"),
                created_at=now,
                updated_at=now,
            )
            session.add(db_prefs)
        else:
            if "theme" in prefs:
                db_prefs.theme = prefs["theme"]
            if "accent_color" in prefs:
                db_prefs.accent_color = prefs["accent_color"]
            if "volume" in prefs:
                db_prefs.volume = prefs["volume"]
            if "crossfade" in prefs:
                db_prefs.crossfade = prefs["crossfade"]
            if "equalizer" in prefs:
                db_prefs.equalizer = prefs["equalizer"]
            db_prefs.updated_at = now

        session.commit()
        logger.info("Saved preferences for user %s", current_user.id)
        return UserPreferencesService.get_preferences(current_user, session)
