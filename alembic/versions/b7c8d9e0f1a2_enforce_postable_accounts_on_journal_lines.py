"""enforce postable accounts on journal lines

Revision ID: b7c8d9e0f1a2
Revises: e2f3a4b5c6d7
Create Date: 2026-03-15 15:20:00.000000
"""

from alembic import op


revision = "b7c8d9e0f1a2"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION financial_core_enforce_postable_journal_line_account()
        RETURNS trigger AS $$
        DECLARE
            account_is_active boolean;
            account_allow_posting boolean;
        BEGIN
            SELECT coa.is_active, coa.allow_posting
            INTO account_is_active, account_allow_posting
            FROM chart_of_accounts coa
            WHERE coa.company_id = NEW.company_id
              AND coa.account_id = NEW.account_id;

            IF account_is_active IS DISTINCT FROM TRUE OR account_allow_posting IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION
                    'journal_entry_lines must reference active chart_of_accounts rows with allow_posting=true';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_journal_entry_lines_require_postable_account ON journal_entry_lines;
        CREATE TRIGGER trg_journal_entry_lines_require_postable_account
        BEFORE INSERT OR UPDATE ON journal_entry_lines
        FOR EACH ROW
        EXECUTE FUNCTION financial_core_enforce_postable_journal_line_account();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_journal_entry_lines_require_postable_account ON journal_entry_lines;
        DROP FUNCTION IF EXISTS financial_core_enforce_postable_journal_line_account();
        """
    )
