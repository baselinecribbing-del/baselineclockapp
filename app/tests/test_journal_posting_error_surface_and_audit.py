from datetime import date

import pytest

from app.database import SessionLocal
from app.models.chart_of_account import ChartOfAccount
from app.models.fiscal_period import FiscalPeriod
from app.models.journal_entry import JournalEntry
from app.models.journal_posting_audit_event import JournalPostingAuditEvent
from app.services.journal_posting_service import (
    ERROR_CODE_PERIOD_CLOSED,
    ERROR_CODE_UNBALANCED,
    JournalPostingApplicationError,
    create_journal_entry_line_draft,
    post_journal_entry_with_audit,
)


def _insert_account(*, db, company_id: int, code: str, normal_balance: str) -> ChartOfAccount:
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


def _insert_period(*, db, company_id: int, status: str) -> FiscalPeriod:
    row = FiscalPeriod(
        company_id=int(company_id),
        name=f"2026-Q1-{status}-{company_id}",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
        status=str(status),
    )
    db.add(row)
    db.flush()
    return row


def _insert_entry(*, db, company_id: int, fiscal_period_id: str | None = None) -> JournalEntry:
    row = JournalEntry(
        company_id=int(company_id),
        entry_date=date(2026, 3, 15),
        status="DRAFT",
        fiscal_period_id=fiscal_period_id,
        source_type="MANUAL",
        source_reference_id=f"src-{company_id}",
        reference_number=f"JE-{company_id}",
        memo="posting test",
    )
    db.add(row)
    db.flush()
    return row


def _fetch_latest_audit(*, company_id: int, journal_entry_id: str) -> JournalPostingAuditEvent | None:
    db = SessionLocal()
    try:
        return (
            db.query(JournalPostingAuditEvent)
            .filter(JournalPostingAuditEvent.company_id == int(company_id))
            .filter(JournalPostingAuditEvent.journal_entry_id == str(journal_entry_id))
            .order_by(JournalPostingAuditEvent.created_at.desc())
            .first()
        )
    finally:
        db.close()


def test_posting_success_creates_success_audit_event():
    db = SessionLocal()
    try:
        company_id = 701
        debit = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        entry = _insert_entry(db=db, company_id=company_id)
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit.account_id,
            debit_amount_cents=1200,
        )
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit.account_id,
            credit_amount_cents=1200,
        )
        db.commit()

        result = post_journal_entry_with_audit(db=db, company_id=company_id, journal_entry_id=entry.journal_entry_id)
        db.commit()

        assert result["ok"] is True
        event = _fetch_latest_audit(company_id=company_id, journal_entry_id=entry.journal_entry_id)
        assert event is not None
        assert event.result == "SUCCESS"
        assert event.error_code is None
    finally:
        db.rollback()
        db.close()


def test_unbalanced_posting_returns_mapped_error_and_failed_audit():
    db = SessionLocal()
    try:
        company_id = 702
        debit = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        entry = _insert_entry(db=db, company_id=company_id)
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit.account_id,
            debit_amount_cents=1200,
        )
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit.account_id,
            credit_amount_cents=1100,
        )
        db.commit()

        with pytest.raises(JournalPostingApplicationError) as exc:
            post_journal_entry_with_audit(db=db, company_id=company_id, journal_entry_id=entry.journal_entry_id)
        assert exc.value.code == ERROR_CODE_UNBALANCED

        event = _fetch_latest_audit(company_id=company_id, journal_entry_id=entry.journal_entry_id)
        assert event is not None
        assert event.result == "FAILED"
        assert event.error_code == ERROR_CODE_UNBALANCED
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize("period_status", ["CLOSED", "LOCKED"])
def test_closed_or_locked_period_returns_mapped_error_and_failed_audit(period_status: str):
    db = SessionLocal()
    try:
        company_id = 703 if period_status == "CLOSED" else 704
        debit = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        period = _insert_period(db=db, company_id=company_id, status=period_status)
        entry = _insert_entry(db=db, company_id=company_id, fiscal_period_id=period.fiscal_period_id)
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit.account_id,
            debit_amount_cents=1200,
        )
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit.account_id,
            credit_amount_cents=1200,
        )
        db.commit()

        with pytest.raises(JournalPostingApplicationError) as exc:
            post_journal_entry_with_audit(db=db, company_id=company_id, journal_entry_id=entry.journal_entry_id)
        assert exc.value.code == ERROR_CODE_PERIOD_CLOSED

        event = _fetch_latest_audit(company_id=company_id, journal_entry_id=entry.journal_entry_id)
        assert event is not None
        assert event.result == "FAILED"
        assert event.error_code == ERROR_CODE_PERIOD_CLOSED
    finally:
        db.rollback()
        db.close()


def test_repeat_post_is_idempotent_and_does_not_add_duplicate_success_audit():
    db = SessionLocal()
    try:
        company_id = 705
        debit = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        entry = _insert_entry(db=db, company_id=company_id)
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit.account_id,
            debit_amount_cents=900,
        )
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit.account_id,
            credit_amount_cents=900,
        )
        db.commit()

        first = post_journal_entry_with_audit(db=db, company_id=company_id, journal_entry_id=entry.journal_entry_id)
        db.commit()

        second = post_journal_entry_with_audit(db=db, company_id=company_id, journal_entry_id=entry.journal_entry_id)
        db.commit()
        assert second["ok"] is True
        assert second["status"] == "POSTED"
        assert second["audit_event_id"] == first["audit_event_id"]

        success_count = (
            db.query(JournalPostingAuditEvent)
            .filter(JournalPostingAuditEvent.company_id == int(company_id))
            .filter(JournalPostingAuditEvent.journal_entry_id == str(entry.journal_entry_id))
            .filter(JournalPostingAuditEvent.event_type == "POST_ATTEMPT")
            .filter(JournalPostingAuditEvent.result == "SUCCESS")
            .count()
        )
        assert success_count == 1
    finally:
        db.rollback()
        db.close()


def test_db_trigger_violation_maps_to_period_closed_error(monkeypatch):
    db = SessionLocal()
    try:
        company_id = 706
        debit = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        period = _insert_period(db=db, company_id=company_id, status="LOCKED")
        entry = _insert_entry(db=db, company_id=company_id, fiscal_period_id=period.fiscal_period_id)
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit.account_id,
            debit_amount_cents=500,
        )
        create_journal_entry_line_draft(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit.account_id,
            credit_amount_cents=500,
        )
        db.commit()

        import app.services.journal_posting_service as svc

        monkeypatch.setattr(svc, "_load_period_for_entry", lambda **_kwargs: None)

        with pytest.raises(JournalPostingApplicationError) as exc:
            post_journal_entry_with_audit(db=db, company_id=company_id, journal_entry_id=entry.journal_entry_id)
        assert exc.value.code == ERROR_CODE_PERIOD_CLOSED
    finally:
        db.rollback()
        db.close()
