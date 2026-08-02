"""Authentication package for Verse."""

from app.auth.exceptions import (
    AuthenticationError,
    InvalidCredentials,
    InvalidUsername,
    RegistrationError,
    UserNotFound,
    UsernameAlreadyExists,
    WeakPassword,
)
from app.auth.password import hash_password, verify_password
from app.auth.schemas import AuthRequest, RegisterRequest, UserAuthResponse
from app.auth.service import AuthService

__all__ = [
    "AuthService",
    "hash_password",
    "verify_password",
    "AuthenticationError",
    "InvalidCredentials",
    "UserNotFound",
    "RegistrationError",
    "UsernameAlreadyExists",
    "InvalidUsername",
    "WeakPassword",
    "RegisterRequest",
    "AuthRequest",
    "UserAuthResponse",
]
