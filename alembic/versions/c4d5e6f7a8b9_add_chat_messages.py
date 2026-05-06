"""Add chat_messages table for persistent dialog history

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-04-02 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_messages',
        sa.Column('id',         sa.Integer(),  autoincrement=True, nullable=False),
        sa.Column('chat_id',    sa.String(),   nullable=False),
        sa.Column('role',       sa.String(),   nullable=False),
        sa.Column('text',       sa.String(),   nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_chat_messages_chat_id',    'chat_messages', ['chat_id'])
    op.create_index('idx_chat_messages_created_at', 'chat_messages', ['created_at'])


def downgrade() -> None:
    op.drop_index('idx_chat_messages_created_at', table_name='chat_messages')
    op.drop_index('idx_chat_messages_chat_id',    table_name='chat_messages')
    op.drop_table('chat_messages')
