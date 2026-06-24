from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.pay_period import PayPeriod
from app.models.payroll_remittance_obligation import PayrollRemittanceObligation
from app.models.payroll_run_audit_event import PayrollRunAuditEvent
from app.models.payroll_run import PayrollRun
from app.services.payroll_audit_service import (
    PAYROLL_REMITTANCE_MARKED_REMITTED_MANUAL_EVENT,
    PAYROLL_REMITTANCE_OBLIGATION_PREPARED_EVENT,
    PAYROLL_REMITTANCE_PAYMENT_RECORDED_EVENT,
    PAYROLL_REMITTANCE_REFERENCE_RECORDED_EVENT,
    record_payroll_audit_event,
)
from app.services.source_deduction_summary_service import get_source_deduction_summary


@dataclass(frozen=True)
class PayrollRemittanceObligationRecord:
    id: int
    company_id: int
    payroll_run_id: str
    remittance_type: str
    tax_year: int
    tax_month: int
    due_date: date | None
    remittance_period_label: str | None
    employee_deductions_cents: int
    employer_contributions_cents: int
    total_remittance_cents: int
    currency: str
    status: str
    is_overdue: bool
    payment_status: str
    last_payment_at: datetime | None
    total_paid_cents: int
    remaining_balance_cents: int
    reference_note: str | None
    remitted_reference: str | None
    prepared_at: datetime
    marked_remitted_at: datetime | None
    marked_remitted_by_user_id: str | None


@dataclass(frozen=True)
class PayrollRemittancePaymentHistoryRecord:
    audit_event_id: int
    remittance_obligation_id: int
    company_id: int
    payroll_run_id: str
    payment_date: date
    amount_cents: int
    currency: str
    payment_method: str
    reference_note: str | None
    remitted_reference: str | None
    recorded_at: datetime
    actor_user_id: str | None


@dataclass(frozen=True)
class PayrollRemittancePaymentState:
    payment_status: str
    last_payment_at: datetime | None
    total_paid_cents: int
    remaining_balance_cents: int


def _normalize_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _get_payroll_run(*, db: Session, company_id: int, payroll_run_id: str) -> PayrollRun | None:
    return (
        db.query(PayrollRun)
        .filter(PayrollRun.company_id == int(company_id))
        .filter(PayrollRun.payroll_run_id == str(payroll_run_id))
        .one_or_none()
    )


def _get_pay_period(*, db: Session, company_id: int, pay_period_id: str) -> PayPeriod | None:
    return (
        db.query(PayPeriod)
        .filter(PayPeriod.company_id == int(company_id))
        .filter(PayPeriod.pay_period_id == str(pay_period_id))
        .one_or_none()
    )


def _internal_remittance_due_date(*, pay_period: PayPeriod) -> date:
    """
    Internal operations reminder date only.
    This intentionally avoids claiming CRA-complete due-date logic.
    """
    if int(pay_period.end_date.month) == 12:
        return date(int(pay_period.end_date.year) + 1, 1, 15)
    return date(int(pay_period.end_date.year), int(pay_period.end_date.month) + 1, 15)


def _remittance_period_label(*, pay_period: PayPeriod) -> str:
    return f"{int(pay_period.end_date.year):04d}-{int(pay_period.end_date.month):02d}"


def _is_overdue(row: PayrollRemittanceObligation, *, today: date | None = None) -> bool:
    comparison_day = date.today() if today is None else today
    return bool(row.due_date is not None and str(row.status) == "PENDING" and row.due_date < comparison_day)


def get_payroll_remittance_obligation(
    *,
    db: Session,
    company_id: int,
    remittance_obligation_id: int,
) -> PayrollRemittanceObligation | None:
    return (
        db.query(PayrollRemittanceObligation)
        .filter(PayrollRemittanceObligation.company_id == int(company_id))
        .filter(PayrollRemittanceObligation.id == int(remittance_obligation_id))
        .one_or_none()
    )


def list_payroll_remittance_payment_history(
    *,
    db: Session,
    company_id: int,
    remittance_obligation_id: int,
) -> list[PayrollRemittancePaymentHistoryRecord]:
    row = get_payroll_remittance_obligation(
        db=db,
        company_id=int(company_id),
        remittance_obligation_id=int(remittance_obligation_id),
    )
    if row is None:
        raise ValueError("Payroll remittance obligation not found")

    audit_rows = (
        db.query(PayrollRunAuditEvent)
        .filter(PayrollRunAuditEvent.company_id == int(company_id))
        .filter(PayrollRunAuditEvent.payroll_run_id == str(row.payroll_run_id))
        .filter(PayrollRunAuditEvent.event_type == PAYROLL_REMITTANCE_PAYMENT_RECORDED_EVENT)
        .order_by(PayrollRunAuditEvent.event_timestamp.asc(), PayrollRunAuditEvent.id.asc())
        .all()
    )

    history: list[PayrollRemittancePaymentHistoryRecord] = []
    for audit_row in audit_rows:
        payload = dict(audit_row.payload_json or {})
        if int(payload.get("remittance_obligation_id") or 0) != int(row.id):
            continue
        payment_date_raw = payload.get("payment_date")
        payment_method = _normalize_text(payload.get("payment_method"))
        currency = _normalize_text(payload.get("currency"))
        if payment_date_raw is None or payment_method is None or currency is None:
            continue
        history.append(
            PayrollRemittancePaymentHistoryRecord(
                audit_event_id=int(audit_row.id),
                remittance_obligation_id=int(row.id),
                company_id=int(company_id),
                payroll_run_id=str(row.payroll_run_id),
                payment_date=date.fromisoformat(str(payment_date_raw)),
                amount_cents=int(payload.get("amount_cents") or 0),
                currency=str(currency),
                payment_method=str(payment_method),
                reference_note=_normalize_text(payload.get("reference_note")),
                remitted_reference=_normalize_text(payload.get("remitted_reference")),
                recorded_at=(
                    audit_row.event_timestamp.replace(tzinfo=timezone.utc)
                    if audit_row.event_timestamp.tzinfo is None
                    else audit_row.event_timestamp.astimezone(timezone.utc)
                ),
                actor_user_id=_normalize_text(payload.get("actor_user_id")) or _normalize_text(audit_row.actor_user_id),
            )
        )

    return history


def _aggregate_payment_state(
    *,
    total_remittance_cents: int,
    payment_history: list[PayrollRemittancePaymentHistoryRecord],
) -> PayrollRemittancePaymentState:
    total_paid_cents = sum(int(row.amount_cents or 0) for row in payment_history)
    last_payment_at = max((row.recorded_at for row in payment_history), default=None)
    remaining_balance_cents = max(int(total_remittance_cents) - int(total_paid_cents), 0)
    if total_paid_cents <= 0:
        payment_status = "UNPAID"
    elif total_paid_cents < int(total_remittance_cents):
        payment_status = "PARTIALLY_PAID"
    elif total_paid_cents == int(total_remittance_cents):
        payment_status = "PAID_IN_FULL"
    else:
        payment_status = "OVERPAID"
    return PayrollRemittancePaymentState(
        payment_status=payment_status,
        last_payment_at=last_payment_at,
        total_paid_cents=int(total_paid_cents),
        remaining_balance_cents=int(remaining_balance_cents),
    )


def get_payroll_remittance_payment_state(
    *,
    db: Session,
    company_id: int,
    remittance_obligation_id: int,
) -> PayrollRemittancePaymentState:
    row = get_payroll_remittance_obligation(
        db=db,
        company_id=int(company_id),
        remittance_obligation_id=int(remittance_obligation_id),
    )
    if row is None:
        raise ValueError("Payroll remittance obligation not found")
    payment_history = list_payroll_remittance_payment_history(
        db=db,
        company_id=int(company_id),
        remittance_obligation_id=int(remittance_obligation_id),
    )
    return _aggregate_payment_state(
        total_remittance_cents=int(row.total_remittance_cents or 0),
        payment_history=payment_history,
    )


def _list_payroll_remittance_payment_state_by_obligation_id(
    *,
    db: Session,
    company_id: int,
    remittance_rows: list[PayrollRemittanceObligation],
) -> dict[int, PayrollRemittancePaymentState]:
    if not remittance_rows:
        return {}

    state_by_obligation_id: dict[int, PayrollRemittancePaymentState] = {}
    payment_history_by_obligation_id: dict[int, list[PayrollRemittancePaymentHistoryRecord]] = {
        int(row.id): [] for row in remittance_rows
    }
    payroll_run_ids = {str(row.payroll_run_id) for row in remittance_rows}

    audit_rows = (
        db.query(PayrollRunAuditEvent)
        .filter(PayrollRunAuditEvent.company_id == int(company_id))
        .filter(PayrollRunAuditEvent.event_type == PAYROLL_REMITTANCE_PAYMENT_RECORDED_EVENT)
        .filter(PayrollRunAuditEvent.payroll_run_id.in_(sorted(payroll_run_ids)))
        .order_by(PayrollRunAuditEvent.event_timestamp.asc(), PayrollRunAuditEvent.id.asc())
        .all()
    )
    remittance_by_id = {int(row.id): row for row in remittance_rows}

    for audit_row in audit_rows:
        payload = dict(audit_row.payload_json or {})
        remittance_obligation_id = int(payload.get("remittance_obligation_id") or 0)
        remittance_row = remittance_by_id.get(remittance_obligation_id)
        payment_date_raw = payload.get("payment_date")
        payment_method = _normalize_text(payload.get("payment_method"))
        currency = _normalize_text(payload.get("currency"))
        if remittance_row is None or payment_date_raw is None or payment_method is None or currency is None:
            continue
        payment_history_by_obligation_id[remittance_obligation_id].append(
            PayrollRemittancePaymentHistoryRecord(
                audit_event_id=int(audit_row.id),
                remittance_obligation_id=remittance_obligation_id,
                company_id=int(company_id),
                payroll_run_id=str(remittance_row.payroll_run_id),
                payment_date=date.fromisoformat(str(payment_date_raw)),
                amount_cents=int(payload.get("amount_cents") or 0),
                currency=str(currency),
                payment_method=str(payment_method),
                reference_note=_normalize_text(payload.get("reference_note")),
                remitted_reference=_normalize_text(payload.get("remitted_reference")),
                recorded_at=(
                    audit_row.event_timestamp.replace(tzinfo=timezone.utc)
                    if audit_row.event_timestamp.tzinfo is None
                    else audit_row.event_timestamp.astimezone(timezone.utc)
                ),
                actor_user_id=_normalize_text(payload.get("actor_user_id")) or _normalize_text(audit_row.actor_user_id),
            )
        )

    for remittance_row in remittance_rows:
        state_by_obligation_id[int(remittance_row.id)] = _aggregate_payment_state(
            total_remittance_cents=int(remittance_row.total_remittance_cents or 0),
            payment_history=payment_history_by_obligation_id[int(remittance_row.id)],
        )
    return state_by_obligation_id


def list_payroll_remittance_obligations(
    *,
    db: Session,
    company_id: int,
    status: str | None = None,
    overdue: bool | None = None,
) -> list[PayrollRemittanceObligationRecord]:
    query = db.query(PayrollRemittanceObligation).filter(PayrollRemittanceObligation.company_id == int(company_id))
    if status is not None:
        query = query.filter(PayrollRemittanceObligation.status == str(status))
    rows = (
        query.order_by(
            PayrollRemittanceObligation.tax_year.desc(),
            PayrollRemittanceObligation.tax_month.desc(),
            PayrollRemittanceObligation.id.asc(),
        )
        .all()
    )
    payment_state_by_obligation_id = _list_payroll_remittance_payment_state_by_obligation_id(
        db=db,
        company_id=int(company_id),
        remittance_rows=rows,
    )
    records = [
        PayrollRemittanceObligationRecord(
            id=int(row.id),
            company_id=int(row.company_id),
            payroll_run_id=str(row.payroll_run_id),
            remittance_type=str(row.remittance_type),
            tax_year=int(row.tax_year),
            tax_month=int(row.tax_month),
            due_date=row.due_date,
            remittance_period_label=row.remittance_period_label,
            employee_deductions_cents=int(row.employee_deductions_cents or 0),
            employer_contributions_cents=int(row.employer_contributions_cents or 0),
            total_remittance_cents=int(row.total_remittance_cents or 0),
            currency=str(row.currency),
            status=str(row.status),
            is_overdue=_is_overdue(row),
            payment_status=payment_state_by_obligation_id[int(row.id)].payment_status,
            last_payment_at=payment_state_by_obligation_id[int(row.id)].last_payment_at,
            total_paid_cents=payment_state_by_obligation_id[int(row.id)].total_paid_cents,
            remaining_balance_cents=payment_state_by_obligation_id[int(row.id)].remaining_balance_cents,
            reference_note=row.reference_note,
            remitted_reference=row.remitted_reference,
            prepared_at=row.prepared_at,
            marked_remitted_at=row.marked_remitted_at,
            marked_remitted_by_user_id=row.marked_remitted_by_user_id,
        )
        for row in rows
    ]
    if overdue is not None:
        records = [row for row in records if row.is_overdue is bool(overdue)]
    return records


def ensure_payroll_remittance_obligation_for_run(
    *,
    db: Session,
    company_id: int,
    payroll_run_id: str,
    actor_user_id: str | None,
) -> tuple[PayrollRemittanceObligation, bool]:
    payroll_run = _get_payroll_run(db=db, company_id=int(company_id), payroll_run_id=str(payroll_run_id))
    if payroll_run is None:
        raise ValueError("PayrollRun not found")
    if str(payroll_run.status) != "FINALIZED":
        raise ValueError("Payroll remittance obligations require a FINALIZED payroll run")

    existing = (
        db.query(PayrollRemittanceObligation)
        .filter(PayrollRemittanceObligation.company_id == int(company_id))
        .filter(PayrollRemittanceObligation.payroll_run_id == str(payroll_run_id))
        .one_or_none()
    )
    if existing is not None:
        return existing, False

    pay_period = _get_pay_period(db=db, company_id=int(company_id), pay_period_id=str(payroll_run.pay_period_id))
    if pay_period is None:
        raise ValueError("PayPeriod not found")

    source_summary = get_source_deduction_summary(
        db=db,
        company_id=int(company_id),
        payroll_run_id=str(payroll_run_id),
    )
    employee_deductions_cents = int(source_summary["remittance_totals"]["employee_portions_cents"] or 0)
    employer_contributions_cents = 0
    total_remittance_cents = employee_deductions_cents + employer_contributions_cents
    prepared_at = datetime.now(timezone.utc)

    row = PayrollRemittanceObligation(
        company_id=int(company_id),
        payroll_run_id=str(payroll_run_id),
        remittance_type="SOURCE_DEDUCTIONS",
        tax_year=int(pay_period.end_date.year),
        tax_month=int(pay_period.end_date.month),
        due_date=_internal_remittance_due_date(pay_period=pay_period),
        remittance_period_label=_remittance_period_label(pay_period=pay_period),
        employee_deductions_cents=employee_deductions_cents,
        employer_contributions_cents=employer_contributions_cents,
        total_remittance_cents=total_remittance_cents,
        currency="CAD",
        status="PENDING",
        prepared_at=prepared_at,
    )
    db.add(row)
    db.flush()

    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=str(payroll_run_id),
        event_type=PAYROLL_REMITTANCE_OBLIGATION_PREPARED_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "remittance_obligation_id": int(row.id),
            "payroll_run_id": str(payroll_run_id),
            "tax_year": int(row.tax_year),
            "tax_month": int(row.tax_month),
            "due_date": None if row.due_date is None else row.due_date.isoformat(),
            "remittance_period_label": row.remittance_period_label,
            "total_remittance_cents": int(row.total_remittance_cents),
            "actor_user_id": actor_user_id,
            "timestamp": prepared_at.isoformat(),
        },
    )
    return row, True


def mark_payroll_remittance_obligation_remitted_manual(
    *,
    db: Session,
    company_id: int,
    remittance_obligation_id: int,
    actor_user_id: str | None,
) -> tuple[PayrollRemittanceObligation, bool]:
    row = get_payroll_remittance_obligation(
        db=db,
        company_id=int(company_id),
        remittance_obligation_id=int(remittance_obligation_id),
    )
    if row is None:
        raise ValueError("Payroll remittance obligation not found")
    if str(row.status) == "REMITTED_MANUAL":
        return row, False

    marked_at = datetime.now(timezone.utc)
    row.status = "REMITTED_MANUAL"
    row.marked_remitted_at = marked_at
    row.marked_remitted_by_user_id = None if actor_user_id is None else str(actor_user_id)
    db.flush()

    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=str(row.payroll_run_id),
        event_type=PAYROLL_REMITTANCE_MARKED_REMITTED_MANUAL_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "remittance_obligation_id": int(row.id),
            "payroll_run_id": str(row.payroll_run_id),
            "tax_year": int(row.tax_year),
            "tax_month": int(row.tax_month),
            "due_date": None if row.due_date is None else row.due_date.isoformat(),
            "remittance_period_label": row.remittance_period_label,
            "total_remittance_cents": int(row.total_remittance_cents),
            "actor_user_id": actor_user_id,
            "timestamp": marked_at.isoformat(),
        },
    )
    return row, True


def record_payroll_remittance_reference(
    *,
    db: Session,
    company_id: int,
    remittance_obligation_id: int,
    reference_note: str | None,
    remitted_reference: str | None,
    actor_user_id: str | None,
) -> tuple[PayrollRemittanceObligation, bool]:
    row = get_payroll_remittance_obligation(
        db=db,
        company_id=int(company_id),
        remittance_obligation_id=int(remittance_obligation_id),
    )
    if row is None:
        raise ValueError("Payroll remittance obligation not found")

    normalized_note = _normalize_text(reference_note)
    normalized_reference = _normalize_text(remitted_reference)
    if normalized_note is None and normalized_reference is None:
        raise ValueError("At least one remittance reference field is required")

    changed = False
    if row.reference_note != normalized_note:
        row.reference_note = normalized_note
        changed = True
    if row.remitted_reference != normalized_reference:
        row.remitted_reference = normalized_reference
        changed = True
    if not changed:
        return row, False

    db.flush()
    recorded_at = datetime.now(timezone.utc)
    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=str(row.payroll_run_id),
        event_type=PAYROLL_REMITTANCE_REFERENCE_RECORDED_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "remittance_obligation_id": int(row.id),
            "payroll_run_id": str(row.payroll_run_id),
            "tax_year": int(row.tax_year),
            "tax_month": int(row.tax_month),
            "due_date": None if row.due_date is None else row.due_date.isoformat(),
            "remittance_period_label": row.remittance_period_label,
            "total_remittance_cents": int(row.total_remittance_cents),
            "reference_note": row.reference_note,
            "remitted_reference": row.remitted_reference,
            "actor_user_id": actor_user_id,
            "timestamp": recorded_at.isoformat(),
        },
    )
    return row, True


def record_payroll_remittance_payment(
    *,
    db: Session,
    company_id: int,
    remittance_obligation_id: int,
    payment_date: date,
    amount_cents: int,
    payment_method: str,
    reference_note: str | None,
    remitted_reference: str | None,
    actor_user_id: str | None,
) -> tuple[PayrollRemittanceObligation, bool]:
    row = get_payroll_remittance_obligation(
        db=db,
        company_id=int(company_id),
        remittance_obligation_id=int(remittance_obligation_id),
    )
    if row is None:
        raise ValueError("Payroll remittance obligation not found")

    normalized_method = _normalize_text(payment_method)
    normalized_note = _normalize_text(reference_note)
    normalized_reference = _normalize_text(remitted_reference)
    if normalized_method is None:
        raise ValueError("payment_method is required")
    if int(amount_cents) <= 0:
        raise ValueError("amount_cents must be greater than zero")
    if int(amount_cents) != int(row.total_remittance_cents):
        raise ValueError("amount_cents must match the remittance obligation total")

    existing_history = list_payroll_remittance_payment_history(
        db=db,
        company_id=int(company_id),
        remittance_obligation_id=int(remittance_obligation_id),
    )
    duplicate = next(
        (
            entry
            for entry in existing_history
            if entry.payment_date == payment_date
            and int(entry.amount_cents) == int(amount_cents)
            and entry.payment_method == normalized_method
            and entry.reference_note == normalized_note
            and entry.remitted_reference == normalized_reference
        ),
        None,
    )
    if duplicate is not None:
        if row.reference_note != normalized_note:
            row.reference_note = normalized_note
        if row.remitted_reference != normalized_reference:
            row.remitted_reference = normalized_reference
        if str(row.status) != "REMITTED_MANUAL":
            row.status = "REMITTED_MANUAL"
            row.marked_remitted_at = duplicate.recorded_at
            row.marked_remitted_by_user_id = duplicate.actor_user_id
        db.flush()
        return row, False

    if row.reference_note != normalized_note:
        row.reference_note = normalized_note
    if row.remitted_reference != normalized_reference:
        row.remitted_reference = normalized_reference
    if str(row.status) != "REMITTED_MANUAL":
        row.status = "REMITTED_MANUAL"
        row.marked_remitted_at = datetime.now(timezone.utc)
        row.marked_remitted_by_user_id = None if actor_user_id is None else str(actor_user_id)
    db.flush()

    recorded_at = datetime.now(timezone.utc)
    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=str(row.payroll_run_id),
        event_type=PAYROLL_REMITTANCE_PAYMENT_RECORDED_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "remittance_obligation_id": int(row.id),
            "payroll_run_id": str(row.payroll_run_id),
            "tax_year": int(row.tax_year),
            "tax_month": int(row.tax_month),
            "due_date": None if row.due_date is None else row.due_date.isoformat(),
            "remittance_period_label": row.remittance_period_label,
            "payment_date": payment_date.isoformat(),
            "amount_cents": int(amount_cents),
            "currency": str(row.currency),
            "payment_method": normalized_method,
            "reference_note": normalized_note,
            "remitted_reference": normalized_reference,
            "actor_user_id": actor_user_id,
            "timestamp": recorded_at.isoformat(),
        },
    )
    return row, True
