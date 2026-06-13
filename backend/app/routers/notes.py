from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
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
from app.dependencies import get_current_user
from app.limiter import _get_user_or_ip, limiter
from app.logger import get_logger
from app.models.note import Note
from app.models.user import User
from app.schemas.note import NoteCreate, NoteResponse, NoteUpdate

router = APIRouter(prefix="/notes", tags=["notes"])
log = get_logger("notes")


def _check_ownership(note: Note, user: User) -> None:
    """Raise 403 if the user doesn't own the note and isn't an admin."""
    if note.owner_id != user.id and user.role != "admin":
        log.warning(
            "FORBIDDEN  user_id=%d tried to modify note_id=%d owned by user_id=%s",
            user.id, note.id, note.owner_id,
        )
        raise HTTPException(status_code=403, detail="You don't own this note")


def _check_read_access(note_data: dict, user: User) -> None:
    """Raise 403 if a private note is accessed by a non-owner non-admin."""
    if note_data.get("visibility") == "private":
        if note_data.get("owner_id") != user.id and user.role != "admin":
            raise HTTPException(status_code=403, detail="This note is private")


def _serialize_note(note: Note) -> dict:
    """Convert ORM Note → JSON-safe dict via Pydantic (handles datetime → ISO string)."""
    return NoteResponse.model_validate(note).model_dump(mode="json")


# ── List (scoped) ─────────────────────────────────────────────────────────────

@router.get("/", response_model=List[NoteResponse])
def list_notes(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    # Cache key is per-user: admins see all notes, regular users see a subset.
    cache_key = f"notes:list:{current_user.id}:{skip}:{limit}"
    log.info("LIST  user_id=%d  skip=%d  limit=%d", current_user.id, skip, limit)

    cached = cache_get(cache_key)
    if cached is not None:
        log.info("LIST  → cache hit  count=%d", len(cached))
        return cached

    query = db.query(Note).order_by(Note.created_at.desc())
    if current_user.role != "admin":
        # Regular users see their own notes + everyone's public notes
        query = query.filter(
            or_(Note.owner_id == current_user.id, Note.visibility == "public")
        )
    notes = query.offset(skip).limit(limit).all()

    data = [_serialize_note(n) for n in notes]
    cache_set(cache_key, data, NOTES_LIST_TTL)
    log.info("LIST  → db hit  count=%d  cached for %ds", len(data), NOTES_LIST_TTL)
    return data


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("/", response_model=NoteResponse, status_code=201)
@limiter.limit("30/minute", key_func=_get_user_or_ip)
def create_note(
    request: Request,
    note: NoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
        _check_read_access(cached, current_user)
        log.info("GET  note_id=%d  → cache hit", note_id)
        return cached

    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        log.warning("GET  note_id=%d  → 404", note_id)
        raise HTTPException(status_code=404, detail="Note not found")

    data = _serialize_note(note)
    _check_read_access(data, current_user)

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
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    _check_ownership(note, current_user)
    for field, value in changed.items():
        setattr(note, field, value)
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
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    _check_ownership(note, current_user)
    db.delete(note)
    db.commit()
    cache_delete(f"notes:detail:{note_id}")
    cache_delete_pattern("notes:list:*")
    log.info("DELETE  note_id=%d  → cache invalidated", note_id)
