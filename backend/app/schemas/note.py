from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class NoteCreate(BaseModel):
    title: str
    content: str
    # author is now set server-side from the JWT user's email, not submitted by client

    @field_validator("title", "content")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be empty or whitespace")
        return v


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


class NoteResponse(BaseModel):
    id: int
    title: str
    content: str
    author: str
    owner_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
