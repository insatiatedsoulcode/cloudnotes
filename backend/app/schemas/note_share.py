from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr


class ShareRequest(BaseModel):
    email: EmailStr
    permission: Literal["view", "edit"]


class ShareResponse(BaseModel):
    id: int
    note_id: int
    shared_with_user_id: int
    permission: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ShareLinkResponse(BaseModel):
    token: str
    url: str
    expires_at: datetime
