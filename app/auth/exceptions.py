"""Authentication domain exceptions for Verse."""


class AuthenticationError(Exception):
    """Base exception for all authentication service errors."""

    pass


class InvalidCredentials(AuthenticationError):
    """Raised when authentication credentials (username or password) are invalid."""

    def __init__(self, message: str = "Invalid username or password.") -> None:
        super().__init__(message)


class UserNotFound(AuthenticationError):
    """Raised when a specified user cannot be found in the database."""

    def __init__(self, identifier: str | int = "") -> None:
        message = f"User '{identifier}' not found." if identifier else "User not found."
        super().__init__(message)


class RegistrationError(AuthenticationError):
    """Base exception for user registration failures."""

    pass


class UsernameAlreadyExists(RegistrationError):
    """Raised when registering a username that is already taken."""

    def __init__(self, username: str = "") -> None:
        message = f"Username '{username}' is already taken." if username else "Username is already taken."
        super().__init__(message)


class InvalidUsername(RegistrationError):
    """Raised when a username violates format or length requirements."""

    def __init__(self, message: str = "Username cannot be empty.") -> None:
        super().__init__(message)


class WeakPassword(RegistrationError):
    """Raised when a password fails policy checks."""

    def __init__(self, message: str = "Password cannot be empty.") -> None:
        super().__init__(message)
