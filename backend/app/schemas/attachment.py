from datetime import datetime

from pydantic import BaseModel


class AttachmentResponse(BaseModel):
    id: int
    note_id: int
    filename: str
    content_type: str
    size_bytes: int
    url: str          # computed from storage_path at response time — not stored in DB
    created_at: datetime
