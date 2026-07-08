"""add bin service request email intake fields

Revision ID: d2a6c4e7b9f1
Revises: c1d2e3f4a5b6
Create Date: 2026-03-07 09:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d2a6c4e7b9f1"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bin_service_requests",
        sa.Column("parsed_confidence", sa.Numeric(precision=5, scale=2), nullable=True),
    )
    op.alter_column(
        "bin_service_requests",
        "customer_site_id",
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "bin_service_requests",
        "customer_site_id",
        existing_type=sa.String(),
        nullable=False,
    )
    op.drop_column("bin_service_requests", "parsed_confidence")
