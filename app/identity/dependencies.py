"""FastAPI dependency injection and ASGI middleware for CurrentUser identity."""

from collections.abc import Callable
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.identity.user import CurrentUser
from app.identity.context import CurrentUserProvider


def get_current_user(request: Request | None = None) -> CurrentUser:
    """FastAPI dependency yielding the resolved CurrentUser for the active request.

    Args:
        request: FastAPI Request object (optional).

    Returns:
        The active CurrentUser instance from CurrentUserProvider.
    """
    return CurrentUserProvider.get_current_user()


class CurrentUserMiddleware(BaseHTTPMiddleware):
    """ASGI Middleware to manage request-scoped CurrentUser context lifecycle.

    Ensures that each HTTP request operates within its own contextvar scope and
    resets context cleanly upon completion.
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        # Check for development/test header overrides (e.g. X-User-ID) if present
        dev_user_id = request.headers.get("X-User-ID")
        token = None

        if dev_user_id and dev_user_id.isdigit():
            # Dev user context override
            override_user = CurrentUser(
                id=int(dev_user_id),
                username=f"user_{dev_user_id}",
                display_name=f"User {dev_user_id}",
                is_authenticated=True,
            )
            token = CurrentUserProvider.set_current_user(override_user)

        try:
            response = await call_next(request)
            return response
        finally:
            if token is not None:
                CurrentUserProvider.clear_current_user(token)
