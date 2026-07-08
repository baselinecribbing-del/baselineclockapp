from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.payroll_deduction import PayrollDeduction
from app.models.payroll_run import PayrollRun

FEDERAL_TAX_CODES = {"TAX", "FEDERAL_TAX", "FED_TAX_OVERRIDE"}
PROVINCIAL_TAX_CODES = {"PROVINCIAL_TAX", "PROV_TAX_OVERRIDE"}


def _component(amount_cents: int | None, available: bool) -> dict[str, Any]:
    return {
        "amount_cents": amount_cents if available else None,
        "available": bool(available),
    }


def get_source_deduction_summary(*, db: Session, company_id: int, payroll_run_id: str) -> dict[str, Any]:
    payroll_run = (
        db.query(PayrollRun)
        .filter(PayrollRun.company_id == int(company_id))
        .filter(PayrollRun.payroll_run_id == str(payroll_run_id))
        .one_or_none()
    )
    if payroll_run is None:
        raise ValueError("PayrollRun not found")

    rows = (
        db.query(
            PayrollDeduction.deduction_type,
            func.coalesce(func.sum(PayrollDeduction.amount_cents), 0),
        )
        .filter(PayrollDeduction.company_id == int(company_id))
        .filter(PayrollDeduction.payroll_run_id == str(payroll_run_id))
        .group_by(PayrollDeduction.deduction_type)
        .all()
    )
    totals_by_type = {str(code): int(amount or 0) for code, amount in rows}

    cpp_employee_available = "CPP" in totals_by_type
    ei_employee_available = "EI" in totals_by_type
    federal_tax_matches = [amount for code, amount in totals_by_type.items() if code in FEDERAL_TAX_CODES]
    provincial_tax_matches = [amount for code, amount in totals_by_type.items() if code in PROVINCIAL_TAX_CODES]
    federal_tax_available = bool(federal_tax_matches)
    provincial_tax_available = bool(provincial_tax_matches)

    employee_known_total_cents = 0
    if cpp_employee_available:
        employee_known_total_cents += int(totals_by_type["CPP"])
    if ei_employee_available:
        employee_known_total_cents += int(totals_by_type["EI"])
    if federal_tax_available:
        employee_known_total_cents += sum(int(v) for v in federal_tax_matches)
    if provincial_tax_available:
        employee_known_total_cents += sum(int(v) for v in provincial_tax_matches)

    employer_available = False

    return {
        "payroll_run_id": str(payroll_run_id),
        "approval_status": str(payroll_run.status),
        "components": {
            "cpp_employee": _component(
                totals_by_type.get("CPP"),
                cpp_employee_available,
            ),
            "cpp_employer": _component(None, False),
            "ei_employee": _component(
                totals_by_type.get("EI"),
                ei_employee_available,
            ),
            "ei_employer": _component(None, False),
            "federal_tax": _component(
                sum(int(v) for v in federal_tax_matches) if federal_tax_available else None,
                federal_tax_available,
            ),
            "provincial_tax": _component(
                sum(int(v) for v in provincial_tax_matches) if provincial_tax_available else None,
                provincial_tax_available,
            ),
        },
        "remittance_totals": {
            "employee_portions_cents": int(employee_known_total_cents),
            "employer_portions_cents": None,
            "total_cents": None if not employer_available else int(employee_known_total_cents),
            "available": False,
        },
        "due_date": None,
        "remittance_status": "UNAVAILABLE",
    }
