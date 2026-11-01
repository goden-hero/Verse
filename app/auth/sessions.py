"""Persistent, revocable browser sessions shared by all web server workers."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config.settings import settings
from app.database.models import AuthSession, User

SESSION_COOKIE = "verse_session"


def _utcnow() -> datetime:
    # Match the database's timezone-naive UTC timestamps.
    return datetime.now(UTC).replace(tzinfo=None)


class SessionService:
    @staticmethod
    def create(user: User, db: Session, previous_token: str | None = None) -> str:
        """Rotate this browser's session without signing out other devices."""
        SessionService.revoke(previous_token, db)
        db.query(AuthSession).filter(AuthSession.expires_at <= _utcnow()).delete()
        token = secrets.token_urlsafe(32)
        db.add(AuthSession(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            user_id=user.id,
            expires_at=_utcnow() + timedelta(seconds=settings.session_max_age),
        ))
        db.commit()
        return token

    @staticmethod
    def resolve(token: str | None, db: Session) -> User | None:
        if not token or len(token) != 43:
            return None
        record = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
        if record is None or record.expires_at <= _utcnow():
            return None
        user = db.get(User, record.user_id)
        if user is None or not user.is_active or not user.password_hash:
            return None
        return user

    @staticmethod
    def revoke(token: str | None, db: Session) -> None:
        if token:
            db.query(AuthSession).filter_by(
                token_hash=hashlib.sha256(token.encode()).hexdigest()
            ).delete()
