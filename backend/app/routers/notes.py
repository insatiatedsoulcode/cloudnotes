from datetime import date, datetime, timedelta
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.cache import (
    NOTES_DETAIL_TTL,
    NOTES_LIST_TTL,
    cache_delete,
    cache_delete_pattern,
    cache_get,
    cache_set,
)
from app.database import get_db
from app.dependencies import get_current_user, require_verified
from app.limiter import _get_user_or_ip, limiter
from app.logger import get_logger
from app.audit import log_action
from app.models.note import Note
from app.models.note_share import NoteShare
from app.models.user import User
from app.schemas.note import NoteCreate, NoteResponse, NoteUpdate

router = APIRouter(prefix="/notes", tags=["notes"])
log = get_logger("notes")


def _check_ownership(note: Note, user: User, db: Optional[Session] = None, *, allow_edit_share: bool = False) -> None:
    """Raise 403 if the user doesn't own the note and isn't an admin.

    When allow_edit_share=True, also grants access to users with an 'edit' share — used
    for update_note (edit-share users can update; they still cannot delete).
    """
    if note.owner_id != user.id and user.role != "admin":
        if allow_edit_share and db:
            share = db.query(NoteShare).filter(
                NoteShare.note_id == note.id,
                NoteShare.shared_with_user_id == user.id,
                NoteShare.permission == "edit",
            ).first()
            if share:
                return
        log.warning(
            "FORBIDDEN  user_id=%d tried to modify note_id=%d owned by user_id=%s",
            user.id, note.id, note.owner_id,
        )
        raise HTTPException(status_code=403, detail="You don't own this note")


def _check_read_access(note_data: dict, user: User, db: Optional[Session] = None) -> None:
    """Raise 403 if a private note is inaccessible to the user.

    Access is granted when: user is the owner, user is an admin, or the note has
    been explicitly shared with the user (any permission level).
    """
    if note_data.get("visibility") == "private":
        if note_data.get("owner_id") != user.id and user.role != "admin":
            if db:
                share = db.query(NoteShare).filter(
                    NoteShare.note_id == note_data["id"],
                    NoteShare.shared_with_user_id == user.id,
                ).first()
                if share:
                    return
            raise HTTPException(status_code=403, detail="This note is private")


def _serialize_note(note: Note) -> dict:
    """Convert ORM Note → JSON-safe dict via Pydantic (handles datetime → ISO string)."""
    return NoteResponse.model_validate(note).model_dump(mode="json")


# ── List (scoped) ─────────────────────────────────────────────────────────────

@router.get("/", response_model=List[NoteResponse])
def list_notes(
    skip: int = 0,
    limit: int = 100,
    q: Optional[str] = None,
    sort: str = "created_at",
    order: str = "desc",
    date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    visibility: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    # Normalize params — unknown values fall back to safe defaults.
    q = q.strip() if q else None
    if sort not in ("created_at", "updated_at", "rank"):
        sort = "created_at"
    if order not in ("asc", "desc"):
        order = "desc"
    if sort == "rank" and not q:
        sort = "created_at"

    log.info(
        "LIST  user_id=%d  skip=%d  limit=%d  q=%r  sort=%s  order=%s",
        current_user.id, skip, limit, q, sort, order,
    )

    # Only cache plain listing requests — search/filter results are too dynamic.
    use_cache = not any([q, date_from, date_to, visibility])
    if use_cache:
        cache_key = f"notes:list:{current_user.id}:{skip}:{limit}:{sort}:{order}"
        cached = cache_get(cache_key)
        if cached is not None:
            log.info("LIST  → cache hit  count=%d", len(cached))
            return cached

    query = db.query(Note).filter(Note.deleted_at.is_(None))

    # Scope: admins see everything; regular users see own + public + shared with them.
    if current_user.role != "admin":
        shared_ids = {
            r.note_id
            for r in db.query(NoteShare.note_id)
                       .filter(NoteShare.shared_with_user_id == current_user.id)
                       .all()
        }
        conditions = [Note.owner_id == current_user.id, Note.visibility == "public"]
        if shared_ids:
            conditions.append(Note.id.in_(shared_ids))
        query = query.filter(or_(*conditions))
    else:
        shared_ids = set()

    # Full-text search filter.
    if q:
        ts_query = func.plainto_tsquery("english", q)
        query = query.filter(Note.search_vector.op("@@")(ts_query))

    # Date range filter (inclusive on both ends, full-day granularity).
    if date_from:
        query = query.filter(
            Note.created_at >= datetime(date_from.year, date_from.month, date_from.day)
        )
    if date_to:
        query = query.filter(
            Note.created_at < datetime(date_to.year, date_to.month, date_to.day) + timedelta(days=1)
        )

    # Visibility filter (stacks on top of access-control scope above).
    if visibility in ("public", "private"):
        query = query.filter(Note.visibility == visibility)

    # Sort.
    if sort == "rank":
        rank_expr = func.ts_rank(Note.search_vector, func.plainto_tsquery("english", q))
        query = query.order_by(rank_expr.desc() if order == "desc" else rank_expr.asc())
    else:
        sort_col = Note.updated_at if sort == "updated_at" else Note.created_at
        query = query.order_by(sort_col.desc() if order == "desc" else sort_col.asc())

    notes = query.offset(skip).limit(limit).all()
    data = []
    for note in notes:
        d = _serialize_note(note)
        # Mark notes the user doesn't own but has been given explicit share access to.
        d["is_shared_with_me"] = (
            note.id in shared_ids and note.owner_id != current_user.id
        )
        data.append(d)

    if use_cache:
        cache_set(cache_key, data, NOTES_LIST_TTL)
        log.info("LIST  → db hit  count=%d  cached for %ds", len(data), NOTES_LIST_TTL)
    else:
        log.info("LIST  → db hit  count=%d  (no cache)", len(data))

    return data


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("/", response_model=NoteResponse, status_code=201)
@limiter.limit("30/minute", key_func=_get_user_or_ip)
def create_note(
    request: Request,
    note: NoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_verified),
):
    log.info(
        "CREATE  user_id=%d  title=%r  visibility=%s",
        current_user.id, note.title, note.visibility,
    )
    db_note = Note(
        title=note.title,
        content=note.content,
        author=current_user.email,
        owner_id=current_user.id,
        visibility=note.visibility,
    )
    db.add(db_note)
    db.flush()   # assigns db_note.id from the sequence before commit
    log_action(db, action="note_create", user_id=current_user.id, resource_type="note",
               resource_id=db_note.id,
               details={"title": note.title, "visibility": note.visibility})
    db.commit()
    db.refresh(db_note)
    cache_delete_pattern("notes:list:*")
    log.info("CREATE  → id=%d  list cache invalidated", db_note.id)
    return db_note


# ── Get (visibility-aware) ────────────────────────────────────────────────────

@router.get("/{note_id}", response_model=NoteResponse)
def get_note(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    cache_key = f"notes:detail:{note_id}"
    log.info("GET  user_id=%d  note_id=%d", current_user.id, note_id)

    cached = cache_get(cache_key)
    if cached is not None:
        # Access control must be re-checked even on cache hits —
        # visibility or ownership may have changed since the key was written.
        _check_read_access(cached, current_user, db)
        log.info("GET  note_id=%d  → cache hit", note_id)
        return cached

    note = db.query(Note).filter(Note.id == note_id, Note.deleted_at.is_(None)).first()
    if not note:
        log.warning("GET  note_id=%d  → 404", note_id)
        raise HTTPException(status_code=404, detail="Note not found")

    data = _serialize_note(note)
    _check_read_access(data, current_user, db)

    cache_set(cache_key, data, NOTES_DETAIL_TTL)
    log.info("GET  note_id=%d  → db hit  title=%r", note_id, note.title)
    return data


# ── Update ────────────────────────────────────────────────────────────────────

@router.put("/{note_id}", response_model=NoteResponse)
@limiter.limit("30/minute", key_func=_get_user_or_ip)
def update_note(
    request: Request,
    note_id: int,
    updates: NoteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    changed = updates.model_dump(exclude_unset=True)
    log.info("UPDATE  user_id=%d  note_id=%d  fields=%s", current_user.id, note_id, list(changed.keys()))
    note = db.query(Note).filter(Note.id == note_id, Note.deleted_at.is_(None)).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    _check_ownership(note, current_user, db, allow_edit_share=True)
    before = {field: getattr(note, field) for field in changed}
    for field, value in changed.items():
        setattr(note, field, value)
    after = {field: getattr(note, field) for field in changed}
    log_action(db, action="note_update", user_id=current_user.id, resource_type="note",
               resource_id=note.id,
               details={"changed_fields": list(changed.keys()), "before": before, "after": after})
    db.commit()
    db.refresh(note)
    cache_delete(f"notes:detail:{note_id}")
    cache_delete_pattern("notes:list:*")
    log.info("UPDATE  note_id=%d  → cache invalidated", note_id)
    return note


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{note_id}", status_code=204)
@limiter.limit("30/minute", key_func=_get_user_or_ip)
def delete_note(
    request: Request,
    note_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    log.info("DELETE  user_id=%d  note_id=%d", current_user.id, note_id)
    note = db.query(Note).filter(Note.id == note_id, Note.deleted_at.is_(None)).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    _check_ownership(note, current_user)
    note.deleted_at = datetime.utcnow()
    log_action(db, action="note_delete", user_id=current_user.id, resource_type="note",
               resource_id=note.id)
    db.commit()
    cache_delete(f"notes:detail:{note_id}")
    cache_delete_pattern("notes:list:*")
    log.info("DELETE  note_id=%d  → soft-deleted  cache invalidated", note_id)
