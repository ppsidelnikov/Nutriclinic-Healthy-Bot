"""add created_at to food_model_answer_log

Revision ID: e1f2a3b4c5d6
Revises: d5e6f7a8b9c0
Create Date: 2026-04-09
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1f2a3b4c5d6'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'food_model_answer_log',
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
    )
    # Заполняем существующие строки текущим временем
    op.execute("UPDATE food_model_answer_log SET created_at = NOW() WHERE created_at IS NULL")


def downgrade():
    op.drop_column('food_model_answer_log', 'created_at')
