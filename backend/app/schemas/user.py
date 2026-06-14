from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def email_max_length(cls, v: str) -> str:
        if len(v) > 255:
            raise ValueError("Email must not exceed 255 characters")
        return v

    @field_validator("password")
    @classmethod
    def password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        # bcrypt silently truncates passwords longer than 72 bytes, making very long
        # passwords weaker than they appear. Cap at 128 characters to prevent this
        # confusion and defend against bcrypt DoS on some implementations.
        if len(v) > 128:
            raise ValueError("Password must not exceed 128 characters")
        return v


class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserProfile(BaseModel):
    """Richer response used by /api/users/me — includes is_active and is_verified."""
    id: int
    email: str
    role: str
    is_active: bool
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserAdminView(BaseModel):
    """Admin-plane view of a user — includes note_count derived via a subquery."""
    id: int
    email: str
    role: str
    is_active: bool
    is_verified: bool
    note_count: int
    created_at: datetime


class SystemStats(BaseModel):
    total_users: int
    total_notes: int
    notes_today: int
    active_sessions: int


class UserUpdate(BaseModel):
    """Change password. Email change requires verification (F-05)."""
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("New password must be at least 8 characters")
        if len(v) > 128:
            raise ValueError("New password must not exceed 128 characters")
        return v


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SessionResponse(BaseModel):
    """One active (non-revoked, non-expired) refresh token = one device/session."""
    id: int
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    is_current: bool = False  # True when this session's token matches the request cookie


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("New password must be at least 8 characters")
        if len(v) > 128:
            raise ValueError("New password must not exceed 128 characters")
        return v
