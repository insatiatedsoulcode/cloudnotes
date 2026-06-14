"""Add tags array column to notes

Revision ID: a8b9c0d1e2f3
Revises: 07a8b9c0d1e2
Create Date: 2026-06-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a8b9c0d1e2f3'
down_revision = '07a8b9c0d1e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'notes',
        sa.Column(
            'tags',
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default='{}',
        ),
    )
    # GIN index for fast array-contains (@>) queries.
    # e.g. WHERE tags @> ARRAY['cloud'] uses this index instead of seqscan.
    op.create_index('ix_notes_tags', 'notes', ['tags'], postgresql_using='gin')


def downgrade() -> None:
    op.drop_index('ix_notes_tags', table_name='notes')
    op.drop_column('notes', 'tags')
