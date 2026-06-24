from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.company_profile import CompanyProfile
from app.models.employee import Employee
from app.models.payroll_t4_filing_artifact import PayrollT4FilingArtifact
from app.models.payroll_t4 import PayrollT4
from app.services.payroll_audit_service import (
    PAYROLL_T4_FILING_ARTIFACT_PREPARED_EVENT,
    record_payroll_audit_event,
)
from app.services.payroll_t4_export_service import build_t4_export_preparation
from app.services.payroll_t4_filing_storage_service import (
    build_db_backed_t4_filing_storage_key,
    clear_t4_filing_xml_validation_state,
    store_t4_filing_artifact_blob,
)

FILING_PACKAGE_SCHEMA_ID = "frontier_payroll_cra_t4_filing_package"
FILING_PACKAGE_SCHEMA_VERSION = "1.0"
FILING_PACKAGE_ARTIFACT_KIND = "CRA_T4_FILING_PACKAGE_PREPARATION"


def _normalize_registration_country(company: CompanyProfile | None) -> str | None:
    if company is None:
        return None
    value = str(company.payroll_registration_country or "").strip().upper()
    return value or None


def _serialize_package_blob(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def get_payroll_t4_filing_artifact_row(
    *,
    db: Session,
    company_id: int,
    tax_year: int,
) -> PayrollT4FilingArtifact | None:
    return (
        db.query(PayrollT4FilingArtifact)
        .filter(PayrollT4FilingArtifact.company_id == int(company_id))
        .filter(PayrollT4FilingArtifact.tax_year == int(tax_year))
        .one_or_none()
    )


def get_payroll_t4_filing_artifact_row_by_id(
    *,
    db: Session,
    company_id: int,
    filing_artifact_id: str,
) -> PayrollT4FilingArtifact | None:
    return (
        db.query(PayrollT4FilingArtifact)
        .filter(PayrollT4FilingArtifact.company_id == int(company_id))
        .filter(PayrollT4FilingArtifact.filing_artifact_id == str(filing_artifact_id))
        .one_or_none()
    )


def _build_company_registration_snapshot(company: CompanyProfile | None) -> dict[str, object] | None:
    if company is None:
        return None
    return {
        "company_id": int(company.company_id),
        "company_name": str(company.company_name),
        "country": str(company.country),
        "province_or_state": str(company.province_or_state),
        "cra_business_number": None if company.cra_business_number is None else str(company.cra_business_number),
        "cra_payroll_program_account_number": (
            None
            if company.cra_payroll_program_account_number is None
            else str(company.cra_payroll_program_account_number)
        ),
        "payroll_registration_country": _normalize_registration_country(company),
    }


def _build_filing_package_payload(
    *,
    tax_year: int,
    filing_status: str,
    export_ready: bool,
    filing_ready: bool,
    company_registration_snapshot: dict[str, object] | None,
    employer_summary: dict[str, int],
    prepared_rows: list[dict[str, object]],
    blocking_issues: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_id": FILING_PACKAGE_SCHEMA_ID,
        "schema_version": FILING_PACKAGE_SCHEMA_VERSION,
        "package_kind": FILING_PACKAGE_ARTIFACT_KIND,
        "tax_authority": "CRA",
        "tax_year": int(tax_year),
        "filing_status": str(filing_status),
        "export_ready": bool(export_ready),
        "filing_ready": bool(filing_ready),
        "employer_registration": company_registration_snapshot,
        "employer_summary": employer_summary,
        "t4_rows": prepared_rows,
        "blocking_issues": blocking_issues,
    }


def prepare_t4_filing_artifact(
    *,
    db: Session,
    company_id: int,
    tax_year: int,
    actor_user_id: str | None = None,
) -> dict[str, object]:
    export = build_t4_export_preparation(
        db=db,
        company_id=int(company_id),
        tax_year=int(tax_year),
    )
    company = (
        db.query(CompanyProfile)
        .filter(CompanyProfile.company_id == int(company_id))
        .one_or_none()
    )
    employees = {
        int(employee.id): employee
        for employee in (
            db.query(Employee)
            .filter(Employee.company_id == int(company_id))
            .all()
        )
    }
    t4_rows = (
        db.query(PayrollT4)
        .filter(PayrollT4.company_id == int(company_id))
        .filter(PayrollT4.tax_year == int(tax_year))
        .order_by(PayrollT4.employee_id.asc(), PayrollT4.t4_id.asc())
        .all()
    )
    t4_by_id = {str(row.t4_id): row for row in t4_rows}

    prepared_rows: list[dict[str, object]] = []
    for export_row in list(export["rows"]):
        employee_id = int(export_row["employee_id"])
        employee = employees.get(employee_id)
        payroll_t4 = t4_by_id.get(str(export_row["t4_id"]))
        prepared_rows.append(
            {
                "t4_id": str(export_row["t4_id"]),
                "employee_id": employee_id,
                "employee_display_name": export_row["employee_display_name"],
                "employee_legal_name": str(export_row["employee_legal_name"]),
                "employee_sin": None if employee is None or employee.sin is None else str(employee.sin),
                "employee_address": None
                if employee is None
                else {
                    "address_line_1": str(employee.address_line_1 or employee.mailing_address_line_1 or ""),
                    "city": str(employee.city or employee.mailing_city or ""),
                    "province": str(employee.province or employee.mailing_province or ""),
                    "postal_code": str(employee.postal_code or employee.mailing_postal_code or ""),
                    "country": str(employee.country or employee.mailing_country or ""),
                },
                "tax_year": int(export_row["tax_year"]),
                "employment_income_cents": int(export_row["employment_income_cents"]),
                "cpp_contributions_cents": int(export_row["cpp_contributions_cents"]),
                "ei_premiums_cents": int(export_row["ei_premiums_cents"]),
                "income_tax_deducted_cents": int(export_row["income_tax_deducted_cents"]),
                "other_deductions_cents": int(export_row["other_deductions_cents"]),
                "delivery_state": str(export_row["delivery_state"]),
                "slip_generated_at": (
                    None if payroll_t4 is None or payroll_t4.slip_generated_at is None else payroll_t4.slip_generated_at.isoformat()
                ),
                "artifact_state": str(export_row["artifact_state"]),
                "ready_for_filing": bool(export_row["ready_for_export"]),
                "blocking_issue_codes": list(export_row["blocking_issue_codes"]),
            }
        )

    employer_summary = {
        "t4_record_count": int(export["summary"]["t4_record_count"]),
        "employment_income_cents": int(export["summary"]["employment_income_cents"]),
        "cpp_contributions_cents": int(export["summary"]["cpp_contributions_cents"]),
        "ei_premiums_cents": int(export["summary"]["ei_premiums_cents"]),
        "income_tax_deducted_cents": int(export["summary"]["income_tax_deducted_cents"]),
        "other_deductions_cents": int(sum(int(row["other_deductions_cents"]) for row in prepared_rows)),
        "delivered_count": int(export["summary"]["delivered_count"]),
        "employee_downloaded_count": int(export["summary"]["employee_downloaded_count"]),
        "employee_acknowledged_count": int(export["summary"]["employee_acknowledged_count"]),
    }

    company_registration_snapshot = _build_company_registration_snapshot(company)

    filing_ready = bool(export["export_ready"])
    filing_status = "FILING_ARTIFACT_READY" if filing_ready else "FILING_ARTIFACT_BLOCKED"
    prepared_at = datetime.now(timezone.utc).isoformat()
    prepared_payload = {
        "schema_version": "frontier_payroll_t4_filing_v1",
        "tax_authority": "CRA",
        "artifact_kind": "T4_YEAR_END_FILING_PREPARATION",
        "tax_year": int(tax_year),
        "prepared_at": prepared_at,
        "filing_status": filing_status,
        "export_ready": bool(export["export_ready"]),
        "filing_ready": filing_ready,
        "company_registration": company_registration_snapshot,
        "employer_summary": employer_summary,
        "t4_rows": prepared_rows,
        "blocking_issues": list(export["blocking_issues"]),
    }
    filing_package = _build_filing_package_payload(
        tax_year=int(tax_year),
        filing_status=filing_status,
        export_ready=bool(export["export_ready"]),
        filing_ready=filing_ready,
        company_registration_snapshot=company_registration_snapshot,
        employer_summary=employer_summary,
        prepared_rows=prepared_rows,
        blocking_issues=list(export["blocking_issues"]),
    )

    artifact_blob = _serialize_package_blob(filing_package)
    artifact_file_name = f"t4-filing-package-{int(tax_year)}.json"
    artifact_row = get_payroll_t4_filing_artifact_row(
        db=db,
        company_id=int(company_id),
        tax_year=int(tax_year),
    )
    if artifact_row is None:
        artifact_row = PayrollT4FilingArtifact(
            company_id=int(company_id),
            tax_year=int(tax_year),
            filing_status=filing_status,
            prepared_payload_json=filing_package,
            artifact_storage_key="pending",
            artifact_file_name=artifact_file_name,
            artifact_content_type="application/json",
            artifact_blob=b"",
            artifact_byte_size=0,
            artifact_sha256="pending",
            prepared_by_user_id=actor_user_id,
        )
        db.add(artifact_row)
        db.flush()

    previous_artifact_sha = None if artifact_row.artifact_sha256 is None else str(artifact_row.artifact_sha256)
    artifact_row.filing_status = filing_status
    artifact_row.prepared_payload_json = filing_package
    artifact_row.prepared_at = datetime.now(timezone.utc)
    artifact_row.prepared_by_user_id = actor_user_id
    artifact = store_t4_filing_artifact_blob(
        artifact_row,
        storage_key=build_db_backed_t4_filing_storage_key(
            company_id=int(company_id),
            tax_year=int(tax_year),
            file_name=artifact_file_name,
        ),
        file_name=artifact_file_name,
        content_type="application/json",
        blob=artifact_blob,
    )
    if previous_artifact_sha is not None and previous_artifact_sha != artifact.sha256:
        clear_t4_filing_xml_validation_state(artifact_row)
    db.flush()

    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=None,
        event_type=PAYROLL_T4_FILING_ARTIFACT_PREPARED_EVENT,
        actor_user_id=actor_user_id,
        payload_json={
            "tax_year": int(tax_year),
            "filing_status": filing_status,
            "export_ready": bool(export["export_ready"]),
            "filing_ready": filing_ready,
            "blocking_issue_codes": [issue["code"] for issue in list(export["blocking_issues"])],
            "artifact_file_name": artifact.file_name,
            "artifact_sha256": artifact.sha256,
            "package_schema_id": FILING_PACKAGE_SCHEMA_ID,
            "package_schema_version": FILING_PACKAGE_SCHEMA_VERSION,
        },
    )

    return {
        "tax_year": int(tax_year),
        "prepared_at": prepared_at,
        "filing_status": filing_status,
        "export_ready": bool(export["export_ready"]),
        "filing_ready": filing_ready,
        "company_registration": company_registration_snapshot,
        "summary": employer_summary,
        "rows": prepared_rows,
        "blocking_issues": list(export["blocking_issues"]),
        "prepared_payload": prepared_payload,
        "filing_package": filing_package,
        "filing_artifact": {
            "filing_artifact_id": str(artifact_row.filing_artifact_id),
            "file_name": artifact.file_name,
            "content_type": artifact.content_type,
            "byte_size": int(artifact.byte_size),
            "sha256": artifact.sha256,
            "storage_key": artifact.storage_key,
            "prepared_by_user_id": artifact_row.prepared_by_user_id,
        },
    }
