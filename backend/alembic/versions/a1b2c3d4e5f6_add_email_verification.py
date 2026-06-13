"""add email verification

Revision ID: a1b2c3d4e5f6
Revises: 959a20e0dea4
Create Date: 2026-06-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '959a20e0dea4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_verified to existing users table.
    # server_default=sa.false() is required to backfill existing rows safely
    # before the NOT NULL constraint is enforced.
    op.add_column(
        'users',
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        'email_verifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_email_verifications_id', 'email_verifications', ['id'], unique=False)
    op.create_index('ix_email_verifications_token_hash', 'email_verifications', ['token_hash'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_email_verifications_token_hash', table_name='email_verifications')
    op.drop_index('ix_email_verifications_id', table_name='email_verifications')
    op.drop_table('email_verifications')
    op.drop_column('users', 'is_verified')
