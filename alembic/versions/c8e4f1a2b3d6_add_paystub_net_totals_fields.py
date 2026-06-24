"""add paystub net totals fields

Revision ID: c8e4f1a2b3d6
Revises: b4d9e2a1c6f7
Create Date: 2026-03-06 19:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c8e4f1a2b3d6"
down_revision: Union[str, Sequence[str], None] = "b4d9e2a1c6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "paystubs",
        sa.Column("total_deductions_cents", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "paystubs",
        sa.Column("net_pay_cents", sa.Integer(), nullable=False, server_default="0"),
    )

    op.execute(
        """
        UPDATE paystubs
        SET total_deductions_cents = 0,
            net_pay_cents = gross_pay_cents
        """
    )

    op.create_check_constraint(
        "ck_paystubs_total_deductions_nonnegative",
        "paystubs",
        "total_deductions_cents >= 0",
    )
    op.create_check_constraint(
        "ck_paystubs_net_pay_nonnegative",
        "paystubs",
        "net_pay_cents >= 0",
    )

    op.alter_column("paystubs", "total_deductions_cents", server_default=None)
    op.alter_column("paystubs", "net_pay_cents", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_paystubs_net_pay_nonnegative", "paystubs", type_="check")
    op.drop_constraint("ck_paystubs_total_deductions_nonnegative", "paystubs", type_="check")
    op.drop_column("paystubs", "net_pay_cents")
    op.drop_column("paystubs", "total_deductions_cents")
