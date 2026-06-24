from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.employee_payroll_enrollment import EmployeePayrollEnrollment
from app.models.employee_vacation_assignment import EmployeeVacationAssignment
from app.models.vacation_policy import VacationPolicy


@dataclass
class EffectiveVacationConfig:
    assignment: EmployeeVacationAssignment
    policy: VacationPolicy


def _employee_is_effective(*, employee: Employee, as_of_date: date) -> bool:
    if employee.hire_date is not None and employee.hire_date > as_of_date:
        return False
    if employee.termination_date is not None and employee.termination_date < as_of_date:
        return False
    return True


def resolve_effective_vacation_config(
    *,
    db: Session,
    company_id: int,
    employee_id: int,
    as_of_date: date,
) -> EffectiveVacationConfig | None:
    employee = (
        db.query(Employee)
        .filter(Employee.company_id == int(company_id))
        .filter(Employee.id == int(employee_id))
        .one_or_none()
    )
    if employee is None or not _employee_is_effective(employee=employee, as_of_date=as_of_date):
        return None

    rows = (
        db.query(EmployeeVacationAssignment, VacationPolicy)
        .join(VacationPolicy, VacationPolicy.vacation_policy_id == EmployeeVacationAssignment.vacation_policy_id)
        .filter(EmployeeVacationAssignment.company_id == int(company_id))
        .filter(EmployeeVacationAssignment.employee_id == int(employee_id))
        .filter(VacationPolicy.company_id == int(company_id))
        .filter(EmployeeVacationAssignment.effective_start_date <= as_of_date)
        .filter(
            (EmployeeVacationAssignment.effective_end_date.is_(None))
            | (EmployeeVacationAssignment.effective_end_date >= as_of_date)
        )
        .order_by(
            EmployeeVacationAssignment.effective_start_date.desc(),
            EmployeeVacationAssignment.created_at.desc(),
            EmployeeVacationAssignment.assignment_id.asc(),
        )
        .all()
    )
    if not rows:
        return None

    assignment, policy = rows[0]
    return EffectiveVacationConfig(assignment=assignment, policy=policy)


def resolve_effective_payroll_enrollments(
    *,
    db: Session,
    company_id: int,
    employee_id: int,
    as_of_date: date,
) -> list[EmployeePayrollEnrollment]:
    employee = (
        db.query(Employee)
        .filter(Employee.company_id == int(company_id))
        .filter(Employee.id == int(employee_id))
        .one_or_none()
    )
    if employee is None or not _employee_is_effective(employee=employee, as_of_date=as_of_date):
        return []

    return (
        db.query(EmployeePayrollEnrollment)
        .filter(EmployeePayrollEnrollment.company_id == int(company_id))
        .filter(EmployeePayrollEnrollment.employee_id == int(employee_id))
        .filter(EmployeePayrollEnrollment.is_active.is_(True))
        .filter(EmployeePayrollEnrollment.effective_start_date <= as_of_date)
        .filter(
            (EmployeePayrollEnrollment.effective_end_date.is_(None))
            | (EmployeePayrollEnrollment.effective_end_date >= as_of_date)
        )
        .order_by(
            EmployeePayrollEnrollment.category.asc(),
            EmployeePayrollEnrollment.code.asc(),
            EmployeePayrollEnrollment.effective_start_date.desc(),
            EmployeePayrollEnrollment.created_at.desc(),
            EmployeePayrollEnrollment.enrollment_id.asc(),
        )
        .all()
    )
