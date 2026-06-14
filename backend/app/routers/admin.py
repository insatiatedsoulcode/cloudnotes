"""
Admin-only endpoints (control plane).

All routes require role == "admin" via the require_admin dependency.
Regular users receive 403 — they cannot even discover these routes via Swagger
because the security scheme blocks them.

Cloud concept: control plane vs. data plane separation.
  - Data plane  = /api/notes/, /api/tags/, etc. — user-facing CRUD.
  - Control plane = /api/admin/ — operational tooling.
  Keeping them separate means a bug in user auth can never accidentally
  escalate to admin access, and you can put different rate limits / network
  policies on each plane.
"""

from datetime import datetime, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit import log_action
from app.database import get_db
from app.dependencies import require_admin
from app.logger import get_logger
from app.models.audit_log import AuditLog
from app.models.note import Note
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.audit_log import AuditLogResponse
from app.schemas.note import NoteResponse
from app.schemas.user import SystemStats, UserAdminView, UserProfile

router = APIRouter(prefix="/admin", tags=["admin"])
log = get_logger("admin")


# ── Note management ───────────────────────────────────────────────────────────

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


# ── User management ───────────────────────────────────────────────────────────

def _get_note_counts(db: Session) -> dict[int, int]:
    """Return a {user_id: live_note_count} mapping via a single GROUP BY query."""
    rows = (
        db.query(Note.owner_id, func.count(Note.id).label("cnt"))
        .filter(Note.deleted_at.is_(None))
        .group_by(Note.owner_id)
        .all()
    )
    return {r.owner_id: r.cnt for r in rows}


@router.get("/users", response_model=List[UserAdminView])
def list_all_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return all users with live note counts."""
    users = db.query(User).order_by(User.created_at.desc()).offset(skip).limit(limit).all()
    counts = _get_note_counts(db)
    result = [
        UserAdminView(
            id=u.id, email=u.email, role=u.role,
            is_active=u.is_active, is_verified=u.is_verified,
            note_count=counts.get(u.id, 0),
            created_at=u.created_at,
        )
        for u in users
    ]
    log.info("ADMIN LIST USERS  count=%d", len(result))
    return result


class _RoleUpdate(BaseModel):
    role: Literal["user", "admin"]


@router.put("/users/{user_id}/role", response_model=UserAdminView)
def change_user_role(
    user_id: int,
    body: _RoleUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Change a user's role between 'user' and 'admin'."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    old_role = user.role
    user.role = body.role
    log_action(db, action="user_role_change", user_id=admin.id, resource_type="user",
               resource_id=user.id, details={"from": old_role, "to": body.role})
    db.commit()
    db.refresh(user)
    log.info("ADMIN ROLE CHANGE  user_id=%d  %s → %s", user_id, old_role, body.role)
    counts = _get_note_counts(db)
    return UserAdminView(
        id=user.id, email=user.email, role=user.role,
        is_active=user.is_active, is_verified=user.is_verified,
        note_count=counts.get(user.id, 0), created_at=user.created_at,
    )


@router.put("/users/{user_id}/suspend", response_model=UserAdminView)
def suspend_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Disable a user account.  The user cannot log in until unsuspended.

    Admins cannot suspend their own account — this prevents accidental lockout.
    """
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot suspend your own account")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="User is already suspended")
    user.is_active = False
    log_action(db, action="user_suspend", user_id=admin.id, resource_type="user", resource_id=user.id)
    db.commit()
    db.refresh(user)
    log.info("ADMIN SUSPEND  user_id=%d  by admin_id=%d", user_id, admin.id)
    counts = _get_note_counts(db)
    return UserAdminView(
        id=user.id, email=user.email, role=user.role,
        is_active=user.is_active, is_verified=user.is_verified,
        note_count=counts.get(user.id, 0), created_at=user.created_at,
    )


@router.put("/users/{user_id}/unsuspend", response_model=UserAdminView)
def unsuspend_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Re-enable a suspended user account."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_active:
        raise HTTPException(status_code=400, detail="User is not suspended")
    user.is_active = True
    log_action(db, action="user_unsuspend", user_id=admin.id, resource_type="user", resource_id=user.id)
    db.commit()
    db.refresh(user)
    log.info("ADMIN UNSUSPEND  user_id=%d  by admin_id=%d", user_id, admin.id)
    counts = _get_note_counts(db)
    return UserAdminView(
        id=user.id, email=user.email, role=user.role,
        is_active=user.is_active, is_verified=user.is_verified,
        note_count=counts.get(user.id, 0), created_at=user.created_at,
    )


# ── System stats ──────────────────────────────────────────────────────────────

@router.get("/stats", response_model=SystemStats)
def get_stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    High-level system stats — intended for an operational dashboard.

    Cloud analogy: this is what flows into CloudWatch / Grafana dashboards.
    total_users, total_notes, notes_today, active_sessions.
    """
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    total_users = db.query(func.count(User.id)).scalar() or 0
    total_notes = db.query(func.count(Note.id)).filter(Note.deleted_at.is_(None)).scalar() or 0
    notes_today = (
        db.query(func.count(Note.id))
        .filter(Note.deleted_at.is_(None), Note.created_at >= today_start)
        .scalar() or 0
    )
    active_sessions = (
        db.query(func.count(RefreshToken.id))
        .filter(
            RefreshToken.revoked == False,  # noqa: E712
            RefreshToken.expires_at > datetime.utcnow(),
        )
        .scalar() or 0
    )
    log.info(
        "ADMIN STATS  users=%d  notes=%d  today=%d  sessions=%d",
        total_users, total_notes, notes_today, active_sessions,
    )
    return SystemStats(
        total_users=total_users,
        total_notes=total_notes,
        notes_today=notes_today,
        active_sessions=active_sessions,
    )


# ── Audit log ─────────────────────────────────────────────────────────────────

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
