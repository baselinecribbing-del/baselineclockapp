"""restore closed period guard on posted transition

Revision ID: c4d5e6f7a8b9
Revises: b7c8d9e0f1a2
Create Date: 2026-03-15 15:55:00.000000
"""

from alembic import op


revision = "c4d5e6f7a8b9"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION financial_core_block_posted_journal_entry_mutation()
        RETURNS trigger AS $$
        DECLARE
            line_count bigint;
            debit_total bigint;
            credit_total bigint;
            period_status text;
        BEGIN
            IF TG_OP = 'UPDATE' AND OLD.status = 'POSTED' THEN
                IF NEW.status <> 'POSTED' THEN
                    RAISE EXCEPTION 'journal_entries cannot transition from POSTED to another status';
                END IF;
                IF NEW.posted_at IS DISTINCT FROM OLD.posted_at THEN
                    RAISE EXCEPTION 'posted_at is immutable once journal entry is POSTED';
                END IF;
                IF NEW.posted_by_user_account_id IS DISTINCT FROM OLD.posted_by_user_account_id THEN
                    RAISE EXCEPTION 'posted_by_user_account_id is immutable once journal entry is POSTED';
                END IF;

                IF ROW(
                    NEW.entry_date,
                    NEW.fiscal_period_id,
                    NEW.source_type,
                    NEW.source_reference_id,
                    NEW.reference_number,
                    NEW.memo
                ) IS DISTINCT FROM ROW(
                    OLD.entry_date,
                    OLD.fiscal_period_id,
                    OLD.source_type,
                    OLD.source_reference_id,
                    OLD.reference_number,
                    OLD.memo
                ) THEN
                    RAISE EXCEPTION 'journal_entries in POSTED status are immutable';
                END IF;

                RETURN NEW;
            END IF;

            IF NEW.status = 'POSTED' AND (TG_OP = 'INSERT' OR OLD.status <> 'POSTED') THEN
                IF NEW.posted_at IS NULL THEN
                    RAISE EXCEPTION 'posted_at is required when journal entry status is POSTED';
                END IF;

                IF NEW.fiscal_period_id IS NOT NULL THEN
                    SELECT fp.status
                    INTO period_status
                    FROM fiscal_periods fp
                    WHERE fp.company_id = NEW.company_id
                      AND fp.fiscal_period_id = NEW.fiscal_period_id;

                    IF period_status IN ('CLOSED', 'LOCKED') THEN
                        RAISE EXCEPTION 'cannot mark journal entry as POSTED in a CLOSED or LOCKED fiscal period';
                    END IF;
                END IF;

                SELECT
                    COUNT(*)::bigint,
                    COALESCE(SUM(debit_amount_cents), 0)::bigint,
                    COALESCE(SUM(credit_amount_cents), 0)::bigint
                INTO line_count, debit_total, credit_total
                FROM journal_entry_lines
                WHERE company_id = NEW.company_id
                  AND journal_entry_id = NEW.journal_entry_id;

                IF line_count = 0 THEN
                    RAISE EXCEPTION 'cannot mark journal entry as POSTED without at least one line';
                END IF;
                IF debit_total <> credit_total THEN
                    RAISE EXCEPTION
                        'cannot mark journal entry as POSTED unless debits equal credits (debit_total_cents=%, credit_total_cents=%)',
                        debit_total,
                        credit_total;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION financial_core_block_posted_journal_entry_mutation()
        RETURNS trigger AS $$
        DECLARE
            line_count bigint;
            debit_total bigint;
            credit_total bigint;
        BEGIN
            IF TG_OP = 'UPDATE' AND OLD.status = 'POSTED' THEN
                IF NEW.status <> 'POSTED' THEN
                    RAISE EXCEPTION 'journal_entries cannot transition from POSTED to another status';
                END IF;
                IF NEW.posted_at IS DISTINCT FROM OLD.posted_at THEN
                    RAISE EXCEPTION 'posted_at is immutable once journal entry is POSTED';
                END IF;
                IF NEW.posted_by_user_account_id IS DISTINCT FROM OLD.posted_by_user_account_id THEN
                    RAISE EXCEPTION 'posted_by_user_account_id is immutable once journal entry is POSTED';
                END IF;

                IF ROW(
                    NEW.entry_date,
                    NEW.fiscal_period_id,
                    NEW.source_type,
                    NEW.source_reference_id,
                    NEW.reference_number,
                    NEW.memo
                ) IS DISTINCT FROM ROW(
                    OLD.entry_date,
                    OLD.fiscal_period_id,
                    OLD.source_type,
                    OLD.source_reference_id,
                    OLD.reference_number,
                    OLD.memo
                ) THEN
                    RAISE EXCEPTION 'journal_entries in POSTED status are immutable';
                END IF;

                RETURN NEW;
            END IF;

            IF NEW.status = 'POSTED' AND (TG_OP = 'INSERT' OR OLD.status <> 'POSTED') THEN
                IF NEW.posted_at IS NULL THEN
                    RAISE EXCEPTION 'posted_at is required when journal entry status is POSTED';
                END IF;

                SELECT
                    COUNT(*)::bigint,
                    COALESCE(SUM(debit_amount_cents), 0)::bigint,
                    COALESCE(SUM(credit_amount_cents), 0)::bigint
                INTO line_count, debit_total, credit_total
                FROM journal_entry_lines
                WHERE company_id = NEW.company_id
                  AND journal_entry_id = NEW.journal_entry_id;

                IF line_count = 0 THEN
                    RAISE EXCEPTION 'cannot mark journal entry as POSTED without at least one line';
                END IF;
                IF debit_total <> credit_total THEN
                    RAISE EXCEPTION
                        'cannot mark journal entry as POSTED unless debits equal credits (debit_total_cents=%, credit_total_cents=%)',
                        debit_total,
                        credit_total;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
