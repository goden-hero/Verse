"""Request-scoped context management for CurrentUser provider."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Generator
from sqlalchemy.orm import Session

from app.identity.user import CurrentUser
from app.config.settings import settings

logger = logging.getLogger("music_rec.identity.context")

# Request/Task scoped ContextVar for storing the active CurrentUser
_current_user_var: ContextVar[CurrentUser] = ContextVar(
    "current_user", default=CurrentUser.anonymous()
)


class CurrentUserProvider:
    """Thread-safe and async-safe provider for getting and setting the active user context."""

    @staticmethod
    def set_current_user(user: CurrentUser) -> Token:
        """Binds a CurrentUser instance to the current execution context.

        Args:
            user: The CurrentUser instance to activate.

        Returns:
            ContextVar Token that can be used to reset the context to its prior state.
        """
        token = _current_user_var.set(user)

        if settings.debug_assistant or logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Current user resolved: id=%s username=%s",
                user.id,
                user.username,
            )

        return token

    @staticmethod
    def get_current_user() -> CurrentUser:
        """Retrieves the active CurrentUser for the current execution context.

        Returns:
            The active CurrentUser instance, or CurrentUser.anonymous() if unset.
        """
        return _current_user_var.get()

    @staticmethod
    def clear_current_user(token: Token | None = None) -> None:
        """Clears or resets the active user context.

        Args:
            token: Optional Token returned by set_current_user() to reset context.
        """
        if token is not None:
            try:
                _current_user_var.reset(token)
            except ValueError:
                _current_user_var.set(CurrentUser.anonymous())
        else:
            _current_user_var.set(CurrentUser.anonymous())

    @staticmethod
    def is_authenticated() -> bool:
        """Checks whether the active context user is authenticated."""
        return _current_user_var.get().is_authenticated

    @staticmethod
    def resolve_user_from_db(db: Session, user_id: int | None = None) -> CurrentUser:
        """Development/fallback helper to resolve a User from DB and set in current context.

        Args:
            db: Active SQLAlchemy Session.
            user_id: Optional target user id. Defaults to system owner (id=1 / 'Verse Owner').

        Returns:
            The resolved CurrentUser instance bound to current context.
        """
        from app.database.models import User

        user_orm = None
        if user_id is not None:
            user_orm = db.query(User).filter_by(id=user_id).first()
        else:
            # Fallback to system owner (id=1 or username='Verse Owner')
            user_orm = db.query(User).filter_by(id=1).first()
            if not user_orm:
                user_orm = db.query(User).filter_by(username="Verse Owner").first()

        current_user = CurrentUser.from_user_model(user_orm)
        CurrentUserProvider.set_current_user(current_user)
        return current_user


@contextmanager
def current_user_context(user: CurrentUser) -> Generator[CurrentUser, None, None]:
    """Context manager for temporarily binding a CurrentUser to a code block.

    Example:
        with current_user_context(user):
            playlist_service.get_playlists()
    """
    token = CurrentUserProvider.set_current_user(user)
    try:
        yield user
    finally:
        CurrentUserProvider.clear_current_user(token)
