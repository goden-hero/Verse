"""CurrentUser lightweight immutable model."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CurrentUser:
    """Lightweight immutable representation of the active identity context.

    Intentionally contains only identity fields (id, username, display_name, avatar_path,
    is_authenticated). Does not contain permissions, roles, playlists, or secrets.
    """

    id: int | None
    username: str
    display_name: str | None = None
    avatar_path: str | None = None
    is_authenticated: bool = True

    @classmethod
    def anonymous(cls) -> "CurrentUser":
        """Factory for an unauthenticated/guest user context."""
        return cls(
            id=None,
            username="anonymous",
            display_name="Anonymous User",
            avatar_path=None,
            is_authenticated=False,
        )

    @classmethod
    def from_user_model(cls, user: Any) -> "CurrentUser":
        """Factory creating CurrentUser from a database User ORM model instance.

        Args:
            user: SQLAlchemy User ORM instance or duck-typed user object.
        """
        if user is None:
            return cls.anonymous()

        return cls(
            id=getattr(user, "id", None),
            username=getattr(user, "username", "unknown"),
            display_name=getattr(user, "display_name", None),
            avatar_path=getattr(user, "avatar_path", None),
            is_authenticated=bool(getattr(user, "is_active", True)),
        )
