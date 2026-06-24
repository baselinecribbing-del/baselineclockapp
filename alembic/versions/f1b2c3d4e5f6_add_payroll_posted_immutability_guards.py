"""add payroll posted immutability guards

Revision ID: f1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-03-07 13:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION payroll_run_block_posted_rollback()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'POSTED' AND NEW.status <> 'POSTED' THEN
                RAISE EXCEPTION 'POSTED payroll runs are immutable and cannot transition backwards';
            END IF;
            IF OLD.status = 'POSTED' AND NEW.posted_at IS NULL THEN
                RAISE EXCEPTION 'POSTED payroll runs must retain posted_at';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_payroll_run_block_posted_rollback ON payroll_run;
        CREATE TRIGGER trg_payroll_run_block_posted_rollback
        BEFORE UPDATE ON payroll_run
        FOR EACH ROW
        EXECUTE FUNCTION payroll_run_block_posted_rollback();

        CREATE OR REPLACE FUNCTION payroll_items_guard_mutation()
        RETURNS trigger AS $$
        DECLARE
            run_status text;
            run_company_id integer;
            target_run_id text;
            target_company_id integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                target_run_id := OLD.payroll_run_id;
                target_company_id := OLD.company_id;
            ELSE
                target_run_id := NEW.payroll_run_id;
                target_company_id := NEW.company_id;
            END IF;

            SELECT pr.status, pr.company_id
            INTO run_status, run_company_id
            FROM payroll_run pr
            WHERE pr.payroll_run_id = target_run_id;

            IF run_status IS NULL THEN
                RAISE EXCEPTION 'Payroll run not found for payroll_items row';
            END IF;
            IF run_company_id <> target_company_id THEN
                RAISE EXCEPTION 'payroll_items company_id must match payroll_run company_id';
            END IF;
            IF run_status = 'POSTED' THEN
                RAISE EXCEPTION 'payroll_items are immutable once payroll run is POSTED';
            END IF;
            IF TG_OP <> 'DELETE' AND run_status NOT IN ('DRAFT', 'FINALIZED') THEN
                RAISE EXCEPTION 'payroll_items writes require payroll run in DRAFT or FINALIZED';
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_payroll_items_guard_mutation ON payroll_items;
        CREATE TRIGGER trg_payroll_items_guard_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON payroll_items
        FOR EACH ROW
        EXECUTE FUNCTION payroll_items_guard_mutation();

        CREATE OR REPLACE FUNCTION payroll_deductions_guard_mutation()
        RETURNS trigger AS $$
        DECLARE
            run_status text;
            run_company_id integer;
            target_run_id text;
            target_company_id integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                target_run_id := OLD.payroll_run_id;
                target_company_id := OLD.company_id;
            ELSE
                target_run_id := NEW.payroll_run_id;
                target_company_id := NEW.company_id;
            END IF;

            SELECT pr.status, pr.company_id
            INTO run_status, run_company_id
            FROM payroll_run pr
            WHERE pr.payroll_run_id = target_run_id;

            IF run_status IS NULL THEN
                RAISE EXCEPTION 'Payroll run not found for payroll_deductions row';
            END IF;
            IF run_company_id <> target_company_id THEN
                RAISE EXCEPTION 'payroll_deductions company_id must match payroll_run company_id';
            END IF;
            IF run_status = 'POSTED' THEN
                RAISE EXCEPTION 'payroll_deductions are immutable once payroll run is POSTED';
            END IF;
            IF TG_OP <> 'DELETE' AND run_status <> 'FINALIZED' THEN
                RAISE EXCEPTION 'payroll_deductions writes require payroll run in FINALIZED';
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_payroll_deductions_guard_mutation ON payroll_deductions;
        CREATE TRIGGER trg_payroll_deductions_guard_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON payroll_deductions
        FOR EACH ROW
        EXECUTE FUNCTION payroll_deductions_guard_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_payroll_deductions_guard_mutation ON payroll_deductions;
        DROP FUNCTION IF EXISTS payroll_deductions_guard_mutation();

        DROP TRIGGER IF EXISTS trg_payroll_items_guard_mutation ON payroll_items;
        DROP FUNCTION IF EXISTS payroll_items_guard_mutation();

        DROP TRIGGER IF EXISTS trg_payroll_run_block_posted_rollback ON payroll_run;
        DROP FUNCTION IF EXISTS payroll_run_block_posted_rollback();
        """
    )
