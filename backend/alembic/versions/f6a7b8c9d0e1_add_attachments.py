"""Add attachments table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'attachments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('note_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('content_type', sa.String(100), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('storage_path', sa.String(500), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['note_id'], ['notes.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_attachments_id', 'attachments', ['id'])
    op.create_index('ix_attachments_note_id', 'attachments', ['note_id'])


def downgrade() -> None:
    op.drop_index('ix_attachments_note_id', table_name='attachments')
    op.drop_index('ix_attachments_id', table_name='attachments')
    op.drop_table('attachments')
