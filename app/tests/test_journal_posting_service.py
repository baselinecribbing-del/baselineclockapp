from datetime import date

import pytest

from app.database import SessionLocal
from app.models.chart_of_account import ChartOfAccount
from app.models.fiscal_period import FiscalPeriod
from app.models.journal_entry import JournalEntry
from app.services.journal_posting_service import (
    JournalPostingError,
    create_journal_entry_line_draft,
    delete_journal_entry_line_draft,
    post_journal_entry,
    update_journal_entry_draft,
    update_journal_entry_line_draft,
)


def _insert_account(*, db, company_id: int, code: str, name: str, normal_balance: str) -> ChartOfAccount:
    account = ChartOfAccount(
        company_id=int(company_id),
        code=str(code),
        name=str(name),
        account_type="ASSET" if normal_balance == "DEBIT" else "LIABILITY",
        normal_balance=str(normal_balance),
        allow_posting=True,
        is_active=True,
    )
    db.add(account)
    db.flush()
    return account


def _insert_entry(*, db, company_id: int, fiscal_period_id: str | None = None) -> JournalEntry:
    entry = JournalEntry(
        company_id=int(company_id),
        entry_date=date(2026, 3, 15),
        status="DRAFT",
        fiscal_period_id=fiscal_period_id,
        source_type="MANUAL",
        source_reference_id="test-source",
        reference_number="JE-TEST",
        memo="test memo",
    )
    db.add(entry)
    db.flush()
    return entry


def test_post_journal_entry_success_balanced_draft():
    db = SessionLocal()
    try:
        company_id = 501
        debit_account = _insert_account(
            db=db,
            company_id=company_id,
            code="1000",
            name="Cash",
            normal_balance="DEBIT",
        )
        credit_account = _insert_account(
            db=db,
            company_id=company_id,
            code="2000",
            name="Payable",
            normal_balance="CREDIT",
        )
        entry = _insert_entry(db=db, company_id=company_id)

        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit_account.account_id,
            debit_amount_cents=15000,
            credit_amount_cents=0,
        )
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit_account.account_id,
            debit_amount_cents=0,
            credit_amount_cents=15000,
        )

        result = post_journal_entry(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
        )
        db.commit()
        db.refresh(entry)

        assert result["ok"] is True
        assert result["debit_total_cents"] == 15000
        assert result["credit_total_cents"] == 15000
        assert entry.status == "POSTED"
        assert entry.posted_at is not None
    finally:
        db.rollback()
        db.close()


def test_post_journal_entry_fails_when_unbalanced():
    db = SessionLocal()
    try:
        company_id = 502
        debit_account = _insert_account(db=db, company_id=company_id, code="1000", name="Cash", normal_balance="DEBIT")
        credit_account = _insert_account(
            db=db,
            company_id=company_id,
            code="2000",
            name="Payable",
            normal_balance="CREDIT",
        )
        entry = _insert_entry(db=db, company_id=company_id)

        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit_account.account_id,
            debit_amount_cents=15000,
        )
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit_account.account_id,
            credit_amount_cents=14000,
        )

        with pytest.raises(JournalPostingError, match="unbalanced"):
            post_journal_entry(
                db=db,
                company_id=company_id,
                journal_entry_id=entry.journal_entry_id,
            )
    finally:
        db.rollback()
        db.close()


def test_post_journal_entry_fails_when_no_lines():
    db = SessionLocal()
    try:
        company_id = 503
        _insert_account(db=db, company_id=company_id, code="1000", name="Cash", normal_balance="DEBIT")
        entry = _insert_entry(db=db, company_id=company_id)

        with pytest.raises(JournalPostingError, match="without at least one line"):
            post_journal_entry(
                db=db,
                company_id=company_id,
                journal_entry_id=entry.journal_entry_id,
            )
    finally:
        db.rollback()
        db.close()


def test_update_posted_journal_entry_fails_via_service_path():
    db = SessionLocal()
    try:
        company_id = 504
        debit_account = _insert_account(db=db, company_id=company_id, code="1000", name="Cash", normal_balance="DEBIT")
        credit_account = _insert_account(
            db=db,
            company_id=company_id,
            code="2000",
            name="Payable",
            normal_balance="CREDIT",
        )
        entry = _insert_entry(db=db, company_id=company_id)
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit_account.account_id,
            debit_amount_cents=100,
        )
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit_account.account_id,
            credit_amount_cents=100,
        )
        post_journal_entry(db=db, company_id=company_id, journal_entry_id=entry.journal_entry_id)

        with pytest.raises(JournalPostingError, match="Only DRAFT"):
            update_journal_entry_draft(
                db=db,
                company_id=company_id,
                journal_entry_id=entry.journal_entry_id,
                memo="mutated",
            )
    finally:
        db.rollback()
        db.close()


def test_mutate_posted_journal_lines_fails_via_service_path():
    db = SessionLocal()
    try:
        company_id = 505
        debit_account = _insert_account(db=db, company_id=company_id, code="1000", name="Cash", normal_balance="DEBIT")
        credit_account = _insert_account(
            db=db,
            company_id=company_id,
            code="2000",
            name="Payable",
            normal_balance="CREDIT",
        )
        entry = _insert_entry(db=db, company_id=company_id)
        line_1 = create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit_account.account_id,
            debit_amount_cents=2500,
        )
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit_account.account_id,
            credit_amount_cents=2500,
        )
        post_journal_entry(db=db, company_id=company_id, journal_entry_id=entry.journal_entry_id)

        with pytest.raises(JournalPostingError, match="Only DRAFT"):
            update_journal_entry_line_draft(
                db=db,
                company_id=company_id,
                journal_entry_line_id=line_1.journal_entry_line_id,
                memo="mutated line",
            )

        with pytest.raises(JournalPostingError, match="Only DRAFT"):
            create_journal_entry_line_draft(
                db=db,
                company_id=company_id,
                journal_entry_id=entry.journal_entry_id,
                line_number=3,
                account_id=debit_account.account_id,
                debit_amount_cents=1,
            )

        with pytest.raises(JournalPostingError, match="Only DRAFT"):
            delete_journal_entry_line_draft(
                db=db,
                company_id=company_id,
                journal_entry_line_id=line_1.journal_entry_line_id,
            )
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
def test_create_journal_line_requires_active_postable_account(allow_posting: bool, is_active: bool):
    db = SessionLocal()
    try:
        company_id = 508
        blocked_account = _insert_account(
            db=db,
            company_id=company_id,
            code=f"3{int(allow_posting)}{int(is_active)}00",
            name="Blocked Account",
            normal_balance="DEBIT",
        )
        blocked_account.allow_posting = allow_posting
        blocked_account.is_active = is_active
        entry = _insert_entry(db=db, company_id=company_id)

        with pytest.raises(JournalPostingError, match="active posting account"):
            create_journal_entry_line_draft(
                db=db,
                company_id=company_id,
                journal_entry_id=entry.journal_entry_id,
                line_number=1,
                account_id=blocked_account.account_id,
                debit_amount_cents=100,
            )
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize("period_status", ["CLOSED", "LOCKED"])
def test_posting_into_closed_or_locked_period_fails(period_status: str):
    db = SessionLocal()
    try:
        company_id = 506
        debit_account = _insert_account(db=db, company_id=company_id, code="1000", name="Cash", normal_balance="DEBIT")
        credit_account = _insert_account(
            db=db,
            company_id=company_id,
            code="2000",
            name="Payable",
            normal_balance="CREDIT",
        )
        period = FiscalPeriod(
            company_id=company_id,
            name=f"2026-Q1-{period_status}",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 3, 31),
            status=period_status,
        )
        db.add(period)
        db.flush()

        entry = _insert_entry(
            db=db,
            company_id=company_id,
            fiscal_period_id=period.fiscal_period_id,
        )
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit_account.account_id,
            debit_amount_cents=100,
        )
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit_account.account_id,
            credit_amount_cents=100,
        )

        with pytest.raises(JournalPostingError, match="closed or locked fiscal period"):
            post_journal_entry(db=db, company_id=company_id, journal_entry_id=entry.journal_entry_id)
    finally:
        db.rollback()
        db.close()
