"""Add knowledge_chunks table with pgvector

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-04-02 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        'knowledge_chunks',
        sa.Column('id',          sa.Integer(),  autoincrement=True, nullable=False),
        sa.Column('source',      sa.String(),   nullable=False),
        sa.Column('chunk_index', sa.Integer(),  nullable=False),
        sa.Column('text',        sa.String(),   nullable=False),
        sa.Column('embedding',   sa.Text(),     nullable=True),   # pgvector тип добавляется ниже
        sa.Column('created_at',  sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )

    # Меняем тип колонки на vector(1536) — нативный тип pgvector
    op.execute(f"ALTER TABLE knowledge_chunks ALTER COLUMN embedding TYPE vector({EMBEDDING_DIM}) USING embedding::vector({EMBEDDING_DIM})")

    # IVFFLAT-индекс для быстрого поиска по косинусному сходству
    op.execute("CREATE INDEX idx_knowledge_chunks_embedding ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")
    op.create_index('idx_knowledge_chunks_source', 'knowledge_chunks', ['source'])


def downgrade() -> None:
    op.drop_index('idx_knowledge_chunks_source',    table_name='knowledge_chunks')
    op.execute("DROP INDEX IF EXISTS idx_knowledge_chunks_embedding")
    op.drop_table('knowledge_chunks')
    op.execute("DROP EXTENSION IF EXISTS vector")
