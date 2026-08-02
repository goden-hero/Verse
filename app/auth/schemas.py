"""Domain schemas for authentication operations."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    """Domain model for user registration request."""

    username: str = Field(..., min_length=1, description="Unique username")
    password: str = Field(..., min_length=1, description="User password")
    display_name: str | None = Field(default=None, description="Optional display name")


class AuthRequest(BaseModel):
    """Domain model for user authentication request."""

    username: str = Field(..., min_length=1, description="Username")
    password: str = Field(..., min_length=1, description="Password")


class UserAuthResponse(BaseModel):
    """Domain model representing an authenticated user profile."""

    id: int
    username: str
    display_name: str | None = None
    avatar_path: str | None = None
    is_active: bool = True
    created_at: datetime
    last_login_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
