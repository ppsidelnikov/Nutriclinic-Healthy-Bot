"""Drop FatSecret cache tables (moved to Redis)

Revision ID: a1b2c3d4e5f6
Revises: f868b681d923
Create Date: 2026-04-05 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f868b681d923'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('idx_search_query', table_name='fatsecret_search_cache')
    op.drop_index('idx_search_type', table_name='fatsecret_search_cache')
    op.drop_index('idx_created_at', table_name='fatsecret_search_cache')
    op.drop_table('fatsecret_search_cache')

    op.drop_index('idx_food_id', table_name='fatsecret_food_cache')
    op.drop_index('idx_food_name', table_name='fatsecret_food_cache')
    op.drop_index('idx_brand_name', table_name='fatsecret_food_cache')
    op.drop_table('fatsecret_food_cache')


def downgrade() -> None:
    op.create_table(
        'fatsecret_food_cache',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('fatsecret_food_id', sa.String(length=100), nullable=False),
        sa.Column('food_name', sa.String(length=500), nullable=False),
        sa.Column('brand_name', sa.String(length=200), nullable=True),
        sa.Column('food_description', sa.Text(), nullable=True),
        sa.Column('food_type', sa.String(length=100), nullable=True),
        sa.Column('food_url', sa.String(length=1000), nullable=True),
        sa.Column('calories_per_100g', sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column('protein_per_100g', sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column('fat_per_100g', sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column('carbs_per_100g', sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column('raw_api_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fatsecret_food_id'),
    )
    op.create_index('idx_food_id', 'fatsecret_food_cache', ['fatsecret_food_id'])
    op.create_index('idx_food_name', 'fatsecret_food_cache', ['food_name'])
    op.create_index('idx_brand_name', 'fatsecret_food_cache', ['brand_name'])

    op.create_table(
        'fatsecret_search_cache',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('search_query', sa.String(length=500), nullable=False),
        sa.Column('search_type', sa.String(length=50), nullable=False),
        sa.Column('max_results', sa.Integer(), nullable=False),
        sa.Column('api_response', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_search_query', 'fatsecret_search_cache', ['search_query'])
    op.create_index('idx_search_type', 'fatsecret_search_cache', ['search_type'])
    op.create_index('idx_created_at', 'fatsecret_search_cache', ['created_at'])
