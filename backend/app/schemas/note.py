from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator


class NoteCreate(BaseModel):
    title: str
    content: str
    visibility: Literal["private", "public"] = "private"
    tags: List[str] = []

    @field_validator("title", "content")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be empty or whitespace")
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
    # Set to True in list responses when the note is shared with the requesting user.
    # Always False for notes the user owns or in single-note responses.
    is_shared_with_me: bool = False
    # Non-null only for soft-deleted notes (visible in /admin/notes/trash).
    deleted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
