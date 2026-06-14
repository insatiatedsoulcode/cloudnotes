from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache import cache_delete_pattern
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.email import generate_token, hash_token
from app.logger import get_logger
from app.models.note import Note
from app.models.note_share import NoteShare
from app.models.share_link import ShareLink
from app.models.user import User
from app.schemas.note import NoteResponse
from app.schemas.note_share import ShareLinkResponse, ShareRequest, ShareResponse

router = APIRouter(prefix="/notes", tags=["sharing"])
log = get_logger("sharing")

_SHARE_LINK_TTL_DAYS = 7


def _require_note_owner(note_id: int, db: Session, current_user: User) -> Note:
    """Load the note and verify the caller owns it (or is admin). Raises 403/404."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.owner_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="You don't own this note")
    return note


# ── Share with specific user ──────────────────────────────────────────────────

@router.post("/{note_id}/share", response_model=ShareResponse, status_code=201)
def share_note_with_user(
    note_id: int,
    data: ShareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Share a note with another registered user.

    Idempotent: sharing with the same user again updates the permission.
    Concept: resource-level ACL — the same pattern as an S3 bucket policy
    granting a specific IAM principal read/write on a specific object.
    """
    note = _require_note_owner(note_id, db, current_user)

    target = db.query(User).filter(User.email == data.email).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == note.owner_id:
        raise HTTPException(status_code=400, detail="Cannot share a note with its own owner")

    existing = db.query(NoteShare).filter(
        NoteShare.note_id == note_id,
        NoteShare.shared_with_user_id == target.id,
    ).first()

    if existing:
        existing.permission = data.permission
        db.commit()
        db.refresh(existing)
        log.info("SHARE UPDATE  note_id=%d  target=%d  permission=%s", note_id, target.id, data.permission)
    else:
        existing = NoteShare(
            note_id=note_id,
            shared_with_user_id=target.id,
            permission=data.permission,
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)
        log.info("SHARE CREATE  note_id=%d  target=%d  permission=%s", note_id, target.id, data.permission)

    cache_delete_pattern("notes:list:*")
    return existing


@router.get("/{note_id}/shares", response_model=List[ShareResponse])
def list_note_shares(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all users this note has been shared with. Owner/admin only."""
    _require_note_owner(note_id, db, current_user)
    return db.query(NoteShare).filter(NoteShare.note_id == note_id).all()


@router.delete("/{note_id}/share/{share_id}", status_code=204)
def revoke_note_share(
    note_id: int,
    share_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke a specific share. The recipient immediately loses access."""
    _require_note_owner(note_id, db, current_user)
    share = db.query(NoteShare).filter(
        NoteShare.id == share_id,
        NoteShare.note_id == note_id,
    ).first()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    db.delete(share)
    db.commit()
    log.info("SHARE REVOKE  share_id=%d  note_id=%d", share_id, note_id)
    cache_delete_pattern("notes:list:*")


# ── Public share links ────────────────────────────────────────────────────────

@router.post("/{note_id}/share-link", response_model=ShareLinkResponse, status_code=201)
def create_share_link(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a public share link for a note.

    Each call replaces any existing active link (old link is revoked).
    Concept: S3 presigned URL — a time-limited capability URL that grants
    access to one resource without requiring the caller to authenticate.
    The token IS the credential; treat it like a password.
    """
    _require_note_owner(note_id, db, current_user)

    # Revoke any existing active link for this note.
    db.query(ShareLink).filter(
        ShareLink.note_id == note_id,
        ShareLink.revoked == False,  # noqa: E712
    ).update({"revoked": True})

    raw, hashed = generate_token()
    link = ShareLink(
        note_id=note_id,
        token_hash=hashed,
        expires_at=datetime.utcnow() + timedelta(days=_SHARE_LINK_TTL_DAYS),
    )
    db.add(link)
    db.commit()
    log.info("SHARE LINK CREATE  note_id=%d  expires=%s", note_id, link.expires_at)

    url = f"{settings.APP_BASE_URL}/api/notes/shared/{raw}"
    return ShareLinkResponse(token=raw, url=url, expires_at=link.expires_at)


@router.delete("/{note_id}/share-link", status_code=204)
def revoke_share_link(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke the active share link for a note. Existing holders of the URL lose access."""
    _require_note_owner(note_id, db, current_user)
    updated = db.query(ShareLink).filter(
        ShareLink.note_id == note_id,
        ShareLink.revoked == False,  # noqa: E712
    ).update({"revoked": True})
    db.commit()
    if not updated:
        raise HTTPException(status_code=404, detail="No active share link found")
    log.info("SHARE LINK REVOKE  note_id=%d", note_id)


@router.get("/shared/{token}", response_model=NoteResponse)
def access_via_share_link(token: str, db: Session = Depends(get_db)):
    """
    Read a note using a public share link token. No authentication required.

    The token is the credential — anyone who has the URL can access this note
    until the link expires or is revoked.
    """
    token_hash = hash_token(token)
    link = db.query(ShareLink).filter(
        ShareLink.token_hash == token_hash,
        ShareLink.revoked == False,  # noqa: E712
        ShareLink.expires_at > datetime.utcnow(),
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Share link not found or expired")

    note = db.query(Note).filter(Note.id == link.note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    log.info("SHARE LINK ACCESS  note_id=%d", note.id)
    return NoteResponse.model_validate(note).model_dump(mode="json")
