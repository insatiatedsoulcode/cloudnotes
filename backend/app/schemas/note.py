import re
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator

# Control characters that are never valid in user-supplied text fields.
# Allows \t (tab), \n (newline), \r (carriage return) in content but
# rejects null bytes and other non-printable ASCII control chars.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_MAX_TITLE_LEN = 255
_MAX_CONTENT_LEN = 50_000


class NoteCreate(BaseModel):
    title: str
    content: str
    visibility: Literal["private", "public"] = "private"
    tags: List[str] = []

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title must not be empty or whitespace")
        if len(v) > _MAX_TITLE_LEN:
            raise ValueError(f"Title must not exceed {_MAX_TITLE_LEN} characters")
        if _CTRL_RE.search(v):
            raise ValueError("Title contains invalid control characters")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Content must not be empty or whitespace")
        if len(v) > _MAX_CONTENT_LEN:
            raise ValueError(f"Content must not exceed {_MAX_CONTENT_LEN} characters")
        if "\x00" in v:
            raise ValueError("Content contains invalid null bytes")
        return v

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, v: List[str]) -> List[str]:
        seen: dict = {}
        for t in v:
            t = t.strip().lower()
            if t:
                seen[t] = None
        return list(seen)


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    visibility: Optional[Literal["private", "public"]] = None
    tags: Optional[List[str]] = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Title must not be empty or whitespace")
        if len(v) > _MAX_TITLE_LEN:
            raise ValueError(f"Title must not exceed {_MAX_TITLE_LEN} characters")
        if _CTRL_RE.search(v):
            raise ValueError("Title contains invalid control characters")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not v.strip():
            raise ValueError("Content must not be empty or whitespace")
        if len(v) > _MAX_CONTENT_LEN:
            raise ValueError(f"Content must not exceed {_MAX_CONTENT_LEN} characters")
        if "\x00" in v:
            raise ValueError("Content contains invalid null bytes")
        return v

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        seen: dict = {}
        for t in v:
            t = t.strip().lower()
            if t:
                seen[t] = None
        return list(seen)


class NoteResponse(BaseModel):
    id: int
    title: str
    content: str
    author: str
    owner_id: Optional[int]
    visibility: str
    tags: List[str] = []
    created_at: datetime
    updated_at: datetime
    is_shared_with_me: bool = False
    deleted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
