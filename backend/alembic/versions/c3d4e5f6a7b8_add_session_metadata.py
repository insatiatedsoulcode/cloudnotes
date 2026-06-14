"""add session metadata to refresh_tokens

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Both columns are nullable — existing rows get NULL, which the API returns as None.
    op.add_column('refresh_tokens', sa.Column('ip_address', sa.String(45), nullable=True))
    op.add_column('refresh_tokens', sa.Column('user_agent', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('refresh_tokens', 'user_agent')
    op.drop_column('refresh_tokens', 'ip_address')
