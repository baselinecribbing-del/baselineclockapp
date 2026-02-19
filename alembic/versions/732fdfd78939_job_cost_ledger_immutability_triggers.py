"""job_cost_ledger_immutability_triggers

Revision ID: 732fdfd78939
Revises: c4d09a62d3c6
Create Date: 2026-02-19 16:44:23.526846

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '732fdfd78939'
down_revision: Union[str, Sequence[str], None] = 'c4d09a62d3c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION job_cost_ledger_block_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'job_cost_ledger is immutable';
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_job_cost_ledger_block_update ON job_cost_ledger;
        CREATE TRIGGER trg_job_cost_ledger_block_update
        BEFORE UPDATE ON job_cost_ledger
        FOR EACH ROW
        EXECUTE FUNCTION job_cost_ledger_block_mutation();

        DROP TRIGGER IF EXISTS trg_job_cost_ledger_block_delete ON job_cost_ledger;
        CREATE TRIGGER trg_job_cost_ledger_block_delete
        BEFORE DELETE ON job_cost_ledger
        FOR EACH ROW
        EXECUTE FUNCTION job_cost_ledger_block_mutation();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_job_cost_ledger_block_update ON job_cost_ledger;
        DROP TRIGGER IF EXISTS trg_job_cost_ledger_block_delete ON job_cost_ledger;
        DROP FUNCTION IF EXISTS job_cost_ledger_block_mutation();
        """
    )
