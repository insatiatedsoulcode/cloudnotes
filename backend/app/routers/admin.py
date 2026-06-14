"""
Admin-only endpoints (control plane).

All routes require role == "admin" via the require_admin dependency.
Regular users receive 403 — they cannot even discover these routes via Swagger
because the security scheme blocks them.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.audit import log_action
from app.database import get_db
from app.dependencies import require_admin
from app.logger import get_logger
from app.models.audit_log import AuditLog
from app.models.note import Note
from app.models.user import User
from app.schemas.audit_log import AuditLogResponse
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
    """Return every live (non-deleted) note in the system."""
    notes = (
        db.query(Note)
        .filter(Note.deleted_at.is_(None))
        .order_by(Note.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    log.info("ADMIN LIST NOTES  count=%d", len(notes))
    return notes


@router.get("/notes/trash", response_model=List[NoteResponse])
def list_trash(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return all soft-deleted notes."""
    notes = (
        db.query(Note)
        .filter(Note.deleted_at.isnot(None))
        .order_by(Note.deleted_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    log.info("ADMIN TRASH  count=%d", len(notes))
    return notes


@router.post("/notes/{note_id}/restore", response_model=NoteResponse)
def restore_note(
    note_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Undelete a soft-deleted note."""
    note = db.query(Note).filter(Note.id == note_id, Note.deleted_at.isnot(None)).first()
    if not note:
        raise HTTPException(status_code=404, detail="Deleted note not found")
    note.deleted_at = None
    log_action(db, action="note_restore", user_id=admin.id, resource_type="note", resource_id=note.id)
    db.commit()
    db.refresh(note)
    log.info("ADMIN RESTORE  note_id=%d", note_id)
    return note


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


@router.get("/audit-logs", response_model=List[AuditLogResponse])
def list_audit_logs(
    skip: int = 0,
    limit: int = 100,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    date_from: Optional[datetime] = Query(None, alias="from"),
    date_to: Optional[datetime] = Query(None, alias="to"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return audit log entries with optional filters."""
    query = db.query(AuditLog)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if date_from:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to:
        query = query.filter(AuditLog.created_at <= date_to)
    logs = query.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()
    log.info("ADMIN AUDIT LOGS  count=%d", len(logs))
    return logs
