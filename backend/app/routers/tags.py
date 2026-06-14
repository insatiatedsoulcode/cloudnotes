"""
Tag endpoints (F-13).

Tags are stored as a PostgreSQL TEXT[] array on each note (no separate table).
GIN index on notes.tags enables fast @> queries.

Cloud concept: PostgreSQL arrays vs. normalised many-to-many table.
Arrays work well here because:
  - Tags are small strings, not shared entities.
  - We only need contains-queries, not joins.
  - A separate tags table would add complexity without benefit at this scale.
"""

from typing import Any, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.logger import get_logger
from app.models.user import User

router = APIRouter(prefix="/tags", tags=["tags"])
log = get_logger("tags")


class TagCount(BaseModel):
    tag: str
    count: int


@router.get("/", response_model=List[TagCount])
def list_tags(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Return all tags the current user has applied to their own notes, with usage counts.

    unnest() is a PostgreSQL set-returning function — it expands a TEXT[] array into
    one row per element.  GROUP BY then counts how many notes each tag appears in.
    The GIN index on notes.tags speeds up the WHERE clause scan.
    """
    rows = db.execute(
        text("""
            SELECT unnest(tags) AS tag, COUNT(*) AS count
            FROM notes
            WHERE owner_id = :owner_id AND deleted_at IS NULL
            GROUP BY tag
            ORDER BY count DESC
        """),
        {"owner_id": current_user.id},
    ).fetchall()
    log.info("TAGS LIST  user_id=%d  distinct_tags=%d", current_user.id, len(rows))
    return [TagCount(tag=row.tag, count=row.count) for row in rows]
