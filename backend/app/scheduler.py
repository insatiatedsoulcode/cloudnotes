"""
Background scheduler (F-12b).

Three cleanup jobs run on a fixed schedule:
  - 02:00 daily  → hard-delete notes soft-deleted > 30 days ago
  - 03:00 daily  → purge expired refresh tokens
  - every hour   → mark expired share links as revoked

Each job function accepts an optional `db` session so tests can inject the
test-DB session instead of letting the job open its own via SessionLocal.

Cloud analogy:
  - APScheduler in-process ≈ cron; survives only while the process is alive.
  - For crash-safety, production would use AWS EventBridge Scheduler + Lambda
    or a Celery beat worker backed by SQS.  The "at-least-once" problem is why
    these jobs are idempotent (safe to run multiple times).
"""

from datetime import datetime, timedelta
import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.models.note import Note
from app.models.refresh_token import RefreshToken
from app.models.share_link import ShareLink

log = logging.getLogger("cloudnotes.scheduler")

_HARD_DELETE_AFTER_DAYS = 30

scheduler = AsyncIOScheduler()


# ── Job functions (also callable directly from tests) ─────────────────────────

def hard_delete_old_notes(db: Optional[Session] = None) -> int:
    """Hard-delete notes that have been soft-deleted for more than 30 days."""
    from app.database import SessionLocal
    _own = db is None
    if _own:
        db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=_HARD_DELETE_AFTER_DAYS)
        count = (
            db.query(Note)
            .filter(Note.deleted_at.isnot(None), Note.deleted_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        log.info("hard_delete_old_notes  purged=%d  cutoff=%s", count, cutoff.date())
        return count
    finally:
        if _own:
            db.close()


def purge_expired_refresh_tokens(db: Optional[Session] = None) -> int:
    """Delete refresh tokens that are past their expiry date."""
    from app.database import SessionLocal
    _own = db is None
    if _own:
        db = SessionLocal()
    try:
        count = (
            db.query(RefreshToken)
            .filter(RefreshToken.expires_at < datetime.utcnow())
            .delete(synchronize_session=False)
        )
        db.commit()
        log.info("purge_expired_refresh_tokens  purged=%d", count)
        return count
    finally:
        if _own:
            db.close()


def revoke_expired_share_links(db: Optional[Session] = None) -> int:
    """Mark share links whose expires_at has passed as revoked."""
    from app.database import SessionLocal
    _own = db is None
    if _own:
        db = SessionLocal()
    try:
        count = (
            db.query(ShareLink)
            .filter(
                ShareLink.expires_at < datetime.utcnow(),
                ShareLink.revoked == False,  # noqa: E712
            )
            .update({"revoked": True}, synchronize_session=False)
        )
        db.commit()
        log.info("revoke_expired_share_links  revoked=%d", count)
        return count
    finally:
        if _own:
            db.close()


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    scheduler.add_job(
        hard_delete_old_notes,
        CronTrigger(hour=2, minute=0),
        id="hard_delete_notes",
        replace_existing=True,
    )
    scheduler.add_job(
        purge_expired_refresh_tokens,
        CronTrigger(hour=3, minute=0),
        id="purge_refresh_tokens",
        replace_existing=True,
    )
    scheduler.add_job(
        revoke_expired_share_links,
        IntervalTrigger(hours=1),
        id="revoke_share_links",
        replace_existing=True,
    )
    scheduler.start()
    log.info("Scheduler started (3 jobs registered)")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("Scheduler stopped")
