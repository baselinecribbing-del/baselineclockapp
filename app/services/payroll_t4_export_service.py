from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.company_profile import CompanyProfile
from app.models.employee import Employee
from app.models.payroll_t4 import PayrollT4
from app.services.payroll_audit_service import PAYROLL_T4_EXPORT_PREPARED_EVENT, record_payroll_audit_event


@dataclass(frozen=True)
class PayrollT4ExportBlockingIssue:
    code: str
    message: str
    scope: str
    employee_id: int | None = None
    t4_id: str | None = None


def _has_address(employee: Employee) -> bool:
    physical_complete = all(
        [
            str(employee.address_line_1 or "").strip(),
            str(employee.city or "").strip(),
            str(employee.province or "").strip(),
            str(employee.postal_code or "").strip(),
            str(employee.country or "").strip(),
        ]
    )
    mailing_complete = all(
        [
            str(employee.mailing_address_line_1 or "").strip(),
            str(employee.mailing_city or "").strip(),
            str(employee.mailing_province or "").strip(),
            str(employee.mailing_postal_code or "").strip(),
            str(employee.mailing_country or "").strip(),
        ]
    )
    return bool(physical_complete or mailing_complete)


def _normalize_name(employee: Employee) -> str:
    return str(employee.legal_name or employee.name or f"Employee {int(employee.id)}")


def build_t4_export_preparation(
    *,
    db: Session,
    company_id: int,
    tax_year: int,
) -> dict[str, object]:
    company = (
        db.query(CompanyProfile)
        .filter(CompanyProfile.company_id == int(company_id))
        .one_or_none()
    )

    rows = (
        db.query(PayrollT4, Employee)
        .join(
            Employee,
            (Employee.company_id == PayrollT4.company_id) & (Employee.id == PayrollT4.employee_id),
        )
        .filter(PayrollT4.company_id == int(company_id))
        .filter(PayrollT4.tax_year == int(tax_year))
        .order_by(PayrollT4.employee_id.asc(), PayrollT4.t4_id.asc())
        .all()
    )

    blocking_issues: list[PayrollT4ExportBlockingIssue] = []
    if company is None:
        blocking_issues.append(
            PayrollT4ExportBlockingIssue(
                code="company_profile_missing",
                message="Company profile is required before T4 export preparation can be considered ready.",
                scope="COMPANY",
            )
        )
    else:
        if str(company.company_name or "").strip() == "":
            blocking_issues.append(
                PayrollT4ExportBlockingIssue(
                    code="company_name_missing",
                    message="Company name is required for T4 export preparation.",
                    scope="COMPANY",
                )
            )
        if str(company.country or "").strip().upper() != "CA":
            blocking_issues.append(
                PayrollT4ExportBlockingIssue(
                    code="company_country_not_ca",
                    message="T4 export preparation is only supported for Canadian company profiles.",
                    scope="COMPANY",
                )
            )
        if str(company.province_or_state or "").strip() == "":
            blocking_issues.append(
                PayrollT4ExportBlockingIssue(
                    code="company_province_missing",
                    message="Company province/state is required for T4 export preparation.",
                    scope="COMPANY",
                )
            )
        if str(company.cra_business_number or "").strip() == "":
            blocking_issues.append(
                PayrollT4ExportBlockingIssue(
                    code="cra_business_number_missing",
                    message="CRA business number is required before T4 export can be prepared for filing.",
                    scope="COMPANY",
                )
            )
        if str(company.cra_payroll_program_account_number or "").strip() == "":
            blocking_issues.append(
                PayrollT4ExportBlockingIssue(
                    code="cra_payroll_program_account_number_missing",
                    message="CRA payroll program account number is required before T4 export can be prepared for filing.",
                    scope="COMPANY",
                )
            )
        registration_country = str(company.payroll_registration_country or "").strip().upper()
        if registration_country == "":
            blocking_issues.append(
                PayrollT4ExportBlockingIssue(
                    code="payroll_registration_country_missing",
                    message="Payroll registration country is required before T4 export can be prepared for filing.",
                    scope="COMPANY",
                )
            )
        elif registration_country != "CA":
            blocking_issues.append(
                PayrollT4ExportBlockingIssue(
                    code="payroll_registration_country_not_ca",
                    message="CRA T4 export preparation requires a Canadian payroll registration country.",
                    scope="COMPANY",
                )
            )

    if not rows:
        blocking_issues.append(
            PayrollT4ExportBlockingIssue(
                code="t4_records_missing",
                message="No payroll T4 records exist for the requested tax year.",
                scope="EXPORT",
            )
        )

    prepared_rows: list[dict[str, object]] = []
    ready_rows = 0
    available_artifact_rows = 0

    for payroll_t4, employee in rows:
        row_issue_codes: list[str] = []
        has_legal_name = bool(str(_normalize_name(employee)).strip())
        has_sin = bool(str(employee.sin or "").strip())
        has_address = _has_address(employee)

        if not has_legal_name:
            row_issue_codes.append("employee_legal_name_missing")
        if not has_sin:
            row_issue_codes.append("employee_sin_missing")
        if not has_address:
            row_issue_codes.append("employee_address_missing")

        for code in row_issue_codes:
            blocking_issues.append(
                PayrollT4ExportBlockingIssue(
                    code=code,
                    message=f"{_normalize_name(employee)} is missing data required for export preparation.",
                    scope="T4",
                    employee_id=int(employee.id),
                    t4_id=str(payroll_t4.t4_id),
                )
            )

        artifact_state = "AVAILABLE" if str(payroll_t4.slip_status) == "AVAILABLE" else "NOT_GENERATED"
        delivery_state = "DELIVERED_MANUAL" if str(payroll_t4.delivery_status) == "DELIVERED_MANUAL" else "PENDING_MANUAL"
        ready_for_export = not row_issue_codes
        if ready_for_export:
            ready_rows += 1
        if artifact_state == "AVAILABLE":
            available_artifact_rows += 1

        prepared_rows.append(
            {
                "t4_id": str(payroll_t4.t4_id),
                "employee_id": int(employee.id),
                "employee_display_name": str(employee.name),
                "employee_legal_name": _normalize_name(employee),
                "tax_year": int(payroll_t4.tax_year),
                "employment_income_cents": int(payroll_t4.employment_income_cents),
                "cpp_contributions_cents": int(payroll_t4.cpp_contributions_cents),
                "ei_premiums_cents": int(payroll_t4.ei_premiums_cents),
                "income_tax_deducted_cents": int(payroll_t4.income_tax_deducted_cents),
                "other_deductions_cents": int(payroll_t4.other_deductions_cents),
                "artifact_state": artifact_state,
                "delivery_state": delivery_state,
                "slip_available_at": None if payroll_t4.slip_available_at is None else payroll_t4.slip_available_at.isoformat(),
                "delivered_at": None if payroll_t4.delivered_at is None else payroll_t4.delivered_at.isoformat(),
                "employee_download_count": int(payroll_t4.employee_download_count or 0),
                "employee_acknowledged_at": (
                    None
                    if payroll_t4.employee_acknowledged_at is None
                    else payroll_t4.employee_acknowledged_at.isoformat()
                ),
                "has_legal_name": has_legal_name,
                "has_sin": has_sin,
                "has_address": has_address,
                "ready_for_export": ready_for_export,
                "blocking_issue_codes": row_issue_codes,
            }
        )

    export_ready = bool(rows) and not blocking_issues
    return {
        "tax_authority": "CRA",
        "tax_year": int(tax_year),
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "export_status": "EXPORT_READY" if export_ready else "EXPORT_PREPARATION_BLOCKED",
        "export_ready": export_ready,
        "company": None
        if company is None
        else {
            "company_id": int(company.company_id),
            "company_name": str(company.company_name),
            "country": str(company.country),
            "province_or_state": str(company.province_or_state),
        },
        "summary": {
            "t4_record_count": int(len(prepared_rows)),
            "ready_record_count": int(ready_rows),
            "artifact_available_count": int(available_artifact_rows),
            "delivered_count": int(sum(1 for row in prepared_rows if row["delivery_state"] == "DELIVERED_MANUAL")),
            "employee_downloaded_count": int(sum(1 for row in prepared_rows if int(row["employee_download_count"]) > 0)),
            "employee_acknowledged_count": int(sum(1 for row in prepared_rows if row["employee_acknowledged_at"] is not None)),
            "employment_income_cents": int(sum(int(row["employment_income_cents"]) for row in prepared_rows)),
            "cpp_contributions_cents": int(sum(int(row["cpp_contributions_cents"]) for row in prepared_rows)),
            "ei_premiums_cents": int(sum(int(row["ei_premiums_cents"]) for row in prepared_rows)),
            "income_tax_deducted_cents": int(sum(int(row["income_tax_deducted_cents"]) for row in prepared_rows)),
        },
        "blocking_issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "scope": issue.scope,
                "employee_id": issue.employee_id,
                "t4_id": issue.t4_id,
            }
            for issue in blocking_issues
        ],
        "rows": prepared_rows,
    }


def prepare_t4_export(
    *,
    db: Session,
    company_id: int,
    tax_year: int,
    actor_user_id: str | None = None,
) -> dict[str, object]:
    result = build_t4_export_preparation(
        db=db,
        company_id=int(company_id),
        tax_year=int(tax_year),
    )
    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=None,
        event_type=PAYROLL_T4_EXPORT_PREPARED_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "tax_year": int(tax_year),
            "export_status": str(result["export_status"]),
            "export_ready": bool(result["export_ready"]),
            "t4_record_count": int(result["summary"]["t4_record_count"]),
            "blocking_issue_codes": [issue["code"] for issue in result["blocking_issues"]],
        },
    )
    return result
