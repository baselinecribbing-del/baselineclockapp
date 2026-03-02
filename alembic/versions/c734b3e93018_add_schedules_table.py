"""add schedules table

Revision ID: c734b3e93018
Revises: ff118af48e9d
Create Date: 2026-03-02 07:04:33.855544

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c734b3e93018"
down_revision: Union[str, Sequence[str], None] = "ff118af48e9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("schedule_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name="fk_schedules_employee_id_employees",
        ),
        sa.PrimaryKeyConstraint("schedule_id", name="schedules_pkey"),
    )

    op.create_index("ix_schedules_company_id", "schedules", ["company_id"], unique=False)
    op.create_index("ix_schedules_employee_id", "schedules", ["employee_id"], unique=False)
    op.create_index("ix_schedules_scheduled_date", "schedules", ["scheduled_date"], unique=False)
    op.create_index("ix_schedules_status", "schedules", ["status"], unique=False)

    # Only one ACTIVE schedule per employee per day (per company)
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_schedules_active_employee_day
        ON schedules(company_id, employee_id, scheduled_date)
        WHERE status = 'ACTIVE';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_schedules_active_employee_day;")
    op.drop_index("ix_schedules_status", table_name="schedules")
    op.drop_index("ix_schedules_scheduled_date", table_name="schedules")
    op.drop_index("ix_schedules_employee_id", table_name="schedules")
    op.drop_index("ix_schedules_company_id", table_name="schedules")
    op.drop_table("schedules")
