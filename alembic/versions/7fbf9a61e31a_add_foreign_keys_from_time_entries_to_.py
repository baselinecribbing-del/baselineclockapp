"""add foreign keys from time_entries to employees jobs scopes

Revision ID: 7fbf9a61e31a
Revises: feba469a72f8
Create Date: 2026-02-20 20:21:35.539926

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7fbf9a61e31a'
down_revision: Union[str, Sequence[str], None] = 'feba469a72f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
