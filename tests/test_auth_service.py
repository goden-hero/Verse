"""Comprehensive unit test suite for AuthService, password security, and identity integration."""

import pytest
from sqlalchemy.orm import Session
from app.database.models import User
from app.identity import CurrentUserProvider
from app.auth import (
    AuthService,
    InvalidCredentials,
    InvalidUsername,
    RegistrationError,
    UsernameAlreadyExists,
    WeakPassword,
    hash_password,
    verify_password,
)


def test_password_hashing_and_verification() -> None:
    """Verifies that password hashing produces valid bcrypt hashes and verifies correctly."""
    plain_password = "SecretPassword123!"
    hashed = hash_password(plain_password)

    assert hashed != plain_password
    assert hashed.startswith("$2b$")
    assert verify_password(plain_password, hashed) is True
    assert verify_password("WrongPassword", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(plain_password, "") is False


def test_first_run_detection(db_session: Session) -> None:
    """Verifies is_first_run returns True on an empty user database and False after registration."""
    # Ensure database is empty of users for this test
    db_session.query(User).delete()
    db_session.commit()

    assert AuthService.is_first_run(db_session) is True

    AuthService.register(
        username="admin_user",
        password="AdminPassword123",
        display_name="Administrator",
        session=db_session,
    )

    assert AuthService.is_first_run(db_session) is False


def test_create_first_user_onboarding(db_session: Session) -> None:
    """Verifies create_first_user succeeds on first run and rejects subsequent attempts."""
    db_session.query(User).delete()
    db_session.commit()

    # First onboarding user creation succeeds
    first_user = AuthService.create_first_user(
        username="owner",
        password="OwnerPassword123",
        display_name="System Owner",
        session=db_session,
    )
    assert first_user.id is not None
    assert first_user.username == "owner"

    # Subsequent onboarding attempts fail
    with pytest.raises(RegistrationError) as exc_info:
        AuthService.create_first_user(
            username="second_owner",
            password="SecondPassword123",
            session=db_session,
        )
    assert "Initial onboarding has already been completed" in str(exc_info.value)


def test_user_registration_validation_and_persistence(db_session: Session) -> None:
    """Verifies registration validations, unique username constraint, and password hashing."""
    db_session.query(User).delete()
    db_session.commit()

    user = AuthService.register(
        username="alice",
        password="AlicePassword123",
        display_name="Alice Smith",
        session=db_session,
    )

    assert user.id is not None
    assert user.username == "alice"
    assert user.display_name == "Alice Smith"
    assert user.password_hash is not None
    assert user.password_hash != "AlicePassword123"
    assert verify_password("AlicePassword123", user.password_hash) is True

    # Duplicate username rejection
    with pytest.raises(UsernameAlreadyExists) as exc_info:
        AuthService.register(
            username="alice",
            password="AnotherPassword123",
            session=db_session,
        )
    assert "already taken" in str(exc_info.value)

    # Empty username rejection
    with pytest.raises(InvalidUsername):
        AuthService.register(username="   ", password="Password123", session=db_session)

    # Empty password rejection
    with pytest.raises(WeakPassword):
        AuthService.register(username="bob", password="", session=db_session)


def test_user_authentication_success_and_failure(db_session: Session) -> None:
    """Verifies authentication with valid credentials succeeds and invalid credentials raise InvalidCredentials."""
    db_session.query(User).delete()
    db_session.commit()

    AuthService.register(
        username="charlie",
        password="CharliePassword123",
        session=db_session,
    )

    # Correct credentials succeed
    auth_user = AuthService.authenticate(
        username="charlie",
        password="CharliePassword123",
        session=db_session,
    )
    assert auth_user.username == "charlie"

    # Incorrect password fails with generic InvalidCredentials
    with pytest.raises(InvalidCredentials):
        AuthService.authenticate(username="charlie", password="WrongPassword", session=db_session)

    # Non-existent username fails with generic InvalidCredentials
    with pytest.raises(InvalidCredentials):
        AuthService.authenticate(username="non_existent", password="CharliePassword123", session=db_session)

    # Empty credentials fail
    with pytest.raises(InvalidCredentials):
        AuthService.authenticate(username="", password="", session=db_session)


def test_login_and_logout_identity_integration(db_session: Session) -> None:
    """Verifies login updates last_login_at and populates CurrentUserProvider context, and logout clears context."""
    db_session.query(User).delete()
    db_session.commit()

    user = AuthService.register(
        username="diana",
        password="DianaPassword123",
        session=db_session,
    )
    assert user.last_login_at is None

    # Perform login
    current_user = AuthService.login(user=user, session=db_session)

    # 1. Verify DB last_login_at updated
    reloaded_user = AuthService.get_user(user.id, db_session)
    assert reloaded_user is not None
    assert reloaded_user.last_login_at is not None

    # 2. Verify CurrentUser context populated
    active_user = CurrentUserProvider.get_current_user()
    assert active_user.is_authenticated is True
    assert active_user.id == user.id
    assert active_user.username == "diana"
    assert current_user.id == user.id

    # Perform logout
    AuthService.logout()

    # 3. Verify CurrentUser context cleared
    cleared_user = CurrentUserProvider.get_current_user()
    assert cleared_user.is_authenticated is False
    assert cleared_user.id is None


def test_user_lookup_by_id_and_username(db_session: Session) -> None:
    """Verifies get_user and get_user_by_username queries."""
    db_session.query(User).delete()
    db_session.commit()

    user = AuthService.register(
        username="eve",
        password="EvePassword123",
        display_name="Eve User",
        session=db_session,
    )

    found_by_id = AuthService.get_user(user.id, db_session)
    found_by_name = AuthService.get_user_by_username("eve", db_session)

    assert found_by_id is not None
    assert found_by_id.username == "eve"
    assert found_by_name is not None
    assert found_by_name.id == user.id

    # Non-existent lookups
    assert AuthService.get_user(99999, db_session) is None
    assert AuthService.get_user_by_username("nobody", db_session) is None
    assert AuthService.get_user_by_username("", db_session) is None
