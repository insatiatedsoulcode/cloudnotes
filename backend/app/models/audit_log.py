from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    # Nullable so system-level actions (e.g., background jobs) can be logged without a user.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # Action name — "register", "login", "note_create", "note_update",
    # "note_delete", "share_create", "share_update", "password_reset"
    action = Column(String(50), nullable=False, index=True)
    resource_type = Column(String(50), nullable=True)   # "note", "user", "note_share"
    resource_id = Column(Integer, nullable=True)
    # JSONB: stores before/after snapshots, changed fields, or extra context.
    # Never queried by the app — exists for human audit and compliance review.
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
