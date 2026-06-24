from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from app.models.payroll_t4_filing_artifact import PayrollT4FilingArtifact
from app.services.payroll_audit_service import (
    PAYROLL_T4_XML_PACKAGE_GENERATED_EVENT,
    PAYROLL_T4_XML_PACKAGE_REGENERATED_EVENT,
    record_payroll_audit_event,
)
from app.services.payroll_t4_filing_storage_service import (
    build_db_backed_t4_filing_storage_key,
    store_t4_filing_xml_package_blob,
)
from app.services.payroll_t4_xml_validation_service import validate_t4_xml_package

XML_PACKAGE_SCHEMA_ID = "frontier_payroll_cra_t4_xml_package"
XML_PACKAGE_SCHEMA_VERSION = "1.0"
XML_PACKAGE_ARTIFACT_KIND = "CRA_T4_XML_SCHEMA_ALIGNED_PACKAGE"
XML_PACKAGE_CONTENT_TYPE = "application/xml"


@dataclass(frozen=True)
class PayrollT4XmlValidationIssue:
    code: str
    message: str
    path: str


class PayrollT4XmlValidationError(ValueError):
    def __init__(self, issues: list[PayrollT4XmlValidationIssue]):
        super().__init__("T4 XML package generation is blocked by canonical filing artifact validation errors")
        self.issues = issues


def _text(value: Any) -> str:
    return escape("" if value is None else str(value))


def _append_tag(lines: list[str], indent: str, tag: str, value: Any) -> None:
    lines.append(f"{indent}<{tag}>{_text(value)}</{tag}>")


def _required_str(
    issues: list[PayrollT4XmlValidationIssue],
    source: dict[str, Any] | None,
    *,
    key: str,
    path: str,
    message: str,
) -> str | None:
    value = None if source is None else source.get(key)
    normalized = str(value or "").strip()
    if normalized == "":
        issues.append(PayrollT4XmlValidationIssue(code=f"{key}_missing", message=message, path=path))
        return None
    return normalized


def _required_int(
    issues: list[PayrollT4XmlValidationIssue],
    source: dict[str, Any] | None,
    *,
    key: str,
    path: str,
    message: str,
) -> int | None:
    value = None if source is None else source.get(key)
    if value is None:
        issues.append(PayrollT4XmlValidationIssue(code=f"{key}_missing", message=message, path=path))
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        issues.append(PayrollT4XmlValidationIssue(code=f"{key}_invalid", message=message, path=path))
        return None


def _validate_canonical_filing_payload(payload: dict[str, Any]) -> list[PayrollT4XmlValidationIssue]:
    issues: list[PayrollT4XmlValidationIssue] = []

    _required_str(
        issues,
        payload,
        key="schema_id",
        path="schema_id",
        message="Canonical filing package schema_id is required before XML package generation.",
    )
    _required_str(
        issues,
        payload,
        key="schema_version",
        path="schema_version",
        message="Canonical filing package schema_version is required before XML package generation.",
    )

    employer_registration = payload.get("employer_registration")
    if not isinstance(employer_registration, dict):
        issues.append(
            PayrollT4XmlValidationIssue(
                code="employer_registration_missing",
                message="Employer registration data is required before XML package generation.",
                path="employer_registration",
            )
        )
    else:
        _required_str(
            issues,
            employer_registration,
            key="company_name",
            path="employer_registration.company_name",
            message="Employer company name is required before XML package generation.",
        )
        _required_str(
            issues,
            employer_registration,
            key="country",
            path="employer_registration.country",
            message="Employer country is required before XML package generation.",
        )
        _required_str(
            issues,
            employer_registration,
            key="province_or_state",
            path="employer_registration.province_or_state",
            message="Employer province/state is required before XML package generation.",
        )
        _required_str(
            issues,
            employer_registration,
            key="cra_business_number",
            path="employer_registration.cra_business_number",
            message="CRA business number is required before XML package generation.",
        )
        _required_str(
            issues,
            employer_registration,
            key="cra_payroll_program_account_number",
            path="employer_registration.cra_payroll_program_account_number",
            message="CRA payroll program account number is required before XML package generation.",
        )
        _required_str(
            issues,
            employer_registration,
            key="payroll_registration_country",
            path="employer_registration.payroll_registration_country",
            message="Payroll registration country is required before XML package generation.",
        )

    employer_summary = payload.get("employer_summary")
    if not isinstance(employer_summary, dict):
        issues.append(
            PayrollT4XmlValidationIssue(
                code="employer_summary_missing",
                message="Employer summary totals are required before XML package generation.",
                path="employer_summary",
            )
        )
    else:
        record_count = _required_int(
            issues,
            employer_summary,
            key="t4_record_count",
            path="employer_summary.t4_record_count",
            message="Employer summary T4 record count is required before XML package generation.",
        )
        if record_count is not None and record_count <= 0:
            issues.append(
                PayrollT4XmlValidationIssue(
                    code="t4_record_count_invalid",
                    message="Employer summary must include at least one T4 row before XML package generation.",
                    path="employer_summary.t4_record_count",
                )
            )

    t4_rows = payload.get("t4_rows")
    if not isinstance(t4_rows, list) or not t4_rows:
        issues.append(
            PayrollT4XmlValidationIssue(
                code="t4_rows_missing",
                message="At least one T4 row is required before XML package generation.",
                path="t4_rows",
            )
        )
        return issues

    for index, row in enumerate(t4_rows):
        path_prefix = f"t4_rows[{index}]"
        if not isinstance(row, dict):
            issues.append(
                PayrollT4XmlValidationIssue(
                    code="t4_row_invalid",
                    message="Each T4 row must be a JSON object before XML package generation.",
                    path=path_prefix,
                )
            )
            continue
        _required_str(
            issues,
            row,
            key="t4_id",
            path=f"{path_prefix}.t4_id",
            message="Each T4 row requires a t4_id before XML package generation.",
        )
        _required_str(
            issues,
            row,
            key="employee_legal_name",
            path=f"{path_prefix}.employee_legal_name",
            message="Each T4 row requires employee legal name before XML package generation.",
        )
        _required_str(
            issues,
            row,
            key="employee_sin",
            path=f"{path_prefix}.employee_sin",
            message="Each T4 row requires employee SIN before XML package generation.",
        )
        address = row.get("employee_address")
        if not isinstance(address, dict):
            issues.append(
                PayrollT4XmlValidationIssue(
                    code="employee_address_missing",
                    message="Each T4 row requires employee address before XML package generation.",
                    path=f"{path_prefix}.employee_address",
                )
            )
        else:
            for key in ("address_line_1", "city", "province", "postal_code", "country"):
                _required_str(
                    issues,
                    address,
                    key=key,
                    path=f"{path_prefix}.employee_address.{key}",
                    message=f"Each T4 row requires employee address field {key} before XML package generation.",
                )

    return issues


def _build_xml_bytes(payload: dict[str, Any]) -> bytes:
    employer_registration = payload["employer_registration"]
    employer_summary = payload["employer_summary"]
    t4_rows = payload["t4_rows"]
    blocking_issues = payload.get("blocking_issues", [])

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(
        f'<PayrollT4XmlPackage schemaId="{_text(XML_PACKAGE_SCHEMA_ID)}" '
        f'schemaVersion="{_text(XML_PACKAGE_SCHEMA_VERSION)}" '
        f'packageKind="{_text(XML_PACKAGE_ARTIFACT_KIND)}" '
        f'sourceSchemaId="{_text(payload.get("schema_id"))}" '
        f'sourceSchemaVersion="{_text(payload.get("schema_version"))}" '
        f'taxAuthority="{_text(payload.get("tax_authority"))}" '
        f'taxYear="{_text(payload.get("tax_year"))}">'
    )
    lines.append("  <EmployerRegistration>")
    for key, tag in (
        ("company_id", "CompanyId"),
        ("company_name", "CompanyName"),
        ("country", "Country"),
        ("province_or_state", "ProvinceOrState"),
        ("cra_business_number", "CraBusinessNumber"),
        ("cra_payroll_program_account_number", "CraPayrollProgramAccountNumber"),
        ("payroll_registration_country", "PayrollRegistrationCountry"),
    ):
        _append_tag(lines, "    ", tag, employer_registration.get(key))
    lines.append("  </EmployerRegistration>")

    lines.append("  <EmployerSummary>")
    for key, tag in (
        ("t4_record_count", "T4RecordCount"),
        ("employment_income_cents", "EmploymentIncomeCents"),
        ("cpp_contributions_cents", "CppContributionsCents"),
        ("ei_premiums_cents", "EiPremiumsCents"),
        ("income_tax_deducted_cents", "IncomeTaxDeductedCents"),
        ("other_deductions_cents", "OtherDeductionsCents"),
        ("delivered_count", "DeliveredCount"),
        ("employee_downloaded_count", "EmployeeDownloadedCount"),
        ("employee_acknowledged_count", "EmployeeAcknowledgedCount"),
    ):
        _append_tag(lines, "    ", tag, employer_summary.get(key))
    lines.append("  </EmployerSummary>")

    lines.append("  <T4Slips>")
    for row in t4_rows:
        lines.append(
            f'    <T4Slip t4Id="{_text(row.get("t4_id"))}" employeeId="{_text(row.get("employee_id"))}" '
            f'taxYear="{_text(row.get("tax_year"))}">'
        )
        lines.append("      <Employee>")
        for key, tag in (
            ("employee_display_name", "DisplayName"),
            ("employee_legal_name", "LegalName"),
            ("employee_sin", "Sin"),
        ):
            _append_tag(lines, "        ", tag, row.get(key))
        lines.append("        <Address>")
        address = row["employee_address"]
        for key, tag in (
            ("address_line_1", "AddressLine1"),
            ("city", "City"),
            ("province", "Province"),
            ("postal_code", "PostalCode"),
            ("country", "Country"),
        ):
            _append_tag(lines, "          ", tag, address.get(key))
        lines.append("        </Address>")
        lines.append("      </Employee>")
        lines.append("      <Amounts>")
        for key, tag in (
            ("employment_income_cents", "EmploymentIncomeCents"),
            ("cpp_contributions_cents", "CppContributionsCents"),
            ("ei_premiums_cents", "EiPremiumsCents"),
            ("income_tax_deducted_cents", "IncomeTaxDeductedCents"),
            ("other_deductions_cents", "OtherDeductionsCents"),
        ):
            _append_tag(lines, "        ", tag, row.get(key))
        lines.append("      </Amounts>")
        lines.append("      <Lifecycle>")
        for key, tag in (
            ("delivery_state", "DeliveryState"),
            ("artifact_state", "ArtifactState"),
            ("ready_for_filing", "ReadyForFiling"),
        ):
            _append_tag(lines, "        ", tag, row.get(key))
        lines.append("      </Lifecycle>")
        lines.append("    </T4Slip>")
    lines.append("  </T4Slips>")

    lines.append("  <BlockingIssues>")
    for issue in blocking_issues:
        lines.append(
            f'    <Issue code="{_text(issue.get("code"))}" scope="{_text(issue.get("scope"))}" '
            f'employeeId="{_text(issue.get("employee_id"))}" t4Id="{_text(issue.get("t4_id"))}">'
        )
        _append_tag(lines, "      ", "Message", issue.get("message"))
        lines.append("    </Issue>")
    lines.append("  </BlockingIssues>")
    lines.append("</PayrollT4XmlPackage>")
    return ("\n".join(lines) + "\n").encode("utf-8")


def prepare_t4_xml_package(
    *,
    db: Session,
    artifact_row: PayrollT4FilingArtifact,
    company_id: int,
    tax_year: int,
    actor_user_id: str | None,
) -> dict[str, Any]:
    payload = dict(artifact_row.prepared_payload_json or {})
    issues = _validate_canonical_filing_payload(payload)
    if issues:
        raise PayrollT4XmlValidationError(issues)

    xml_blob = _build_xml_bytes(payload)
    file_name = f"t4-filing-package-{int(tax_year)}.xml"
    previous_sha = None if artifact_row.xml_package_sha256 is None else str(artifact_row.xml_package_sha256)
    artifact = store_t4_filing_xml_package_blob(
        artifact_row,
        schema_id=XML_PACKAGE_SCHEMA_ID,
        schema_version=XML_PACKAGE_SCHEMA_VERSION,
        storage_key=build_db_backed_t4_filing_storage_key(
            company_id=int(company_id),
            tax_year=int(tax_year),
            file_name=file_name,
        ),
        file_name=file_name,
        content_type=XML_PACKAGE_CONTENT_TYPE,
        blob=xml_blob,
    )
    xml_hash = artifact.sha256

    generated_at = artifact_row.xml_generated_at
    generated_by_user_id = artifact_row.xml_generated_by_user_id
    audit_event_type: str | None = None
    if previous_sha is None:
        audit_event_type = PAYROLL_T4_XML_PACKAGE_GENERATED_EVENT
    elif previous_sha != xml_hash:
        audit_event_type = PAYROLL_T4_XML_PACKAGE_REGENERATED_EVENT

    if audit_event_type is not None:
        generated_at_dt = datetime.now(timezone.utc)
        artifact_row.xml_generated_at = generated_at_dt
        artifact_row.xml_generated_by_user_id = None if actor_user_id is None else str(actor_user_id)
        generated_at = artifact_row.xml_generated_at
        generated_by_user_id = artifact_row.xml_generated_by_user_id
        record_payroll_audit_event(
            db=db,
            company_id=int(company_id),
            payroll_run_id=None,
            event_type=audit_event_type,
            actor_user_id=actor_user_id,
            payload_json={
                "tax_year": int(tax_year),
                "actor_user_id": actor_user_id,
                "schema_id": XML_PACKAGE_SCHEMA_ID,
                "schema_version": XML_PACKAGE_SCHEMA_VERSION,
                "source_schema_id": payload.get("schema_id"),
                "source_schema_version": payload.get("schema_version"),
                "xml_hash": xml_hash,
                "timestamp": generated_at_dt.isoformat(),
            },
        )

    validation_result = validate_t4_xml_package(
        db=db,
        artifact_row=artifact_row,
        company_id=int(company_id),
        tax_year=int(tax_year),
        actor_user_id=actor_user_id,
    )

    return {
        "schema_id": XML_PACKAGE_SCHEMA_ID,
        "schema_version": XML_PACKAGE_SCHEMA_VERSION,
        "package_kind": XML_PACKAGE_ARTIFACT_KIND,
        "tax_year": int(tax_year),
        "source_schema_id": payload.get("schema_id"),
        "source_schema_version": payload.get("schema_version"),
        "file_name": artifact.file_name,
        "content_type": artifact.content_type,
        "byte_size": int(artifact.byte_size),
        "sha256": artifact.sha256,
        "storage_key": artifact.storage_key,
        "generated_at": None if generated_at is None else generated_at.isoformat(),
        "generated_by_user_id": generated_by_user_id,
        "validation": validation_result,
        "xml": artifact.blob.decode("utf-8"),
    }
