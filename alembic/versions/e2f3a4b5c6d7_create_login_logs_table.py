"""Create login_logs table

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-02-06 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if table already exists
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'login_logs' not in inspector.get_table_names():
        op.create_table(
            'login_logs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('email', sa.String(255), nullable=False),
            sa.Column('ip_address', sa.String(45), nullable=False),
            sa.Column('success', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_login_logs_user_id', 'login_logs', ['user_id'])
        op.create_index('ix_login_logs_email', 'login_logs', ['email'])


def downgrade() -> None:
    op.drop_index('ix_login_logs_email', table_name='login_logs')
    op.drop_index('ix_login_logs_user_id', table_name='login_logs')
    op.drop_table('login_logs')
