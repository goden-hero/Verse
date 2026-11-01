"""Exercise cookie authentication through real HTTP requests to the ASGI app."""

import hashlib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_db
from app.api.server import app
from app.auth import AuthService
from app.auth.sessions import SESSION_COOKIE
from app.config.settings import settings
from app.database import connection
from app.database.models import AuthSession
from app.identity import CurrentUserProvider


@pytest.fixture
def session_client(db_engine, monkeypatch):
    # Both route dependencies and cookie resolution use independent sessions on
    # the same isolated DB, just as separate server requests/workers would.
    factory = sessionmaker(bind=db_engine)

    @contextmanager
    def database_session():
        with factory() as db:
            yield db

    def override_db():
        with database_session() as db:
            yield db

    monkeypatch.setattr(connection, "get_session", database_session)
    app.dependency_overrides[get_db] = override_db
    with factory() as db:
        AuthService.register("alice", "AlicePassword123!", db)
        AuthService.register("bob", "BobPassword123!", db)
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        CurrentUserProvider.clear_current_user()


def login(client, username="alice", password="AlicePassword123!"):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response


def test_session_survives_refresh_and_new_client(session_client):
    client, factory = session_client
    assert client.get("/api/v1/auth/me").status_code == 401
    response = login(client)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert f"Max-Age={settings.session_max_age}" in cookie
    assert "Path=/" in cookie
    assert response.headers["cache-control"] == "no-store"
    token = client.cookies.get(SESSION_COOKIE)

    with factory() as db:
        stored = db.query(AuthSession).one()
        assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert stored.token_hash != token

    assert client.get("/").status_code == 200
    assert client.get("/api/v1/auth/me").json()["username"] == "alice"
    # No credentials or in-memory login state: only the browser cookie survives.
    with TestClient(app) as refreshed:
        refreshed.cookies.set(SESSION_COOKIE, token)
        response = refreshed.get("/api/v1/auth/me")
        assert response.status_code == 200
        assert response.json()["username"] == "alice"
        assert response.headers["cache-control"] == "no-store"


def test_logout_revokes_session_in_database(session_client):
    client, factory = session_client
    login(client)
    token = client.cookies.get(SESSION_COOKIE)
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/api/v1/auth/me").status_code == 401
    with factory() as db:
        assert db.query(AuthSession).count() == 0


def test_expired_and_forged_cookies_do_not_authenticate(session_client):
    client, factory = session_client
    login(client)
    with factory() as db:
        record = db.query(AuthSession).one()
        record.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set(SESSION_COOKIE, "x" * 43)
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"X-User-ID": "2"}).status_code == 401


def test_multiple_browsers_stay_isolated_and_login_rotates_token(session_client):
    client, _ = session_client
    login(client)
    old_token = client.cookies.get(SESSION_COOKIE)
    login(client)
    assert client.cookies.get(SESSION_COOKIE) != old_token
    with TestClient(app) as other:
        other.cookies.set(SESSION_COOKIE, old_token)
        assert other.get("/api/v1/auth/me").status_code == 401
        login(other, "bob", "BobPassword123!")
        assert other.get("/api/v1/auth/me").json()["username"] == "bob"
        assert client.get("/api/v1/auth/me", headers={"X-User-ID": "3"}).json()["username"] == "alice"
        client.post("/api/v1/auth/logout")
        assert other.get("/api/v1/auth/me").json()["username"] == "bob"


def test_inactive_account_cannot_use_existing_session(session_client):
    client, factory = session_client
    login(client)
    with factory() as db:
        user = AuthService.get_user_by_username("alice", db)
        user.is_active = False
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_https_cookie_is_secure_and_bad_login_issues_no_cookie(session_client):
    _, _factory = session_client
    with TestClient(app, base_url="https://testserver") as client:
        response = login(client)
        assert "Secure" in response.headers["set-cookie"]
        assert client.get("/api/v1/auth/me").status_code == 200
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={"username": "alice", "password": "wrong"})
        assert response.status_code == 401
        assert SESSION_COOKIE not in client.cookies
