from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.database import Base


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    note_id = Column(Integer, ForeignKey("notes.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)       # sanitized original filename
    content_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    # Storage-backend-relative key (local: relative path; S3: object key).
    # The public URL is derived at read time via StorageBackend.get_url().
    storage_path = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
