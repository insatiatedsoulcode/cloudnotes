"""
F-12: Background Tasks tests.

Part A — FastAPI BackgroundTasks:
  - Verification email is dispatched as a background task after register.
  - Password reset email is dispatched as a background task after forgot-password.
  - Resend-verification email is dispatched as a background task.
  (With TestClient, background tasks run synchronously before the response is
   returned, so we can assert mock call counts in the same test.)

Part B — APScheduler job functions:
  - hard_delete_old_notes: permanently removes notes soft-deleted > 30 days ago.
  - purge_expired_refresh_tokens: deletes expired tokens.
  - revoke_expired_share_links: marks expired-but-still-active links as revoked.
  Each job is called directly with a test DB session so the scheduler never
  touches the dev/prod database during tests.
"""

from datetime import datetime, timedelta

import pytest

from app.scheduler import (
    hard_delete_old_notes,
    purge_expired_refresh_tokens,
    revoke_expired_share_links,
)
from tests.conftest import make_note, _auto_verify


# ── F-12a: BackgroundTasks ────────────────────────────────────────────────────

def test_register_sends_verification_email_as_background_task(client, mock_email):
    """Email mock is called exactly once after a successful register."""
    res = client.post("/api/auth/register", json={
        "email": "bg@test.com", "password": "Password123",
    })
    assert res.status_code == 201
    # TestClient runs background tasks before returning — mock must have been called.
    mock_email.assert_called_once()
    assert mock_email.call_args.kwargs["to"] == "bg@test.com"


def test_forgot_password_sends_reset_email_as_background_task(client, mock_password_reset_email):
    """Reset email mock is called after forgot-password for a registered user."""
    client.post("/api/auth/register", json={"email": "reset@test.com", "password": "Password123"})
    res = client.post("/api/auth/forgot-password", json={"email": "reset@test.com"})
    assert res.status_code == 200
    mock_password_reset_email.assert_called_once()
    assert mock_password_reset_email.call_args.kwargs["to"] == "reset@test.com"


def test_forgot_password_unknown_email_does_not_call_email(client, mock_password_reset_email):
    """No email is sent for an unrecognised address (enumeration prevention)."""
    res = client.post("/api/auth/forgot-password", json={"email": "ghost@test.com"})
    assert res.status_code == 200
    mock_password_reset_email.assert_not_called()


def test_resend_verification_sends_email_as_background_task(client, mock_email):
    """Resend-verification fires email via BackgroundTasks."""
    res = client.post("/api/auth/register", json={"email": "resend@test.com", "password": "Password123"})
    assert res.status_code == 201
    user_id = res.json()["id"]

    # Log in without verifying
    login_res = client.post("/api/auth/login", data={"username": "resend@test.com", "password": "Password123"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    mock_email.reset_mock()
    res2 = client.post("/api/auth/resend-verification", headers=headers)
    assert res2.status_code == 200
    mock_email.assert_called_once()


# ── F-12b: Scheduler jobs ─────────────────────────────────────────────────────

def test_hard_delete_old_notes_removes_stale_deleted_notes(client, auth_headers, db_session):
    """Notes soft-deleted > 30 days ago are permanently removed."""
    from app.models.note import Note

    note = make_note(client, auth_headers, title="old deleted")
    # Manually set deleted_at to 31 days ago
    db_note = db_session.query(Note).filter(Note.id == note["id"]).first()
    db_note.deleted_at = datetime.utcnow() - timedelta(days=31)
    db_session.commit()

    count = hard_delete_old_notes(db=db_session)
    assert count == 1

    remaining = db_session.query(Note).filter(Note.id == note["id"]).first()
    assert remaining is None


def test_hard_delete_skips_recently_deleted_notes(client, auth_headers, db_session):
    """Notes soft-deleted less than 30 days ago are NOT permanently removed."""
    from app.models.note import Note

    note = make_note(client, auth_headers, title="recent delete")
    db_note = db_session.query(Note).filter(Note.id == note["id"]).first()
    db_note.deleted_at = datetime.utcnow() - timedelta(days=10)
    db_session.commit()

    count = hard_delete_old_notes(db=db_session)
    assert count == 0

    remaining = db_session.query(Note).filter(Note.id == note["id"]).first()
    assert remaining is not None


def test_hard_delete_skips_live_notes(client, auth_headers, db_session):
    """Live notes (deleted_at IS NULL) are never touched."""
    from app.models.note import Note

    note = make_note(client, auth_headers, title="live note")
    count = hard_delete_old_notes(db=db_session)
    assert count == 0

    remaining = db_session.query(Note).filter(Note.id == note["id"]).first()
    assert remaining is not None


def test_purge_expired_refresh_tokens_removes_expired(db_session, registered_user, client):
    """Expired refresh tokens are deleted by the purge job."""
    from app.models.refresh_token import RefreshToken
    from app.routers.auth import _hash
    from app.email import generate_token

    raw, hashed = generate_token()
    rt = RefreshToken(
        user_id=registered_user["id"],
        token_hash=hashed,
        expires_at=datetime.utcnow() - timedelta(hours=1),
        ip_address="127.0.0.1",
        user_agent="test",
    )
    db_session.add(rt)
    db_session.commit()

    rt_id = rt.id
    count = purge_expired_refresh_tokens(db=db_session)
    assert count >= 1

    remaining = db_session.query(RefreshToken).filter(RefreshToken.id == rt_id).first()
    assert remaining is None


def test_purge_expired_refresh_tokens_keeps_valid(db_session, registered_user):
    """Active (non-expired) tokens are not purged."""
    from app.models.refresh_token import RefreshToken
    from app.email import generate_token

    raw, hashed = generate_token()
    rt = RefreshToken(
        user_id=registered_user["id"],
        token_hash=hashed,
        expires_at=datetime.utcnow() + timedelta(days=7),
        ip_address="127.0.0.1",
        user_agent="test",
    )
    db_session.add(rt)
    db_session.commit()

    purge_expired_refresh_tokens(db=db_session)

    remaining = db_session.query(RefreshToken).filter(RefreshToken.id == rt.id).first()
    assert remaining is not None


def test_revoke_expired_share_links(db_session, registered_user, client, auth_headers):
    """Share links whose expires_at is in the past are marked revoked."""
    from app.models.share_link import ShareLink
    from app.email import generate_token, hash_token

    note = make_note(client, auth_headers)
    raw, hashed = generate_token()
    link = ShareLink(
        note_id=note["id"],
        token_hash=hashed,
        expires_at=datetime.utcnow() - timedelta(hours=1),
        revoked=False,
    )
    db_session.add(link)
    db_session.commit()

    count = revoke_expired_share_links(db=db_session)
    assert count >= 1

    db_session.refresh(link)
    assert link.revoked is True


def test_revoke_expired_share_links_skips_active(db_session, registered_user, client, auth_headers):
    """Active (non-expired) share links are not revoked."""
    from app.models.share_link import ShareLink
    from app.email import generate_token

    note = make_note(client, auth_headers)
    raw, hashed = generate_token()
    link = ShareLink(
        note_id=note["id"],
        token_hash=hashed,
        expires_at=datetime.utcnow() + timedelta(days=7),
        revoked=False,
    )
    db_session.add(link)
    db_session.commit()

    revoke_expired_share_links(db=db_session)

    db_session.refresh(link)
    assert link.revoked is False


def test_revoke_expired_share_links_skips_already_revoked(db_session, registered_user, client, auth_headers):
    """Already-revoked links are not counted again."""
    from app.models.share_link import ShareLink
    from app.email import generate_token

    note = make_note(client, auth_headers)
    raw, hashed = generate_token()
    link = ShareLink(
        note_id=note["id"],
        token_hash=hashed,
        expires_at=datetime.utcnow() - timedelta(hours=1),
        revoked=True,  # already revoked
    )
    db_session.add(link)
    db_session.commit()

    count = revoke_expired_share_links(db=db_session)
    assert count == 0
