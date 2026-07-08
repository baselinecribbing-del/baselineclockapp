"""add journal posted immutability triggers

Revision ID: cd7e1f2a3b4c
Revises: bc5d1e2f3a4b
Create Date: 2026-03-15 12:00:00.000000
"""

from alembic import op


revision = "cd7e1f2a3b4c"
down_revision = "bc5d1e2f3a4b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION financial_core_block_posted_journal_entry_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'POSTED' THEN
                RAISE EXCEPTION 'journal_entries in POSTED status are immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_journal_entries_block_posted_update ON journal_entries;
        CREATE TRIGGER trg_journal_entries_block_posted_update
        BEFORE UPDATE ON journal_entries
        FOR EACH ROW
        EXECUTE FUNCTION financial_core_block_posted_journal_entry_mutation();

        CREATE OR REPLACE FUNCTION financial_core_block_posted_journal_entry_delete()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'POSTED' THEN
                RAISE EXCEPTION 'journal_entries in POSTED status cannot be deleted';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_journal_entries_block_posted_delete ON journal_entries;
        CREATE TRIGGER trg_journal_entries_block_posted_delete
        BEFORE DELETE ON journal_entries
        FOR EACH ROW
        EXECUTE FUNCTION financial_core_block_posted_journal_entry_delete();

        CREATE OR REPLACE FUNCTION financial_core_block_posted_journal_line_mutation()
        RETURNS trigger AS $$
        DECLARE
            target_company_id integer;
            target_journal_entry_id text;
            target_status text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                target_company_id := OLD.company_id;
                target_journal_entry_id := OLD.journal_entry_id;
            ELSE
                target_company_id := NEW.company_id;
                target_journal_entry_id := NEW.journal_entry_id;
            END IF;

            SELECT status
            INTO target_status
            FROM journal_entries
            WHERE company_id = target_company_id
              AND journal_entry_id = target_journal_entry_id;

            IF target_status = 'POSTED' THEN
                RAISE EXCEPTION 'journal_entry_lines for POSTED journal entries are immutable';
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_journal_entry_lines_block_posted_insert ON journal_entry_lines;
        CREATE TRIGGER trg_journal_entry_lines_block_posted_insert
        BEFORE INSERT ON journal_entry_lines
        FOR EACH ROW
        EXECUTE FUNCTION financial_core_block_posted_journal_line_mutation();

        DROP TRIGGER IF EXISTS trg_journal_entry_lines_block_posted_update ON journal_entry_lines;
        CREATE TRIGGER trg_journal_entry_lines_block_posted_update
        BEFORE UPDATE ON journal_entry_lines
        FOR EACH ROW
        EXECUTE FUNCTION financial_core_block_posted_journal_line_mutation();

        DROP TRIGGER IF EXISTS trg_journal_entry_lines_block_posted_delete ON journal_entry_lines;
        CREATE TRIGGER trg_journal_entry_lines_block_posted_delete
        BEFORE DELETE ON journal_entry_lines
        FOR EACH ROW
        EXECUTE FUNCTION financial_core_block_posted_journal_line_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_journal_entry_lines_block_posted_delete ON journal_entry_lines;
        DROP TRIGGER IF EXISTS trg_journal_entry_lines_block_posted_update ON journal_entry_lines;
        DROP TRIGGER IF EXISTS trg_journal_entry_lines_block_posted_insert ON journal_entry_lines;
        DROP FUNCTION IF EXISTS financial_core_block_posted_journal_line_mutation();

        DROP TRIGGER IF EXISTS trg_journal_entries_block_posted_delete ON journal_entries;
        DROP FUNCTION IF EXISTS financial_core_block_posted_journal_entry_delete();

        DROP TRIGGER IF EXISTS trg_journal_entries_block_posted_update ON journal_entries;
        DROP FUNCTION IF EXISTS financial_core_block_posted_journal_entry_mutation();
        """
    )
