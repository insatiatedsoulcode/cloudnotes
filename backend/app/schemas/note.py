from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

_VALID_VISIBILITY = ("private", "public")


class NoteCreate(BaseModel):
    title: str
    content: str
    visibility: Literal["private", "public"] = "private"

    @field_validator("title", "content")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be empty or whitespace")
        return v


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    visibility: Optional[Literal["private", "public"]] = None


class NoteResponse(BaseModel):
    id: int
    title: str
    content: str
    author: str
    owner_id: Optional[int]
    visibility: str
    created_at: datetime
    updated_at: datetime
    # Set to True in list responses when the note is shared with the requesting user.
    # Always False for notes the user owns or in single-note responses.
    is_shared_with_me: bool = False

    model_config = {"from_attributes": True}
