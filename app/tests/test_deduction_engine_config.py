from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.database import SessionLocal
from app.models.deduction_config import DeductionConfig
from app.models.deduction_type import DeductionType
from app.models.employee import Employee
from app.services.deduction_engine import compute_deduction_amounts


def _seed_employee(company_id: int = 1) -> int:
    db = SessionLocal()
    try:
        e = Employee(company_id=company_id, name=f"Config Engine Emp {company_id}", hourly_rate_cents=3000)
        db.add(e)
        db.commit()
        db.refresh(e)
        return int(e.id)
    finally:
        db.close()


def _seed_deduction_type(*, company_id: int | None, code: str, is_active: bool = True) -> str:
    db = SessionLocal()
    try:
        row = DeductionType(
            company_id=company_id,
            code=code,
            name=code,
            calculation_method="RATE_PERCENT",
            is_statutory=True,
            is_active=is_active,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.deduction_type_id)
    finally:
        db.close()


def _seed_config(
    *,
    company_id: int,
    deduction_type_id: str,
    employee_id: int | None = None,
    rate_percent: Decimal | None = None,
    amount_cents: int | None = None,
    effective_from: date | None = None,
    effective_to: date | None = None,
) -> None:
    db = SessionLocal()
    try:
        row = DeductionConfig(
            company_id=company_id,
            deduction_type_id=str(deduction_type_id),
            employee_id=employee_id,
            rate_percent=rate_percent,
            amount_cents=amount_cents,
            annual_cap_cents=None,
            effective_from=effective_from or date.today(),
            effective_to=effective_to,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def test_rate_percent_deduction():
    company_id = 1
    employee_id = _seed_employee(company_id=company_id)
    dtype_id = _seed_deduction_type(company_id=None, code="CPP_TEST_RATE")
    _seed_config(
        company_id=company_id,
        deduction_type_id=dtype_id,
        rate_percent=Decimal("10.0"),
    )

    db = SessionLocal()
    try:
        rows = compute_deduction_amounts(
            company_id=company_id,
            employee_id=employee_id,
            gross_pay_cents=10000,
            db=db,
        )
    finally:
        db.close()

    by_code = {str(r["deduction_type_code"]): int(r["amount_cents"]) for r in rows}
    assert by_code["CPP_TEST_RATE"] == 1000


def test_flat_deduction():
    company_id = 1
    employee_id = _seed_employee(company_id=company_id)
    dtype_id = _seed_deduction_type(company_id=None, code="EI_TEST_FLAT")
    _seed_config(
        company_id=company_id,
        deduction_type_id=dtype_id,
        amount_cents=777,
    )

    db = SessionLocal()
    try:
        rows = compute_deduction_amounts(
            company_id=company_id,
            employee_id=employee_id,
            gross_pay_cents=10000,
            db=db,
        )
    finally:
        db.close()

    by_code = {str(r["deduction_type_code"]): int(r["amount_cents"]) for r in rows}
    assert by_code["EI_TEST_FLAT"] == 777


def test_employee_override_takes_precedence():
    company_id = 1
    employee_id = _seed_employee(company_id=company_id)
    dtype_id = _seed_deduction_type(company_id=None, code="FED_TAX_OVERRIDE")
    _seed_config(
        company_id=company_id,
        deduction_type_id=dtype_id,
        rate_percent=Decimal("10.0"),
    )
    _seed_config(
        company_id=company_id,
        deduction_type_id=dtype_id,
        employee_id=employee_id,
        amount_cents=250,
    )

    db = SessionLocal()
    try:
        rows = compute_deduction_amounts(
            company_id=company_id,
            employee_id=employee_id,
            gross_pay_cents=10000,
            db=db,
        )
    finally:
        db.close()

    by_code = {str(r["deduction_type_code"]): int(r["amount_cents"]) for r in rows}
    assert by_code["FED_TAX_OVERRIDE"] == 250


def test_inactive_config_ignored():
    company_id = 1
    employee_id = _seed_employee(company_id=company_id)
    inactive_dtype_id = _seed_deduction_type(company_id=None, code="INACTIVE_TYPE", is_active=False)
    _seed_config(
        company_id=company_id,
        deduction_type_id=inactive_dtype_id,
        amount_cents=999,
    )

    active_dtype_id = _seed_deduction_type(company_id=None, code="ACTIVE_TYPE", is_active=True)
    _seed_config(
        company_id=company_id,
        deduction_type_id=active_dtype_id,
        amount_cents=111,
        effective_from=date.today() - timedelta(days=1),
    )

    db = SessionLocal()
    try:
        rows = compute_deduction_amounts(
            company_id=company_id,
            employee_id=employee_id,
            gross_pay_cents=10000,
            db=db,
        )
    finally:
        db.close()

    by_code = {str(r["deduction_type_code"]): int(r["amount_cents"]) for r in rows}
    assert "INACTIVE_TYPE" not in by_code
    assert by_code["ACTIVE_TYPE"] == 111


def test_cpp_statutory_calculation_path_uses_statutory_calculator():
    company_id = 1
    employee_id = _seed_employee(company_id=company_id)

    db = SessionLocal()
    try:
        rows = compute_deduction_amounts(
            company_id=company_id,
            employee_id=employee_id,
            gross_pay_cents=10000,
            db=db,
        )
    finally:
        db.close()

    by_code = {str(r["deduction_type_code"]): r for r in rows}
    assert by_code["CPP"]["amount_cents"] == 600
    assert by_code["CPP"]["calculation_source"] == "STATUTORY"


def test_ei_statutory_calculation_path_uses_statutory_calculator():
    company_id = 1
    employee_id = _seed_employee(company_id=company_id)

    db = SessionLocal()
    try:
        rows = compute_deduction_amounts(
            company_id=company_id,
            employee_id=employee_id,
            gross_pay_cents=10000,
            db=db,
        )
    finally:
        db.close()

    by_code = {str(r["deduction_type_code"]): r for r in rows}
    assert by_code["EI"]["amount_cents"] == 200
    assert by_code["EI"]["calculation_source"] == "STATUTORY"
