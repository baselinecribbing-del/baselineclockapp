"""add issued status to invoices

Revision ID: b7e2c4d9a1f3
Revises: a9c4e2f7b1d3
Create Date: 2026-03-07 13:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b7e2c4d9a1f3"
down_revision: Union[str, Sequence[str], None] = "a9c4e2f7b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_invoices_status_valid", "invoices", type_="check")
    op.create_check_constraint(
        "ck_invoices_status_valid",
        "invoices",
        "status IN ('DRAFT','ISSUED','SENT','PAID','VOID')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_invoices_status_valid", "invoices", type_="check")
    op.create_check_constraint(
        "ck_invoices_status_valid",
        "invoices",
        "status IN ('DRAFT','SENT','PAID','VOID')",
    )
