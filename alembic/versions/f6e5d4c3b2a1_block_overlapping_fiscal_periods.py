"""block overlapping fiscal periods

Revision ID: f6e5d4c3b2a1
Revises: c4d5e6f7a8b9
Create Date: 2026-03-15 16:20:00.000000
"""

from alembic import op


revision = "f6e5d4c3b2a1"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION financial_core_block_overlapping_fiscal_periods()
        RETURNS trigger AS $$
        DECLARE
            overlapping_period_id text;
        BEGIN
            SELECT fp.fiscal_period_id
            INTO overlapping_period_id
            FROM fiscal_periods fp
            WHERE fp.company_id = NEW.company_id
              AND fp.fiscal_period_id <> NEW.fiscal_period_id
              AND fp.period_start <= NEW.period_end
              AND fp.period_end >= NEW.period_start
            LIMIT 1;

            IF overlapping_period_id IS NOT NULL THEN
                RAISE EXCEPTION 'fiscal_periods cannot overlap for the same company';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_fiscal_periods_block_overlap_insert ON fiscal_periods;
        CREATE TRIGGER trg_fiscal_periods_block_overlap_insert
        BEFORE INSERT ON fiscal_periods
        FOR EACH ROW
        EXECUTE FUNCTION financial_core_block_overlapping_fiscal_periods();

        DROP TRIGGER IF EXISTS trg_fiscal_periods_block_overlap_update ON fiscal_periods;
        CREATE TRIGGER trg_fiscal_periods_block_overlap_update
        BEFORE UPDATE ON fiscal_periods
        FOR EACH ROW
        EXECUTE FUNCTION financial_core_block_overlapping_fiscal_periods();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_fiscal_periods_block_overlap_update ON fiscal_periods;
        DROP TRIGGER IF EXISTS trg_fiscal_periods_block_overlap_insert ON fiscal_periods;
        DROP FUNCTION IF EXISTS financial_core_block_overlapping_fiscal_periods();
        """
    )
