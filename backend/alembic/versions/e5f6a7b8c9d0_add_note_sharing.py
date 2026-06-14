"""Add note sharing tables (note_shares + share_links)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'note_shares',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('note_id', sa.Integer(), nullable=False),
        sa.Column('shared_with_user_id', sa.Integer(), nullable=False),
        sa.Column('permission', sa.String(10), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['note_id'], ['notes.id']),
        sa.ForeignKeyConstraint(['shared_with_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('note_id', 'shared_with_user_id', name='uq_note_share'),
    )
    op.create_index('ix_note_shares_id', 'note_shares', ['id'])
    op.create_index('ix_note_shares_note_id', 'note_shares', ['note_id'])
    op.create_index('ix_note_shares_shared_with_user_id', 'note_shares', ['shared_with_user_id'])

    op.create_table(
        'share_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('note_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['note_id'], ['notes.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_share_links_id', 'share_links', ['id'])
    op.create_index('ix_share_links_note_id', 'share_links', ['note_id'])
    op.create_index('ix_share_links_token_hash', 'share_links', ['token_hash'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_share_links_token_hash', table_name='share_links')
    op.drop_index('ix_share_links_note_id', table_name='share_links')
    op.drop_index('ix_share_links_id', table_name='share_links')
    op.drop_table('share_links')

    op.drop_index('ix_note_shares_shared_with_user_id', table_name='note_shares')
    op.drop_index('ix_note_shares_note_id', table_name='note_shares')
    op.drop_index('ix_note_shares_id', table_name='note_shares')
    op.drop_table('note_shares')
