from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.deduction_config import DeductionConfig
from app.models.deduction_type import DeductionType
from app.models.employee import Employee
from app.models.pay_period import PayPeriod
from app.models.payroll_deduction import PayrollDeduction
from app.models.payroll_run import PayrollRun
from app.models.paystub import Paystub
from app.services.employee_payroll_config_service import resolve_effective_payroll_enrollments
from app.services.statutory_deduction_calculator import get_default_statutory_calculator

STATUTORY_DEDUCTION_CODES = {"CPP", "EI"}


def _calc_amount_cents(gross_pay_cents: int, rate: Decimal) -> int:
    gross = Decimal(int(gross_pay_cents))
    amount = (gross * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return max(0, int(amount))


def _active_configs_for_employee(
    *,
    company_id: int,
    employee_id: int,
    as_of_date: date,
    db: Session,
) -> list[tuple[DeductionConfig, DeductionType]]:
    rows = (
        db.query(DeductionConfig, DeductionType)
        .join(DeductionType, DeductionType.deduction_type_id == DeductionConfig.deduction_type_id)
        .filter(DeductionConfig.company_id == int(company_id))
        .filter(DeductionConfig.is_active.is_(True))
        .filter(or_(DeductionConfig.employee_id.is_(None), DeductionConfig.employee_id == int(employee_id)))
        .filter(DeductionConfig.effective_from <= as_of_date)
        .filter(or_(DeductionConfig.effective_to.is_(None), DeductionConfig.effective_to >= as_of_date))
        .filter(DeductionType.is_active.is_(True))
        .filter(or_(DeductionType.company_id.is_(None), DeductionType.company_id == int(company_id)))
        .all()
    )

    # Employee-specific config overrides default config for the same deduction code.
    rows_sorted = sorted(
        rows,
        key=lambda t: (
            str(t[1].code),
            0 if t[0].employee_id is not None else 1,
            0 if t[1].company_id is not None and int(t[1].company_id) == int(company_id) else 1,
            -(t[0].effective_from.toordinal() if t[0].effective_from is not None else 0),
        ),
    )

    picked: dict[str, tuple[DeductionConfig, DeductionType]] = {}
    for cfg, dtype in rows_sorted:
        code = str(dtype.code)
        if code not in picked:
            picked[code] = (cfg, dtype)

    return list(picked.values())


def compute_deduction_amounts(
    *,
    company_id: int,
    employee_id: int,
    gross_pay_cents: int,
    db: Session,
    as_of_date: date | None = None,
) -> list[dict[str, int | str]]:
    if as_of_date is None:
        as_of_date = date.today()

    employee = (
        db.query(Employee)
        .filter(Employee.company_id == int(company_id))
        .filter(Employee.id == int(employee_id))
        .one_or_none()
    )
    if employee is None:
        return []
    if not bool(employee.requires_payroll):
        return []

    statutory_rows = get_default_statutory_calculator().calculate(
        gross_pay_cents=int(gross_pay_cents),
        as_of_date=as_of_date,
    )

    configs = _active_configs_for_employee(
        company_id=int(company_id),
        employee_id=int(employee_id),
        as_of_date=as_of_date,
        db=db,
    )

    rows: list[dict[str, int | str]] = []
    for config, deduction_type in configs:
        if str(deduction_type.code) in STATUTORY_DEDUCTION_CODES:
            continue

        amount_cents: int

        if config.rate_percent is not None:
            rate = Decimal(config.rate_percent) / Decimal("100")
            amount_cents = _calc_amount_cents(int(gross_pay_cents), rate)
        else:
            amount_cents = int(config.amount_cents or 0)

        if config.annual_cap_cents is not None:
            amount_cents = min(int(amount_cents), int(config.annual_cap_cents))

        rows.append(
            {
                "deduction_type_code": str(deduction_type.code),
                "amount_cents": int(max(0, amount_cents)),
                "calculation_source": "CONFIG",
                "paystub_applies": True,
            }
        )

    payroll_enrollments = resolve_effective_payroll_enrollments(
        db=db,
        company_id=int(company_id),
        employee_id=int(employee_id),
        as_of_date=as_of_date,
    )
    for enrollment in payroll_enrollments:
        if int(enrollment.employee_amount_cents or 0) > 0:
            rows.append(
                {
                    "deduction_type_code": f"{enrollment.code}_EMPLOYEE",
                    "amount_cents": int(enrollment.employee_amount_cents),
                    "calculation_source": "CONFIG",
                    "paystub_applies": True,
                }
            )
        if int(enrollment.employer_amount_cents or 0) > 0:
            rows.append(
                {
                    "deduction_type_code": f"{enrollment.code}_EMPLOYER",
                    "amount_cents": int(enrollment.employer_amount_cents),
                    "calculation_source": "CONFIG",
                    "paystub_applies": False,
                }
            )

    combined_rows = [*statutory_rows, *rows]
    filtered_rows: list[dict[str, int | str]] = []
    for row in combined_rows:
        code = str(row.get("deduction_type_code", "")).upper()
        if code == "WCB" and not bool(employee.include_wcb_cost):
            continue
        if code == "EI" and not bool(employee.include_ei_cost):
            continue
        if (code == "CPP" or code.startswith("TAX")) and not bool(employee.include_tax_cost):
            continue
        filtered_rows.append(row)

    return filtered_rows


def _deduction_type_key(row: dict[str, int | str]) -> str:
    return str(row.get("deduction_type_code", ""))


def _deduction_amount_value(row: dict[str, int | str]) -> int:
    try:
        return int(row.get("amount_cents", 0))
    except (TypeError, ValueError):
        return 0


def _deduction_source_value(row: dict[str, int | str]) -> str:
    source = str(row.get("calculation_source", "CONFIG")).upper()
    if source not in {"STATUTORY", "CONFIG"}:
        return "CONFIG"
    return source


def _deduction_paystub_applies(row: dict[str, int | str]) -> bool:
    return bool(row.get("paystub_applies", True))


def generate_deductions_for_run(*, company_id: int, payroll_run_id: str, db: Session) -> dict:
    payroll_run = (
        db.query(PayrollRun)
        .filter(PayrollRun.company_id == int(company_id))
        .filter(PayrollRun.payroll_run_id == str(payroll_run_id))
        .one_or_none()
    )
    if payroll_run is None:
        raise ValueError("PayrollRun not found")
    if payroll_run.status == "POSTED":
        raise ValueError("Payroll run is POSTED and immutable; deductions cannot be regenerated")
    if payroll_run.status != "FINALIZED":
        raise ValueError("Payroll run must be FINALIZED before generating deductions")

    pay_period = (
        db.query(PayPeriod)
        .filter(PayPeriod.company_id == int(company_id))
        .filter(PayPeriod.pay_period_id == str(payroll_run.pay_period_id))
        .one_or_none()
    )
    if pay_period is None:
        raise ValueError("PayPeriod not found")
    payroll_as_of_date = pay_period.end_date

    paystubs = (
        db.query(Paystub)
        .filter(Paystub.company_id == int(company_id))
        .filter(Paystub.payroll_run_id == str(payroll_run_id))
        .order_by(Paystub.employee_id.asc(), Paystub.paystub_id.asc())
        .all()
    )

    existing_rows = (
        db.query(
            PayrollDeduction.employee_id,
            PayrollDeduction.deduction_type,
        )
        .filter(PayrollDeduction.company_id == int(company_id))
        .filter(PayrollDeduction.payroll_run_id == str(payroll_run_id))
        .all()
    )
    existing = {(int(r.employee_id), str(r.deduction_type)) for r in existing_rows}

    generated = 0
    skipped = 0

    for paystub in paystubs:
        deductions = compute_deduction_amounts(
            company_id=int(company_id),
            employee_id=int(paystub.employee_id),
            gross_pay_cents=int(paystub.gross_pay_cents or 0),
            db=db,
            as_of_date=payroll_as_of_date,
        )
        for row in deductions:
            deduction_type = _deduction_type_key(row)
            amount_cents = _deduction_amount_value(row)
            key = (int(paystub.employee_id), deduction_type)
            if key in existing:
                skipped += 1
                continue

            db.add(
                PayrollDeduction(
                    company_id=int(company_id),
                    payroll_run_id=str(payroll_run_id),
                    employee_id=int(paystub.employee_id),
                    paystub_id=str(paystub.paystub_id) if _deduction_paystub_applies(row) else None,
                    deduction_type=deduction_type,
                    amount_cents=int(amount_cents),
                    calculation_source=_deduction_source_value(row),
                )
            )
            existing.add(key)
            generated += 1

    db.flush()

    deduction_totals = {
        str(r.paystub_id): int(r.total_amount_cents or 0)
        for r in (
            db.query(
                PayrollDeduction.paystub_id.label("paystub_id"),
                func.coalesce(func.sum(PayrollDeduction.amount_cents), 0).label("total_amount_cents"),
            )
            .filter(PayrollDeduction.company_id == int(company_id))
            .filter(PayrollDeduction.payroll_run_id == str(payroll_run_id))
            .filter(PayrollDeduction.paystub_id.is_not(None))
            .group_by(PayrollDeduction.paystub_id)
            .all()
        )
    }

    for paystub in paystubs:
        total_deductions_cents = int(deduction_totals.get(str(paystub.paystub_id), 0))
        paystub.total_deductions_cents = total_deductions_cents
        paystub.net_pay_cents = int(paystub.gross_pay_cents) - total_deductions_cents

    return {
        "payroll_run_id": str(payroll_run_id),
        "generated": generated,
        "skipped": skipped,
    }
