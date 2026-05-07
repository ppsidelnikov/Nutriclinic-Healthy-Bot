"""add food_diary table

Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'food_diary',
        sa.Column('id',          sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('telegram_id', sa.String(),     nullable=False),
        sa.Column('eaten_at',    sa.DateTime(),   nullable=False, server_default=sa.func.now()),
        sa.Column('meal_type',   sa.String(20),   nullable=False),  # breakfast/lunch/dinner/snack
        sa.Column('dish_name',   sa.String(),     nullable=False),
        sa.Column('portion_g',   sa.Float(),      nullable=True),
        sa.Column('kcal',        sa.Float(),      nullable=False),
        sa.Column('protein_g',   sa.Float(),      nullable=True),
        sa.Column('fat_g',       sa.Float(),      nullable=True),
        sa.Column('carbs_g',     sa.Float(),      nullable=True),
        sa.Column('source',      sa.String(20),   nullable=False, server_default='photo'),
        sa.Column('created_at',  sa.DateTime(),   nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_food_diary_user_date', 'food_diary', ['telegram_id', 'eaten_at'])


def downgrade() -> None:
    op.drop_index('idx_food_diary_user_date', table_name='food_diary')
    op.drop_table('food_diary')
