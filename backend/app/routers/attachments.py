import os
import re
from typing import List
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.logger import get_logger
from app.models.attachment import Attachment
from app.models.note import Note
from app.models.note_share import NoteShare
from app.models.user import User
from app.schemas.attachment import AttachmentResponse
from app.storage import StorageBackend, get_storage

router = APIRouter(prefix="/notes", tags=["attachments"])
log = get_logger("attachments")

_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_SIZE_MB = 10

# Magic-byte signatures for binary types we accept.
# Checked before trusting the client-supplied content-type.
_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff",       "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a",             "image/gif"),
    (b"GIF89a",             "image/gif"),
    (b"%PDF-",              "application/pdf"),
]
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "application/pdf", "text/plain"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_content_type(data: bytes) -> str:
    """Return MIME type inferred from magic bytes, or 'text/plain' for text-like data.

    Raises ValueError if the content cannot be classified as an allowed type.
    Binary data that doesn't match any known signature is rejected — this prevents
    disguising a .exe as image.png by renaming it.
    """
    for sig, mime in _MAGIC:
        if data[: len(sig)] == sig:
            return mime
    # No binary magic bytes — classify as text only if the first 512 bytes contain
    # no null characters (null bytes are a reliable marker of binary content).
    if b"\x00" not in data[:512]:
        return "text/plain"
    raise ValueError("Unsupported or unrecognised file type")


def _sanitize_filename(name: str) -> str:
    """Strip directory traversal, special chars, and length-limit the filename."""
    name = os.path.basename(name)                      # strip any path prefix
    name = re.sub(r"[^\w\-_\. ]", "_", name)          # allow safe chars only
    return name[:200] or "file"


def _serialize(att: Attachment, storage: StorageBackend) -> AttachmentResponse:
    return AttachmentResponse(
        id=att.id,
        note_id=att.note_id,
        filename=att.filename,
        content_type=att.content_type,
        size_bytes=att.size_bytes,
        url=storage.get_url(att.storage_path),
        created_at=att.created_at,
    )


def _require_note_write(note_id: int, user: User, db: Session) -> Note:
    """Owner or admin only — no share access for upload/delete."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="You don't own this note")
    return note


def _require_note_read(note_id: int, user: User, db: Session) -> Note:
    """Owner, admin, or any share recipient."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.visibility == "private" and note.owner_id != user.id and user.role != "admin":
        share = db.query(NoteShare).filter(
            NoteShare.note_id == note_id,
            NoteShare.shared_with_user_id == user.id,
        ).first()
        if not share:
            raise HTTPException(status_code=403, detail="This note is private")
    return note


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{note_id}/attachments", response_model=AttachmentResponse, status_code=201)
async def upload_attachment(
    note_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageBackend = Depends(get_storage),
):
    """
    Upload a file and attach it to a note.

    Allowed: JPEG, PNG, GIF, PDF, plain text. Max 10 MB.
    MIME type is validated from magic bytes — not from the client-supplied header.
    """
    _require_note_write(note_id, current_user, db)

    data = await file.read()

    if len(data) > _MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {_MAX_SIZE_MB} MB.",
        )

    try:
        content_type = _detect_content_type(data)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(_ALLOWED_TYPES))}.",
        )

    filename = _sanitize_filename(file.filename or "upload")
    # Prefix with a UUID to avoid filename collisions between uploads.
    key = f"{note_id}/{uuid4().hex}_{filename}"

    storage.save(key, data, content_type)
    log.info("UPLOAD  note_id=%d  filename=%r  size=%d  type=%s", note_id, filename, len(data), content_type)

    att = Attachment(
        note_id=note_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        storage_path=key,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return _serialize(att, storage)


@router.get("/{note_id}/attachments", response_model=List[AttachmentResponse])
def list_attachments(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageBackend = Depends(get_storage),
):
    """List all attachments for a note. Accessible to anyone with read access."""
    _require_note_read(note_id, current_user, db)
    atts = db.query(Attachment).filter(Attachment.note_id == note_id).all()
    return [_serialize(a, storage) for a in atts]


@router.delete("/{note_id}/attachments/{file_id}", status_code=204)
def delete_attachment(
    note_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageBackend = Depends(get_storage),
):
    """Delete an attachment. Owner or admin only."""
    _require_note_write(note_id, current_user, db)

    att = db.query(Attachment).filter(
        Attachment.id == file_id,
        Attachment.note_id == note_id,
    ).first()
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")

    storage.delete(att.storage_path)
    db.delete(att)
    db.commit()
    log.info("DELETE ATTACHMENT  att_id=%d  note_id=%d", file_id, note_id)
