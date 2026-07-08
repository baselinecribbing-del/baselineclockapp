from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.chart_of_account import ChartOfAccount
from app.models.fiscal_period import FiscalPeriod
from app.models.journal_entry import JournalEntry
from app.models.journal_entry_line import JournalEntryLine
from app.models.journal_posting_audit_event import JournalPostingAuditEvent


class JournalPostingError(ValueError):
    pass


class JournalPostingApplicationError(ValueError):
    def __init__(self, *, code: str, message: str):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)


ERROR_CODE_NOT_FOUND = "JOURNAL_NOT_FOUND"
ERROR_CODE_INVALID_STATE = "JOURNAL_INVALID_STATE"
ERROR_CODE_NO_LINES = "JOURNAL_NO_LINES"
ERROR_CODE_UNBALANCED = "JOURNAL_UNBALANCED"
ERROR_CODE_PERIOD_CLOSED = "JOURNAL_PERIOD_CLOSED_OR_LOCKED"
ERROR_CODE_DB_GUARD = "JOURNAL_DB_GUARD_VIOLATION"
ERROR_CODE_PERSISTENCE = "JOURNAL_PERSISTENCE_FAILURE"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_entry(*, db: Session, company_id: int, journal_entry_id: str) -> JournalEntry:
    entry = (
        db.query(JournalEntry)
        .filter(JournalEntry.company_id == int(company_id))
        .filter(JournalEntry.journal_entry_id == str(journal_entry_id))
        .one_or_none()
    )
    if entry is None:
        raise JournalPostingError("JournalEntry not found")
    return entry


def _ensure_entry_is_draft(entry: JournalEntry) -> None:
    if str(entry.status) != "DRAFT":
        raise JournalPostingError("Only DRAFT journal entries can be modified or posted")


def _load_period_for_entry(*, db: Session, entry: JournalEntry) -> FiscalPeriod | None:
    if entry.fiscal_period_id is None:
        return None

    period = (
        db.query(FiscalPeriod)
        .filter(FiscalPeriod.company_id == int(entry.company_id))
        .filter(FiscalPeriod.fiscal_period_id == str(entry.fiscal_period_id))
        .one_or_none()
    )
    if period is None:
        raise JournalPostingError("Fiscal period not found for journal entry")
    if str(period.status) in {"CLOSED", "LOCKED"}:
        raise JournalPostingError("Cannot post journal entry into a closed or locked fiscal period")
    return period


def _load_entry_lines(*, db: Session, company_id: int, journal_entry_id: str) -> list[JournalEntryLine]:
    return (
        db.query(JournalEntryLine)
        .filter(JournalEntryLine.company_id == int(company_id))
        .filter(JournalEntryLine.journal_entry_id == str(journal_entry_id))
        .order_by(JournalEntryLine.line_number.asc(), JournalEntryLine.journal_entry_line_id.asc())
        .all()
    )


def _ensure_account_allows_posting(*, db: Session, company_id: int, account_id: str) -> ChartOfAccount:
    account = (
        db.query(ChartOfAccount)
        .filter(ChartOfAccount.company_id == int(company_id))
        .filter(ChartOfAccount.account_id == str(account_id))
        .one_or_none()
    )
    if account is None:
        raise JournalPostingError("Chart of account was not found")
    if not bool(account.is_active) or not bool(account.allow_posting):
        raise JournalPostingError("Journal entry lines must reference an active posting account")
    return account


def _validate_line_shape(line: JournalEntryLine) -> None:
    debit = int(line.debit_amount_cents or 0)
    credit = int(line.credit_amount_cents or 0)
    if debit < 0 or credit < 0:
        raise JournalPostingError("Journal entry lines must use nonnegative debit/credit amounts")
    if (debit > 0 and credit > 0) or (debit == 0 and credit == 0):
        raise JournalPostingError("Each journal entry line must have exactly one nonzero side (debit or credit)")


def post_journal_entry(
    *,
    db: Session,
    company_id: int,
    journal_entry_id: str,
    posted_by_user_account_id: str | None = None,
) -> dict[str, Any]:
    entry = _load_entry(db=db, company_id=int(company_id), journal_entry_id=str(journal_entry_id))
    _ensure_entry_is_draft(entry)
    _load_period_for_entry(db=db, entry=entry)

    lines = _load_entry_lines(db=db, company_id=int(company_id), journal_entry_id=str(journal_entry_id))
    if not lines:
        raise JournalPostingError("Cannot post journal entry without at least one line")

    debit_total = 0
    credit_total = 0
    for line in lines:
        _ensure_account_allows_posting(db=db, company_id=int(company_id), account_id=str(line.account_id))
        _validate_line_shape(line)
        debit_total += int(line.debit_amount_cents or 0)
        credit_total += int(line.credit_amount_cents or 0)

    if debit_total != credit_total:
        raise JournalPostingError(
            "Journal entry is unbalanced: "
            f"debit_total_cents={debit_total}, credit_total_cents={credit_total}"
        )

    entry.status = "POSTED"
    entry.posted_at = _utcnow()
    entry.posted_by_user_account_id = None if posted_by_user_account_id is None else str(posted_by_user_account_id)
    db.flush()

    return {
        "ok": True,
        "journal_entry_id": str(entry.journal_entry_id),
        "status": str(entry.status),
        "line_count": int(len(lines)),
        "debit_total_cents": int(debit_total),
        "credit_total_cents": int(credit_total),
        "posted_at": None if entry.posted_at is None else entry.posted_at.isoformat(),
    }


def update_journal_entry_draft(
    *,
    db: Session,
    company_id: int,
    journal_entry_id: str,
    entry_date: Any | None = None,
    fiscal_period_id: str | None = None,
    source_type: str | None = None,
    source_reference_id: str | None = None,
    reference_number: str | None = None,
    memo: str | None = None,
) -> JournalEntry:
    entry = _load_entry(db=db, company_id=int(company_id), journal_entry_id=str(journal_entry_id))
    _ensure_entry_is_draft(entry)

    if entry_date is not None:
        entry.entry_date = entry_date
    if fiscal_period_id is not None:
        entry.fiscal_period_id = str(fiscal_period_id)
    if source_type is not None:
        entry.source_type = str(source_type)
    if source_reference_id is not None:
        entry.source_reference_id = str(source_reference_id)
    if reference_number is not None:
        entry.reference_number = str(reference_number)
    if memo is not None:
        entry.memo = str(memo)

    db.flush()
    return entry


def create_journal_entry_line_draft(
    *,
    db: Session,
    company_id: int,
    journal_entry_id: str,
    line_number: int,
    account_id: str,
    debit_amount_cents: int = 0,
    credit_amount_cents: int = 0,
    memo: str | None = None,
    job_id: int | None = None,
    cost_code_id: int | None = None,
) -> JournalEntryLine:
    entry = _load_entry(db=db, company_id=int(company_id), journal_entry_id=str(journal_entry_id))
    _ensure_entry_is_draft(entry)
    _ensure_account_allows_posting(db=db, company_id=int(company_id), account_id=str(account_id))

    line = JournalEntryLine(
        company_id=int(company_id),
        journal_entry_id=str(journal_entry_id),
        line_number=int(line_number),
        account_id=str(account_id),
        debit_amount_cents=int(debit_amount_cents),
        credit_amount_cents=int(credit_amount_cents),
        memo=None if memo is None else str(memo),
        job_id=None if job_id is None else int(job_id),
        cost_code_id=None if cost_code_id is None else int(cost_code_id),
    )
    _validate_line_shape(line)
    db.add(line)
    db.flush()
    return line


def update_journal_entry_line_draft(
    *,
    db: Session,
    company_id: int,
    journal_entry_line_id: str,
    debit_amount_cents: int | None = None,
    credit_amount_cents: int | None = None,
    memo: str | None = None,
) -> JournalEntryLine:
    line = (
        db.query(JournalEntryLine)
        .filter(JournalEntryLine.company_id == int(company_id))
        .filter(JournalEntryLine.journal_entry_line_id == str(journal_entry_line_id))
        .one_or_none()
    )
    if line is None:
        raise JournalPostingError("JournalEntryLine not found")

    entry = _load_entry(
        db=db,
        company_id=int(company_id),
        journal_entry_id=str(line.journal_entry_id),
    )
    _ensure_entry_is_draft(entry)

    if debit_amount_cents is not None:
        line.debit_amount_cents = int(debit_amount_cents)
    if credit_amount_cents is not None:
        line.credit_amount_cents = int(credit_amount_cents)
    if memo is not None:
        line.memo = str(memo)

    _validate_line_shape(line)
    db.flush()
    return line


def delete_journal_entry_line_draft(
    *,
    db: Session,
    company_id: int,
    journal_entry_line_id: str,
) -> None:
    line = (
        db.query(JournalEntryLine)
        .filter(JournalEntryLine.company_id == int(company_id))
        .filter(JournalEntryLine.journal_entry_line_id == str(journal_entry_line_id))
        .one_or_none()
    )
    if line is None:
        raise JournalPostingError("JournalEntryLine not found")

    entry = _load_entry(
        db=db,
        company_id=int(company_id),
        journal_entry_id=str(line.journal_entry_id),
    )
    _ensure_entry_is_draft(entry)

    db.delete(line)
    db.flush()


def journal_entry_totals(
    *,
    db: Session,
    company_id: int,
    journal_entry_id: str,
) -> dict[str, int]:
    row = (
        db.query(
            func.coalesce(func.sum(JournalEntryLine.debit_amount_cents), 0).label("debit_total_cents"),
            func.coalesce(func.sum(JournalEntryLine.credit_amount_cents), 0).label("credit_total_cents"),
            func.count(JournalEntryLine.journal_entry_line_id).label("line_count"),
        )
        .filter(JournalEntryLine.company_id == int(company_id))
        .filter(JournalEntryLine.journal_entry_id == str(journal_entry_id))
        .one()
    )
    return {
        "debit_total_cents": int(row.debit_total_cents or 0),
        "credit_total_cents": int(row.credit_total_cents or 0),
        "line_count": int(row.line_count or 0),
    }


def _map_posting_exception(exc: Exception) -> JournalPostingApplicationError:
    if isinstance(exc, JournalPostingApplicationError):
        return exc

    if isinstance(exc, JournalPostingError):
        msg = str(exc)
        msg_lower = msg.lower()
        if "not found" in msg_lower:
            return JournalPostingApplicationError(code=ERROR_CODE_NOT_FOUND, message="Journal entry was not found")
        if "only draft" in msg_lower:
            return JournalPostingApplicationError(code=ERROR_CODE_INVALID_STATE, message="Journal entry is not in DRAFT status")
        if "without at least one line" in msg_lower:
            return JournalPostingApplicationError(code=ERROR_CODE_NO_LINES, message="Journal entry must have at least one line")
        if "unbalanced" in msg_lower:
            return JournalPostingApplicationError(code=ERROR_CODE_UNBALANCED, message="Journal entry debits and credits must balance")
        if "closed or locked fiscal period" in msg_lower:
            return JournalPostingApplicationError(
                code=ERROR_CODE_PERIOD_CLOSED,
                message="Posting is blocked because the fiscal period is CLOSED or LOCKED",
            )
        if "active posting account" in msg_lower:
            return JournalPostingApplicationError(
                code=ERROR_CODE_DB_GUARD,
                message="Posting was blocked by a database integrity guard",
            )
        return JournalPostingApplicationError(code=ERROR_CODE_PERSISTENCE, message="Journal posting failed")

    if isinstance(exc, DBAPIError):
        raw = str(getattr(exc, "orig", exc)).lower()
        if "without at least one line" in raw:
            return JournalPostingApplicationError(code=ERROR_CODE_NO_LINES, message="Journal entry must have at least one line")
        if "unless debits equal credits" in raw:
            return JournalPostingApplicationError(code=ERROR_CODE_UNBALANCED, message="Journal entry debits and credits must balance")
        if "closed or locked fiscal period" in raw:
            return JournalPostingApplicationError(
                code=ERROR_CODE_PERIOD_CLOSED,
                message="Posting is blocked because the fiscal period is CLOSED or LOCKED",
            )
        if "active posting account" in raw or "allow_posting=true" in raw:
            return JournalPostingApplicationError(
                code=ERROR_CODE_DB_GUARD,
                message="Posting was blocked by a database integrity guard",
            )
        if "cannot transition from posted" in raw or "immutable" in raw or "posted_at is immutable" in raw:
            return JournalPostingApplicationError(
                code=ERROR_CODE_DB_GUARD,
                message="Posting was blocked by a database integrity guard",
            )
        return JournalPostingApplicationError(
            code=ERROR_CODE_PERSISTENCE,
            message="Unexpected persistence failure during journal posting",
        )

    return JournalPostingApplicationError(
        code=ERROR_CODE_PERSISTENCE,
        message="Unexpected persistence failure during journal posting",
    )


def _persist_audit_event(
    *,
    db: Session,
    company_id: int,
    journal_entry_id: str,
    result: str,
    actor_user_account_id: str | None,
    source_type: str | None,
    source_reference_id: str | None,
    error_code: str | None,
    error_message: str | None,
) -> JournalPostingAuditEvent:
    row = JournalPostingAuditEvent(
        company_id=int(company_id),
        journal_entry_id=str(journal_entry_id),
        event_type="POST_ATTEMPT",
        result=str(result),
        actor_user_account_id=None if actor_user_account_id is None else str(actor_user_account_id),
        source_type=None if source_type is None else str(source_type),
        source_reference_id=None if source_reference_id is None else str(source_reference_id),
        error_code=None if error_code is None else str(error_code),
        error_message=None if error_message is None else str(error_message),
    )
    db.add(row)
    db.flush()
    return row


def _load_entry_context(
    *,
    db: Session,
    company_id: int,
    journal_entry_id: str,
) -> tuple[str | None, str | None]:
    entry = (
        db.query(JournalEntry)
        .filter(JournalEntry.company_id == int(company_id))
        .filter(JournalEntry.journal_entry_id == str(journal_entry_id))
        .one_or_none()
    )
    if entry is None:
        return (None, None)
    return (
        None if entry.source_type is None else str(entry.source_type),
        None if entry.source_reference_id is None else str(entry.source_reference_id),
    )


def _persist_failure_audit_event_out_of_band(
    *,
    company_id: int,
    journal_entry_id: str,
    actor_user_account_id: str | None,
    error_code: str,
    error_message: str,
) -> None:
    # Failed post attempts are recorded with an independent session so that
    # audit rows remain durable even when the caller's transaction is rolled back.
    audit_db = SessionLocal()
    try:
        source_type, source_reference_id = _load_entry_context(
            db=audit_db,
            company_id=int(company_id),
            journal_entry_id=str(journal_entry_id),
        )
        _persist_audit_event(
            db=audit_db,
            company_id=int(company_id),
            journal_entry_id=str(journal_entry_id),
            result="FAILED",
            actor_user_account_id=actor_user_account_id,
            source_type=source_type,
            source_reference_id=source_reference_id,
            error_code=str(error_code),
            error_message=str(error_message),
        )
        audit_db.commit()
    except Exception:
        audit_db.rollback()
    finally:
        audit_db.close()


def _latest_success_audit_event_for_entry(
    *,
    db: Session,
    company_id: int,
    journal_entry_id: str,
) -> JournalPostingAuditEvent | None:
    return (
        db.query(JournalPostingAuditEvent)
        .filter(JournalPostingAuditEvent.company_id == int(company_id))
        .filter(JournalPostingAuditEvent.journal_entry_id == str(journal_entry_id))
        .filter(JournalPostingAuditEvent.event_type == "POST_ATTEMPT")
        .filter(JournalPostingAuditEvent.result == "SUCCESS")
        .order_by(JournalPostingAuditEvent.created_at.desc(), JournalPostingAuditEvent.journal_posting_audit_event_id.desc())
        .first()
    )


def post_journal_entry_with_audit(
    *,
    db: Session,
    company_id: int,
    journal_entry_id: str,
    posted_by_user_account_id: str | None = None,
) -> dict[str, Any]:
    try:
        existing_entry = _load_entry(db=db, company_id=int(company_id), journal_entry_id=str(journal_entry_id))
        if str(existing_entry.status) == "POSTED":
            totals = journal_entry_totals(
                db=db,
                company_id=int(company_id),
                journal_entry_id=str(journal_entry_id),
            )
            latest_success_event = _latest_success_audit_event_for_entry(
                db=db,
                company_id=int(company_id),
                journal_entry_id=str(journal_entry_id),
            )
            if latest_success_event is None:
                source_type, source_reference_id = _load_entry_context(
                    db=db,
                    company_id=int(company_id),
                    journal_entry_id=str(journal_entry_id),
                )
                latest_success_event = _persist_audit_event(
                    db=db,
                    company_id=int(company_id),
                    journal_entry_id=str(journal_entry_id),
                    result="SUCCESS",
                    actor_user_account_id=posted_by_user_account_id,
                    source_type=source_type,
                    source_reference_id=source_reference_id,
                    error_code=None,
                    error_message=None,
                )
            return {
                "ok": True,
                "journal_entry_id": str(existing_entry.journal_entry_id),
                "status": str(existing_entry.status),
                "line_count": int(totals["line_count"]),
                "debit_total_cents": int(totals["debit_total_cents"]),
                "credit_total_cents": int(totals["credit_total_cents"]),
                "posted_at": None if existing_entry.posted_at is None else existing_entry.posted_at.isoformat(),
                "audit_event_id": str(latest_success_event.journal_posting_audit_event_id),
            }

        result = post_journal_entry(
            db=db,
            company_id=int(company_id),
            journal_entry_id=str(journal_entry_id),
            posted_by_user_account_id=posted_by_user_account_id,
        )
        source_type, source_reference_id = _load_entry_context(
            db=db,
            company_id=int(company_id),
            journal_entry_id=str(journal_entry_id),
        )
        audit_row = _persist_audit_event(
            db=db,
            company_id=int(company_id),
            journal_entry_id=str(journal_entry_id),
            result="SUCCESS",
            actor_user_account_id=posted_by_user_account_id,
            source_type=source_type,
            source_reference_id=source_reference_id,
            error_code=None,
            error_message=None,
        )
        result["audit_event_id"] = str(audit_row.journal_posting_audit_event_id)
        return result
    except Exception as exc:
        mapped = _map_posting_exception(exc)
        db.rollback()
        _persist_failure_audit_event_out_of_band(
            company_id=int(company_id),
            journal_entry_id=str(journal_entry_id),
            actor_user_account_id=posted_by_user_account_id,
            error_code=str(mapped.code),
            error_message=str(mapped.message),
        )
        raise mapped
