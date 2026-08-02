"""API route tests for Authentication REST endpoints (/api/v1/auth)."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.routes.auth import (
    check_first_run,
    get_current_authenticated_user,
    login_user,
    logout_user,
    register_user,
)
from app.api.schemas import LoginRequest, RegisterRequest
from app.api.server import app
from app.auth import AuthService
from app.database.models import User
from app.identity import CurrentUser


def test_auth_routes_are_registered() -> None:
    """Verifies the public auth routes are mounted under /api/v1."""
    paths = app.openapi()["paths"]

    assert "post" in paths["/api/v1/auth/register"]
    assert "post" in paths["/api/v1/auth/login"]
    assert "post" in paths["/api/v1/auth/logout"]
    assert "get" in paths["/api/v1/auth/me"]
    assert "get" in paths["/api/v1/auth/first-run"]


def test_first_run_endpoint(db_session: Session) -> None:
    """Verifies first-run state transition from empty database to existing users."""
    db_session.query(User).delete()
    db_session.commit()

    assert check_first_run(db=db_session).model_dump() == {"first_run": True}

    AuthService.register(
        username="init_user",
        password="InitPassword123",
        session=db_session,
    )

    assert check_first_run(db=db_session).model_dump() == {"first_run": False}


def test_register_endpoint_flow(db_session: Session) -> None:
    """Verifies registration success, duplicate rejection, and request validation."""
    db_session.query(User).delete()
    db_session.commit()

    payload = RegisterRequest(
        username="john_doe",
        password="Password123!",
        display_name="John Doe",
    )

    user = register_user(payload=payload, db=db_session)
    assert user.id is not None
    assert user.username == "john_doe"
    assert user.display_name == "John Doe"
    assert not hasattr(user, "password")

    with pytest.raises(HTTPException) as duplicate:
        register_user(payload=payload, db=db_session)
    assert duplicate.value.status_code == 409
    assert "already taken" in duplicate.value.detail

    with pytest.raises(ValidationError):
        RegisterRequest(username="john")

    with pytest.raises(HTTPException) as invalid:
        register_user(
            payload=RegisterRequest(username="   ", password="Password123!"),
            db=db_session,
        )
    assert invalid.value.status_code == 422


def test_login_endpoint_flow(db_session: Session) -> None:
    """Verifies login with valid credentials, invalid password, and unknown user."""
    db_session.query(User).delete()
    db_session.commit()

    AuthService.register(
        username="jane_doe",
        password="JanePassword123!",
        display_name="Jane Doe",
        session=db_session,
    )

    response = login_user(
        payload=LoginRequest(username="jane_doe", password="JanePassword123!"),
        db=db_session,
    )
    assert response.message == "Login successful"
    assert response.user.username == "jane_doe"
    assert response.user.display_name == "Jane Doe"
    assert not hasattr(response.user, "password_hash")

    with pytest.raises(HTTPException) as wrong_password:
        login_user(
            payload=LoginRequest(username="jane_doe", password="WrongPassword"),
            db=db_session,
        )
    assert wrong_password.value.status_code == 401
    assert "Invalid username or password" in wrong_password.value.detail

    with pytest.raises(HTTPException) as unknown_user:
        login_user(
            payload=LoginRequest(username="nobody", password="JanePassword123!"),
            db=db_session,
        )
    assert unknown_user.value.status_code == 401
    assert "Invalid username or password" in unknown_user.value.detail


def test_logout_endpoint() -> None:
    """Verifies logout returns a success response."""
    response = logout_user()

    assert response.success is True
    assert response.message == "Logout successful"


def test_get_current_user_me_endpoint(db_session: Session) -> None:
    """Verifies /me for authenticated, unauthenticated, and missing users."""
    db_session.query(User).delete()
    db_session.commit()

    user = AuthService.register(
        username="sam",
        password="SamPassword123!",
        display_name="Sam Smith",
        session=db_session,
    )

    response = get_current_authenticated_user(
        db=db_session,
        current_user=CurrentUser.from_user_model(user),
    )
    assert response.id == user.id
    assert response.username == "sam"
    assert response.display_name == "Sam Smith"
    assert not hasattr(response, "password_hash")

    with pytest.raises(HTTPException) as unauthenticated:
        get_current_authenticated_user(
            db=db_session,
            current_user=CurrentUser.anonymous(),
        )
    assert unauthenticated.value.status_code == 401
    assert "Not authenticated" in unauthenticated.value.detail

    with pytest.raises(HTTPException) as missing_user:
        get_current_authenticated_user(
            db=db_session,
            current_user=CurrentUser(
                id=999,
                username="missing",
                is_authenticated=True,
            ),
        )
    assert missing_user.value.status_code == 404
    assert "not found" in missing_user.value.detail
