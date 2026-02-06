"""Add has_customer_reply to submissions

Revision ID: d1e2f3a4b5c6
Revises: c8f91a3d5e72
Create Date: 2026-02-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c8f91a3d5e72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('form_submissions', sa.Column('has_customer_reply', sa.Boolean(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('form_submissions', 'has_customer_reply')
