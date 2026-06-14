"""Add full-text search vector to notes

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None

_TRIGGER_FUNC = """
CREATE OR REPLACE FUNCTION notes_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.content, '')), 'B');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_TRIGGER = """
CREATE TRIGGER notes_search_vector_trigger
BEFORE INSERT OR UPDATE ON notes
FOR EACH ROW EXECUTE FUNCTION notes_search_vector_update();
"""

_BACKFILL = """
UPDATE notes SET
    search_vector =
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(content, '')), 'B');
"""


def upgrade() -> None:
    op.add_column('notes', sa.Column('search_vector', postgresql.TSVECTOR(), nullable=True))
    op.create_index('ix_notes_search_vector', 'notes', ['search_vector'],
                    postgresql_using='gin')
    op.execute(_TRIGGER_FUNC)
    op.execute(_TRIGGER)
    op.execute(_BACKFILL)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS notes_search_vector_trigger ON notes")
    op.execute("DROP FUNCTION IF EXISTS notes_search_vector_update()")
    op.drop_index('ix_notes_search_vector', table_name='notes')
    op.drop_column('notes', 'search_vector')
