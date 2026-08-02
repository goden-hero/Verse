"""Unit tests for CurrentUser identity infrastructure and context management."""

import asyncio
import logging
import pytest
from dataclasses import FrozenInstanceError
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.identity import (
    CurrentUser,
    CurrentUserProvider,
    current_user_context,
    get_current_user,
)
from app.database.models import User
from app.api.server import app


def test_current_user_immutability_and_factories() -> None:
    """Verifies that CurrentUser objects are immutable dataclasses with correct defaults."""
    user = CurrentUser(
        id=42,
        username="alice",
        display_name="Alice Smith",
        avatar_path="/avatars/alice.png",
        is_authenticated=True,
    )

    assert user.id == 42
    assert user.username == "alice"
    assert user.display_name == "Alice Smith"
    assert user.avatar_path == "/avatars/alice.png"
    assert user.is_authenticated is True

    # Test immutability
    with pytest.raises(FrozenInstanceError):
        user.username = "bob"  # type: ignore[misc]

    # Test anonymous factory
    anon = CurrentUser.anonymous()
    assert anon.id is None
    assert anon.username == "anonymous"
    assert anon.is_authenticated is False


def test_current_user_from_orm_model() -> None:
    """Verifies CurrentUser.from_user_model factory."""
    orm_user = User(
        id=1,
        username="Verse Owner",
        display_name="Verse Owner",
        avatar_path="/avatars/owner.png",
        is_active=True,
    )

    current = CurrentUser.from_user_model(orm_user)
    assert current.id == 1
    assert current.username == "Verse Owner"
    assert current.display_name == "Verse Owner"
    assert current.is_authenticated is True

    # Test None handling
    assert CurrentUser.from_user_model(None).is_authenticated is False


def test_provider_set_get_clear() -> None:
    """Verifies CurrentUserProvider state lifecycle in isolated contexts."""
    initial = CurrentUserProvider.get_current_user()
    assert initial.is_authenticated is False

    test_user = CurrentUser(id=10, username="test_user", is_authenticated=True)
    token = CurrentUserProvider.set_current_user(test_user)

    assert CurrentUserProvider.get_current_user().username == "test_user"
    assert CurrentUserProvider.is_authenticated() is True

    CurrentUserProvider.clear_current_user(token)
    assert CurrentUserProvider.get_current_user().is_authenticated is False


def test_context_manager_scoping() -> None:
    """Verifies with current_user_context(user) context manager."""
    user_a = CurrentUser(id=1, username="user_a", is_authenticated=True)
    user_b = CurrentUser(id=2, username="user_b", is_authenticated=True)

    assert CurrentUserProvider.get_current_user().is_authenticated is False

    with current_user_context(user_a):
        assert CurrentUserProvider.get_current_user().username == "user_a"

        with current_user_context(user_b):
            assert CurrentUserProvider.get_current_user().username == "user_b"

        assert CurrentUserProvider.get_current_user().username == "user_a"

    assert CurrentUserProvider.get_current_user().is_authenticated is False


@pytest.mark.anyio
async def test_async_task_context_isolation() -> None:
    """Verifies contextvars isolation across concurrent async tasks."""
    user1 = CurrentUser(id=101, username="task_1_user")
    user2 = CurrentUser(id=102, username="task_2_user")

    async def worker(user_to_set: CurrentUser, delay: float) -> str:
        token = CurrentUserProvider.set_current_user(user_to_set)
        await asyncio.sleep(delay)
        active_user = CurrentUserProvider.get_current_user()
        CurrentUserProvider.clear_current_user(token)
        return active_user.username

    res1, res2 = await asyncio.gather(
        worker(user1, 0.02),
        worker(user2, 0.01),
    )

    assert res1 == "task_1_user"
    assert res2 == "task_2_user"


def test_resolve_user_from_db(db_session: Session) -> None:
    """Verifies CurrentUserProvider.resolve_user_from_db helper."""
    owner = db_session.query(User).filter_by(id=1).first()
    if not owner:
        owner = User(id=1, username="Verse Owner", display_name="Verse Owner")
        db_session.add(owner)
        db_session.commit()

    resolved = CurrentUserProvider.resolve_user_from_db(db_session)
    assert resolved.id == 1
    assert resolved.username == "Verse Owner"
    assert CurrentUserProvider.get_current_user().username == "Verse Owner"

    CurrentUserProvider.clear_current_user()


def test_fastapi_dependency_and_middleware() -> None:
    """Verifies FastAPI get_current_user dependency and CurrentUserMiddleware."""
    client = TestClient(app)

    # Test default request without header
    response = client.get("/api/v1/songs")
    assert response.status_code == 200

    # Test dev header override X-User-ID
    response = client.get("/api/v1/songs", headers={"X-User-ID": "99"})
    assert response.status_code == 200


def test_safe_logging(caplog: pytest.LogCaptureFixture) -> None:
    """Verifies debug log contains user identity info without secrets."""
    caplog.set_level(logging.DEBUG, logger="music_rec.identity.context")

    user = CurrentUser(id=7, username="secret_agent")
    token = CurrentUserProvider.set_current_user(user)

    assert "Current user resolved: id=7 username=secret_agent" in caplog.text
    assert "password" not in caplog.text.lower()

    CurrentUserProvider.clear_current_user(token)
