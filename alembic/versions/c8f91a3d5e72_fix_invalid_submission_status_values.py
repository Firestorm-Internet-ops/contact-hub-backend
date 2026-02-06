"""Fix invalid submission status values

Revision ID: c8f91a3d5e72
Revises: b7565edcdb5c
Create Date: 2026-02-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8f91a3d5e72'
down_revision: Union[str, None] = 'b7565edcdb5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Valid status values according to the Pydantic schema
VALID_STATUSES = ('new', 'waiting_internal', 'waiting_customer', 'in_progress', 'closed')


def upgrade() -> None:
    # Convert all invalid status values to 'new'
    # This handles 'unread', 'read', 'pending', and any other invalid values
    op.execute(
        f"""
        UPDATE form_submissions
        SET status = 'new'
        WHERE status NOT IN {VALID_STATUSES}
        """
    )


def downgrade() -> None:
    # No downgrade - we can't restore the original invalid values
    pass
