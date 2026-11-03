"""message created_at uses clock_timestamp

Revision ID: e3a1c7b52f04
Revises: d9000de13dcb
Create Date: 2026-11-02 23:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e3a1c7b52f04'
down_revision: Union[str, Sequence[str], None] = 'd9000de13dcb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A question and its answer share one transaction, so now() stamps both with the
    # same time; clock_timestamp() gives each insert its own time.
    op.alter_column('messages', 'created_at', server_default=sa.text('clock_timestamp()'))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('messages', 'created_at', server_default=sa.text('now()'))
