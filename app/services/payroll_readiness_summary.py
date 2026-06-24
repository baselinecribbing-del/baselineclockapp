from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
from app.models.time_entry import TimeEntry
from app.services.payroll_t4_xml_validation_service import get_active_payroll_t4_xml_validator


def _empty_or_null(column):
    return or_(column.is_(None), func.length(func.trim(column)) == 0)


def get_payroll_readiness_summary(*, db: Session, company_id: int) -> dict[str, Any]:
    company_id = int(company_id)

    pending_time_approvals_count = int(
        db.query(func.count(TimeEntry.time_entry_id))
        .join(
            Employee,
            (Employee.id == TimeEntry.employee_id) & (Employee.company_id == TimeEntry.company_id),
        )
        .filter(TimeEntry.company_id == company_id)
        .filter(TimeEntry.status == "completed")
        .filter(TimeEntry.approval_status == "pending")
        .filter(Employee.requires_payroll.is_(True))
        .scalar()
        or 0
    )

    rejected_time_entries_count = int(
        db.query(func.count(TimeEntry.time_entry_id))
        .join(
            Employee,
            (Employee.id == TimeEntry.employee_id) & (Employee.company_id == TimeEntry.company_id),
        )
        .filter(TimeEntry.company_id == company_id)
        .filter(TimeEntry.status == "completed")
        .filter(TimeEntry.approval_status == "rejected")
        .filter(Employee.requires_payroll.is_(True))
        .scalar()
        or 0
    )

    missing_payment_condition = _empty_or_null(Employee.payment_method)
    missing_tax_condition = or_(
        _empty_or_null(Employee.sin),
        _empty_or_null(Employee.province_of_employment),
        Employee.federal_claim_amount.is_(None),
    )

    employees_missing_payment_method_count = int(
        db.query(func.count(Employee.id))
        .filter(Employee.company_id == company_id)
        .filter(Employee.requires_payroll.is_(True))
        .filter(Employee.is_active.is_(True))
        .filter(missing_payment_condition)
        .scalar()
        or 0
    )

    employees_missing_tax_setup_count = int(
        db.query(func.count(Employee.id))
        .filter(Employee.company_id == company_id)
        .filter(Employee.requires_payroll.is_(True))
        .filter(Employee.is_active.is_(True))
        .filter(missing_tax_condition)
        .scalar()
        or 0
    )

    employees_not_payroll_ready_count = int(
        db.query(func.count(Employee.id))
        .filter(Employee.company_id == company_id)
        .filter(Employee.requires_payroll.is_(True))
        .filter(Employee.is_active.is_(True))
        .filter(or_(missing_payment_condition, missing_tax_condition))
        .scalar()
        or 0
    )

    approved_hours_ready_count: float | None = None
    today = date.today()
    current_pay_periods = (
        db.query(PayPeriod)
        .filter(PayPeriod.company_id == company_id)
        .filter(PayPeriod.status == "OPEN")
        .filter(PayPeriod.start_date <= today)
        .filter(PayPeriod.end_date >= today)
        .all()
    )

    if len(current_pay_periods) == 1:
        pay_period = current_pay_periods[0]
        ready_seconds = (
            db.query(func.sum(func.extract("epoch", TimeEntry.ended_at - TimeEntry.started_at)))
            .join(
                Employee,
                (Employee.id == TimeEntry.employee_id) & (Employee.company_id == TimeEntry.company_id),
            )
            .filter(TimeEntry.company_id == company_id)
            .filter(TimeEntry.status == "completed")
            .filter(TimeEntry.approval_status == "approved")
            .filter(Employee.requires_payroll.is_(True))
            .filter(func.date(TimeEntry.started_at) >= pay_period.start_date)
            .filter(func.date(TimeEntry.started_at) <= pay_period.end_date)
            .filter(
                ~TimeEntry.time_entry_id.in_(
                    db.query(PayrollItem.source_time_entry_id)
                    .filter(PayrollItem.company_id == company_id)
                    .filter(PayrollItem.source_time_entry_id.isnot(None))
                )
            )
            .scalar()
        ) or 0
        approved_hours_ready_count = round(float(ready_seconds) / 3600.0, 2)

    return {
        "pending_time_approvals_count": pending_time_approvals_count,
        "rejected_time_entries_count": rejected_time_entries_count,
        "employees_not_payroll_ready_count": employees_not_payroll_ready_count,
        "employees_missing_tax_setup_count": employees_missing_tax_setup_count,
        "employees_missing_payment_method_count": employees_missing_payment_method_count,
        "approved_hours_ready_count": approved_hours_ready_count,
    }


def get_payroll_compliance_readiness_capabilities() -> dict[str, bool]:
    validator = get_active_payroll_t4_xml_validator()
    xml_validation_available = validator is not None
    official_cra_xsd_validation_available = bool(
        xml_validation_available and str(validator.validation_mode).upper() == "OFFICIAL_CRA_XSD"
    )

    return {
        "xml_validation_available": xml_validation_available,
        "manual_submission_supported": True,
        "submission_attempt_tracking_available": True,
        "submission_retry_supported": True,
        "submission_attempt_timeline_available": True,
        "transmission_integration_available": False,
        "response_ingestion_available": False,
        "official_cra_xsd_validation_available": official_cra_xsd_validation_available,
    }
