"""add foreign keys from time_entries to employees jobs scopes

Revision ID: 7fbf9a61e31a
Revises: feba469a72f8
Create Date: 2026-02-20 20:21:35.539926
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7fbf9a61e31a"
down_revision: Union[str, Sequence[str], None] = "feba469a72f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_time_entries_employee_id_employees",
        "time_entries",
        "employees",
        ["employee_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_time_entries_job_id_jobs",
        "time_entries",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_time_entries_scope_id_scopes",
        "time_entries",
        "scopes",
        ["scope_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_time_entries_scope_id_scopes", "time_entries", type_="foreignkey")
    op.drop_constraint("fk_time_entries_job_id_jobs", "time_entries", type_="foreignkey")
    op.drop_constraint("fk_time_entries_employee_id_employees", "time_entries", type_="foreignkey")
