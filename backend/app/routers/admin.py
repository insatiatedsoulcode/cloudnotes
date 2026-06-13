"""
Admin-only endpoints (control plane).

All routes require role == "admin" via the require_admin dependency.
Regular users receive 403 — they cannot even discover these routes via Swagger
because the security scheme blocks them.
"""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin
from app.logger import get_logger
from app.models.note import Note
from app.models.user import User
from app.schemas.note import NoteResponse
from app.schemas.user import UserProfile

router = APIRouter(prefix="/admin", tags=["admin"])
log = get_logger("admin")


@router.get("/notes", response_model=List[NoteResponse])
def list_all_notes(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return every note in the system regardless of owner or visibility."""
    notes = db.query(Note).order_by(Note.created_at.desc()).offset(skip).limit(limit).all()
    log.info("ADMIN LIST NOTES  count=%d", len(notes))
    return notes


@router.get("/users", response_model=List[UserProfile])
def list_all_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return all users with their active status."""
    users = db.query(User).order_by(User.created_at.desc()).offset(skip).limit(limit).all()
    log.info("ADMIN LIST USERS  count=%d", len(users))
    return users
