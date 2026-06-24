from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from app.models.chart_of_account import ChartOfAccount
from app.models.fiscal_period import FiscalPeriod
from app.models.journal_entry import JournalEntry
from app.models.journal_entry_line import JournalEntryLine


def _insert_account(*, db, company_id: int, code: str, normal_balance: str) -> ChartOfAccount:
    account = ChartOfAccount(
        company_id=int(company_id),
        code=str(code),
        name=f"Account {code}",
        account_type="ASSET" if normal_balance == "DEBIT" else "LIABILITY",
        normal_balance=str(normal_balance),
        allow_posting=True,
        is_active=True,
    )
    db.add(account)
    db.flush()
    return account


def _insert_period(*, db, company_id: int, status: str, name_suffix: str) -> FiscalPeriod:
    period = FiscalPeriod(
        company_id=int(company_id),
        name=f"2026-Q1-{name_suffix}",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
        status=str(status),
    )
    db.add(period)
    db.flush()
    return period


def _insert_draft_entry(*, db, company_id: int, fiscal_period_id: str | None = None) -> JournalEntry:
    entry = JournalEntry(
        company_id=int(company_id),
        entry_date=date(2026, 3, 15),
        status="DRAFT",
        fiscal_period_id=fiscal_period_id,
        source_type="MANUAL",
        source_reference_id="db-guard-test",
        reference_number="JE-DB-GUARD",
        memo="db guard test",
    )
    db.add(entry)
    db.flush()
    return entry


def _insert_line(
    *,
    db,
    company_id: int,
    journal_entry_id: str,
    line_number: int,
    account_id: str,
    debit_amount_cents: int = 0,
    credit_amount_cents: int = 0,
) -> JournalEntryLine:
    line = JournalEntryLine(
        company_id=int(company_id),
        journal_entry_id=str(journal_entry_id),
        line_number=int(line_number),
        account_id=str(account_id),
        debit_amount_cents=int(debit_amount_cents),
        credit_amount_cents=int(credit_amount_cents),
    )
    db.add(line)
    db.flush()
    return line


def _post_directly(*, db, entry: JournalEntry) -> None:
    entry.status = "POSTED"
    entry.posted_at = datetime.now(timezone.utc)
    db.commit()


def test_db_blocks_posting_unbalanced_entry():
    db = SessionLocal()
    try:
        company_id = 611
        debit_account = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit_account = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        entry = _insert_draft_entry(db=db, company_id=company_id)

        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit_account.account_id,
            debit_amount_cents=1000,
        )
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit_account.account_id,
            credit_amount_cents=900,
        )

        with pytest.raises(DBAPIError):
            _post_directly(db=db, entry=entry)
    finally:
        db.rollback()
        db.close()


def test_db_blocks_posting_entry_with_no_lines():
    db = SessionLocal()
    try:
        company_id = 612
        _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        entry = _insert_draft_entry(db=db, company_id=company_id)

        with pytest.raises(DBAPIError):
            _post_directly(db=db, entry=entry)
    finally:
        db.rollback()
        db.close()


def test_db_blocks_rollback_from_posted_to_draft():
    db = SessionLocal()
    try:
        company_id = 613
        debit_account = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit_account = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        entry = _insert_draft_entry(db=db, company_id=company_id)

        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit_account.account_id,
            debit_amount_cents=1000,
        )
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit_account.account_id,
            credit_amount_cents=1000,
        )
        _post_directly(db=db, entry=entry)

        entry.status = "DRAFT"
        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_db_blocks_nulling_posted_at_after_posted():
    db = SessionLocal()
    try:
        company_id = 614
        debit_account = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit_account = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        entry = _insert_draft_entry(db=db, company_id=company_id)

        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit_account.account_id,
            debit_amount_cents=1000,
        )
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit_account.account_id,
            credit_amount_cents=1000,
        )
        _post_directly(db=db, entry=entry)

        entry.posted_at = None
        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize(
    ("allow_posting", "is_active"),
    [
        (False, True),
        (True, False),
    ],
)
def test_db_blocks_journal_line_insert_for_inactive_or_non_postable_account(allow_posting: bool, is_active: bool):
    db = SessionLocal()
    try:
        company_id = 615
        account = _insert_account(db=db, company_id=company_id, code=f"31{int(allow_posting)}{int(is_active)}", normal_balance="DEBIT")
        account.allow_posting = allow_posting
        account.is_active = is_active
        entry = _insert_draft_entry(db=db, company_id=company_id)

        db.add(
            JournalEntryLine(
                company_id=int(company_id),
                journal_entry_id=str(entry.journal_entry_id),
                line_number=1,
                account_id=str(account.account_id),
                debit_amount_cents=100,
                credit_amount_cents=0,
            )
        )

        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_db_blocks_journal_line_update_to_non_postable_account():
    db = SessionLocal()
    try:
        company_id = 618
        debit_account = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        replacement_account = _insert_account(db=db, company_id=company_id, code="1999", normal_balance="DEBIT")
        replacement_account.allow_posting = False
        credit_account = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        entry = _insert_draft_entry(db=db, company_id=company_id)

        line = _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit_account.account_id,
            debit_amount_cents=1000,
        )
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit_account.account_id,
            credit_amount_cents=1000,
        )
        db.commit()

        line.account_id = replacement_account.account_id
        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_db_allows_posting_balanced_entry():
    db = SessionLocal()
    try:
        company_id = 615
        debit_account = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit_account = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        period = _insert_period(db=db, company_id=company_id, status="OPEN", name_suffix="OPEN")
        entry = _insert_draft_entry(db=db, company_id=company_id, fiscal_period_id=period.fiscal_period_id)

        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit_account.account_id,
            debit_amount_cents=2200,
        )
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit_account.account_id,
            credit_amount_cents=2200,
        )

        _post_directly(db=db, entry=entry)
        db.refresh(entry)
        assert entry.status == "POSTED"
        assert entry.posted_at is not None
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize("period_status", ["CLOSED", "LOCKED"])
def test_db_blocks_posting_with_closed_or_locked_period(period_status: str):
    db = SessionLocal()
    try:
        company_id = 616
        debit_account = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit_account = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        period = _insert_period(db=db, company_id=company_id, status=period_status, name_suffix=period_status)
        entry = _insert_draft_entry(db=db, company_id=company_id, fiscal_period_id=period.fiscal_period_id)

        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit_account.account_id,
            debit_amount_cents=500,
        )
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit_account.account_id,
            credit_amount_cents=500,
        )

        with pytest.raises(DBAPIError):
            _post_directly(db=db, entry=entry)
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize("period_status", ["CLOSED", "LOCKED"])
def test_db_blocks_insert_posted_with_closed_or_locked_period(period_status: str):
    db = SessionLocal()
    try:
        company_id = 617
        period = _insert_period(db=db, company_id=company_id, status=period_status, name_suffix=f"INS-{period_status}")
        posted_entry = JournalEntry(
            company_id=company_id,
            entry_date=date(2026, 3, 15),
            status="POSTED",
            fiscal_period_id=period.fiscal_period_id,
            source_type="MANUAL",
            source_reference_id="db-guard-test-insert",
            reference_number="JE-DB-INS",
            memo="db guard insert test",
            posted_at=datetime.now(timezone.utc),
        )
        db.add(posted_entry)

        with pytest.raises(DBAPIError):
            db.commit()
    finally:
        db.rollback()
        db.close()
