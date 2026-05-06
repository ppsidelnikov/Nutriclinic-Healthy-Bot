"""Add user_profile table

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-04-02 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_profile',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('telegram_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('age', sa.Integer(), nullable=True),
        sa.Column('gender', sa.String(), nullable=True),
        sa.Column('weight_kg', sa.Numeric(5, 1), nullable=True),
        sa.Column('height_cm', sa.Numeric(5, 1), nullable=True),
        sa.Column('goal', sa.String(), nullable=True),
        sa.Column('daily_calories_target', sa.Integer(), nullable=True),
        sa.Column('restrictions', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_id', name='uq_user_profile_telegram_id'),
    )
    op.create_index('idx_user_profile_telegram_id', 'user_profile', ['telegram_id'])


def downgrade() -> None:
    op.drop_index('idx_user_profile_telegram_id', table_name='user_profile')
    op.drop_table('user_profile')
