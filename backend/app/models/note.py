from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR

from app.database import Base


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    author = Column(String(100), nullable=False, default="anonymous")
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # "private": only owner + admin can read/write
    # "public" : all authenticated users can read; only owner + admin can write
    visibility = Column(String(10), nullable=False, default="private")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    # Maintained by a DB trigger (notes_search_vector_trigger) on INSERT/UPDATE.
    # title weighted A (higher), content weighted B — ts_rank respects this ordering.
    search_vector = Column(TSVECTOR, nullable=True)
