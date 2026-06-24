from datetime import date

import pytest
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from app.models.chart_of_account import ChartOfAccount
from app.models.journal_entry import JournalEntry
from app.models.journal_entry_line import JournalEntryLine


def _insert_account(*, db, company_id: int, code: str, normal_balance: str = "DEBIT") -> ChartOfAccount:
    row = ChartOfAccount(
        company_id=int(company_id),
        code=str(code),
        name=f"Account {code}",
        account_type="ASSET" if normal_balance == "DEBIT" else "LIABILITY",
        normal_balance=str(normal_balance),
        allow_posting=True,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _insert_entry(*, db, company_id: int, ref: str) -> JournalEntry:
    row = JournalEntry(
        company_id=int(company_id),
        entry_date=date(2026, 3, 15),
        status="DRAFT",
        source_type="MANUAL",
        source_reference_id=f"seed-{ref}",
        reference_number=f"JE-{ref}",
        memo="journal storage invariant test",
    )
    db.add(row)
    db.flush()
    return row


def test_db_blocks_line_when_debit_and_credit_are_both_zero():
    db = SessionLocal()
    try:
        company_id = 1001
        account = _insert_account(db=db, company_id=company_id, code="1000")
        entry = _insert_entry(db=db, company_id=company_id, ref="ZERO")

        db.add(
            JournalEntryLine(
                company_id=company_id,
                journal_entry_id=entry.journal_entry_id,
                line_number=1,
                account_id=account.account_id,
                debit_amount_cents=0,
                credit_amount_cents=0,
            )
        )

        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_db_blocks_line_when_debit_and_credit_are_both_nonzero():
    db = SessionLocal()
    try:
        company_id = 1002
        account = _insert_account(db=db, company_id=company_id, code="1000")
        entry = _insert_entry(db=db, company_id=company_id, ref="BOTH")

        db.add(
            JournalEntryLine(
                company_id=company_id,
                journal_entry_id=entry.journal_entry_id,
                line_number=1,
                account_id=account.account_id,
                debit_amount_cents=50,
                credit_amount_cents=50,
            )
        )

        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize(
    ("debit_amount_cents", "credit_amount_cents"),
    [
        (-1, 0),
        (0, -1),
    ],
)
def test_db_blocks_negative_line_amounts(debit_amount_cents: int, credit_amount_cents: int):
    db = SessionLocal()
    try:
        company_id = 1003
        account = _insert_account(db=db, company_id=company_id, code="1000")
        entry = _insert_entry(db=db, company_id=company_id, ref="NEG")

        db.add(
            JournalEntryLine(
                company_id=company_id,
                journal_entry_id=entry.journal_entry_id,
                line_number=1,
                account_id=account.account_id,
                debit_amount_cents=debit_amount_cents,
                credit_amount_cents=credit_amount_cents,
            )
        )

        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_db_blocks_line_for_missing_journal_entry():
    db = SessionLocal()
    try:
        company_id = 1004
        account = _insert_account(db=db, company_id=company_id, code="1000")

        db.add(
            JournalEntryLine(
                company_id=company_id,
                journal_entry_id="missing-entry-id",
                line_number=1,
                account_id=account.account_id,
                debit_amount_cents=10,
                credit_amount_cents=0,
            )
        )

        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_db_blocks_line_for_missing_account():
    db = SessionLocal()
    try:
        company_id = 1005
        entry = _insert_entry(db=db, company_id=company_id, ref="NO-ACCOUNT")

        db.add(
            JournalEntryLine(
                company_id=company_id,
                journal_entry_id=entry.journal_entry_id,
                line_number=1,
                account_id="missing-account-id",
                debit_amount_cents=10,
                credit_amount_cents=0,
            )
        )

        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_db_blocks_cross_company_line_references():
    db = SessionLocal()
    try:
        account_company_one = _insert_account(db=db, company_id=1006, code="1000")
        entry_company_two = _insert_entry(db=db, company_id=1007, ref="XCOMP")

        db.add(
            JournalEntryLine(
                company_id=1006,
                journal_entry_id=entry_company_two.journal_entry_id,
                line_number=1,
                account_id=account_company_one.account_id,
                debit_amount_cents=10,
                credit_amount_cents=0,
            )
        )

        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_db_blocks_duplicate_line_number_within_entry():
    db = SessionLocal()
    try:
        company_id = 1008
        debit_account = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit_account = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        entry = _insert_entry(db=db, company_id=company_id, ref="LINE-NO")

        db.add(
            JournalEntryLine(
                company_id=company_id,
                journal_entry_id=entry.journal_entry_id,
                line_number=1,
                account_id=debit_account.account_id,
                debit_amount_cents=25,
                credit_amount_cents=0,
            )
        )
        db.add(
            JournalEntryLine(
                company_id=company_id,
                journal_entry_id=entry.journal_entry_id,
                line_number=1,
                account_id=credit_account.account_id,
                debit_amount_cents=0,
                credit_amount_cents=25,
            )
        )

        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()

