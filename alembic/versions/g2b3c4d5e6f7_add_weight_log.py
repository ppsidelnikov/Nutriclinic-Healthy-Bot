"""add weight_log table

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'g2b3c4d5e6f7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'weight_log',
        sa.Column('id',           sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('telegram_id',  sa.String(),     nullable=False),
        sa.Column('weight_kg',    sa.Float(),      nullable=False),
        sa.Column('recorded_at',  sa.DateTime(),   nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_weight_log_user_date', 'weight_log', ['telegram_id', 'recorded_at'])


def downgrade() -> None:
    op.drop_index('idx_weight_log_user_date', table_name='weight_log')
    op.drop_table('weight_log')
