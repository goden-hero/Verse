"""FastAPI dependency injection and ASGI middleware for CurrentUser identity."""

from collections.abc import Callable
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.concurrency import run_in_threadpool

from app.identity.user import CurrentUser
from app.identity.context import CurrentUserProvider


def _resolve_session_user(session_token: str) -> CurrentUser:
    # Local imports avoid coupling the desktop identity provider to web auth.
    from app.auth.sessions import SessionService
    from app.database.connection import get_session

    with get_session() as db:
        return CurrentUser.from_user_model(SessionService.resolve(session_token, db))


def get_current_user() -> CurrentUser:
    """FastAPI dependency yielding the resolved CurrentUser for the active request.

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
        from app.auth.sessions import SESSION_COOKIE

        session_token = request.cookies.get(SESSION_COOKIE)
        user = CurrentUser.anonymous()
        if session_token:
            user = await run_in_threadpool(_resolve_session_user, session_token)
        # Never carry identity between requests or trust a client-supplied user ID.
        token = CurrentUserProvider.set_current_user(user)

        try:
            response = await call_next(request)
            if request.url.path.startswith("/api/v1/auth/"):
                response.headers["Cache-Control"] = "no-store"
            if session_token and not user.is_authenticated and request.url.path != "/api/v1/auth/login":
                response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
            return response
        finally:
            CurrentUserProvider.clear_current_user(token)
