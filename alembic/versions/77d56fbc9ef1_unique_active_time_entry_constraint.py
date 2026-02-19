"""unique_active_time_entry_constraint

Revision ID: 77d56fbc9ef1
Revises: 732fdfd78939
Create Date: 2026-02-19 16:52:32.518154

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '77d56fbc9ef1'
down_revision: Union[str, Sequence[str], None] = '732fdfd78939'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_time_entries_active
        ON time_entries(company_id, employee_id)
        WHERE status = 'active';
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS uq_time_entries_active;")
