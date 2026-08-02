"""AuthService implementing standalone authentication business logic."""

import logging
from datetime import datetime
from sqlalchemy.orm import Session

from app.database.models import User
from app.identity import CurrentUser, CurrentUserProvider
from app.auth.password import hash_password, verify_password
from app.auth.exceptions import (
    InvalidCredentials,
    InvalidUsername,
    RegistrationError,
    UsernameAlreadyExists,
    WeakPassword,
)

logger = logging.getLogger("music_rec.auth.service")


class AuthService:
    """Standalone service for user registration, authentication, login/logout, and user lookup."""

    @staticmethod
    def is_first_run(session: Session) -> bool:
        """Determines if the application has zero registered users (first-time run)."""
        count = session.query(User).count()
        return count == 0

    @staticmethod
    def register(
        username: str,
        password: str,
        session: Session,
        display_name: str | None = None,
    ) -> User:
        """Registers a new user account with hashed password storage.

        Args:
            username: Desired unique username.
            password: Plain text password.
            session: Active database session.
            display_name: Optional user display name.

        Returns:
            The created User model instance.

        Raises:
            InvalidUsername: If username is empty or whitespace.
            WeakPassword: If password is empty.
            UsernameAlreadyExists: If username is taken.
        """
        if not username or not username.strip():
            raise InvalidUsername("Username cannot be empty or whitespace.")

        if not password:
            raise WeakPassword("Password cannot be empty.")

        clean_username = username.strip()

        existing = session.query(User).filter(User.username == clean_username).first()
        if existing:
            raise UsernameAlreadyExists(clean_username)

        pwd_hash = hash_password(password)
        now = datetime.utcnow()

        user = User(
            username=clean_username,
            password_hash=pwd_hash,
            display_name=display_name or clean_username,
            created_at=now,
            updated_at=now,
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        logger.info("Registration succeeded for user '%s' (ID: %d)", user.username, user.id)
        return user

    @staticmethod
    def create_first_user(
        username: str,
        password: str,
        session: Session,
        display_name: str | None = None,
    ) -> User:
        """Onboards the initial administrative owner if no users exist.

        Raises:
            RegistrationError: If system is not in first-run state.
        """
        if not AuthService.is_first_run(session):
            raise RegistrationError("Initial onboarding has already been completed.")

        return AuthService.register(
            username=username,
            password=password,
            display_name=display_name,
            session=session,
        )

    @staticmethod
    def authenticate(username: str, password: str, session: Session) -> User:
        """Authenticates user credentials against stored password hashes.

        Args:
            username: Candidate username.
            password: Candidate plain text password.
            session: Active database session.

        Returns:
            The authenticated User object.

        Raises:
            InvalidCredentials: If credentials do not match or user is inactive.
        """
        if not username or not password:
            logger.info("Authentication failed: Empty username or password provided.")
            raise InvalidCredentials()

        clean_username = username.strip()
        user = session.query(User).filter(User.username == clean_username).first()

        if not user or not user.password_hash:
            logger.info("Authentication failed for candidate username '%s'", clean_username)
            raise InvalidCredentials()

        if not user.is_active:
            logger.info("Authentication failed: User '%s' is inactive", clean_username)
            raise InvalidCredentials()

        if not verify_password(password, user.password_hash):
            logger.info("Authentication failed: Incorrect password for user '%s'", clean_username)
            raise InvalidCredentials()

        logger.info("Authentication succeeded for user '%s'", user.username)
        return user

    @staticmethod
    def login(user: User, session: Session) -> CurrentUser:
        """Logs in an authenticated user by updating last_login_at and setting CurrentUser context.

        Args:
            user: User model instance to log in.
            session: Active database session.

        Returns:
            Immutable CurrentUser object representing active context.
        """
        now = datetime.utcnow()
        user.last_login_at = now
        user.updated_at = now
        session.commit()

        current_user = CurrentUser.from_user_model(user)
        CurrentUserProvider.set_current_user(current_user)

        logger.info("Login succeeded for user '%s' (ID: %d)", user.username, user.id)
        return current_user

    @staticmethod
    def logout() -> None:
        """Clears the active CurrentUser context."""
        CurrentUserProvider.clear_current_user()
        logger.info("Logout succeeded.")

    @staticmethod
    def get_user(user_id: int, session: Session) -> User | None:
        """Retrieves a user by primary key ID."""
        return session.get(User, user_id)

    @staticmethod
    def get_user_by_username(username: str, session: Session) -> User | None:
        """Retrieves a user by unique username."""
        if not username:
            return None
        return session.query(User).filter(User.username == username.strip()).first()
