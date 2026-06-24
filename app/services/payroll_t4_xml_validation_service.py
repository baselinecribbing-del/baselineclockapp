from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from xml.etree import ElementTree

from sqlalchemy.orm import Session

from app.models.payroll_t4_filing_artifact import PayrollT4FilingArtifact
from app.services.payroll_audit_service import (
    PAYROLL_T4_XML_VALIDATION_FAILED_EVENT,
    PAYROLL_T4_XML_VALIDATION_PASSED_EVENT,
    record_payroll_audit_event,
)

INTERNAL_XML_VALIDATOR_ID = "frontier_internal_payroll_t4_xml_validator"
INTERNAL_XML_VALIDATOR_VERSION = "1.0"
INTERNAL_XML_VALIDATION_MODE = "INTERNAL_ONLY"


@dataclass(frozen=True)
class PayrollT4XmlValidationIssue:
    code: str
    message: str
    path: str
    section: str | None = None
    line_reference: str | None = None


@dataclass(frozen=True)
class PayrollT4XmlValidatorDefinition:
    validator_id: str
    validator_version: str
    validation_mode: str
    validate_document: Callable[[PayrollT4FilingArtifact, int], list[PayrollT4XmlValidationIssue]]


def _text_is_blank(value: str | None) -> bool:
    return str(value or "").strip() == ""


def _child_text(element: ElementTree.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None:
        return None
    return child.text


def _append_issue(
    issues: list[PayrollT4XmlValidationIssue],
    *,
    code: str,
    message: str,
    path: str,
    section: str | None = None,
    line_reference: str | None = None,
) -> None:
    issues.append(
        PayrollT4XmlValidationIssue(
            code=code,
            message=message,
            path=path,
            section=section,
            line_reference=line_reference,
        )
    )


def _serialize_issue(issue: PayrollT4XmlValidationIssue) -> dict[str, str | None]:
    return {
        "code": issue.code,
        "message": issue.message,
        "path": issue.path,
        "error_code": issue.code,
        "error_message": issue.message,
        "validation_section": issue.section,
        "validation_line_reference": issue.line_reference,
    }


def _validate_xml_document(
    *,
    artifact_row: PayrollT4FilingArtifact,
    tax_year: int,
) -> list[PayrollT4XmlValidationIssue]:
    issues: list[PayrollT4XmlValidationIssue] = []
    xml_blob = artifact_row.xml_package_blob
    if xml_blob is None:
        _append_issue(
            issues,
            code="xml_package_missing",
            message="Payroll T4 XML package blob is not available for internal validation.",
            path="xml",
            section="XML_DOCUMENT",
        )
        return issues

    try:
        root = ElementTree.fromstring(xml_blob)
    except ElementTree.ParseError as exc:
        _append_issue(
            issues,
            code="xml_not_well_formed",
            message=f"Payroll T4 XML package is not well formed: {exc}",
            path="xml",
            section="XML_DOCUMENT",
            line_reference=(
                f"line {exc.position[0]}, column {exc.position[1]}"
                if getattr(exc, "position", None) is not None
                else None
            ),
        )
        return issues

    if root.tag != "PayrollT4XmlPackage":
        _append_issue(
            issues,
            code="root_tag_invalid",
            message="Payroll T4 XML package root tag must be PayrollT4XmlPackage.",
            path="PayrollT4XmlPackage",
            section="ROOT",
        )
        return issues

    expected_root_attrs = {
        "schemaId": str(artifact_row.xml_package_schema_id or ""),
        "schemaVersion": str(artifact_row.xml_package_schema_version or ""),
        "taxYear": str(int(tax_year)),
    }
    for attr, expected in expected_root_attrs.items():
        actual = str(root.attrib.get(attr) or "")
        if actual != expected:
            _append_issue(
                issues,
                code=f"{attr}_mismatch",
                message=f"Payroll T4 XML package {attr} must match stored artifact metadata.",
                path=f"PayrollT4XmlPackage.@{attr}",
                section="ROOT",
            )

    employer_registration = root.find("EmployerRegistration")
    if employer_registration is None:
        _append_issue(
            issues,
            code="employer_registration_missing",
            message="Payroll T4 XML package must include EmployerRegistration.",
            path="PayrollT4XmlPackage.EmployerRegistration",
            section="EMPLOYER_REGISTRATION",
        )
    else:
        for tag in (
            "CompanyId",
            "CompanyName",
            "Country",
            "ProvinceOrState",
            "CraBusinessNumber",
            "CraPayrollProgramAccountNumber",
            "PayrollRegistrationCountry",
        ):
            if _text_is_blank(_child_text(employer_registration, tag)):
                _append_issue(
                    issues,
                    code=f"{tag}_missing",
                    message=f"Payroll T4 XML package EmployerRegistration field {tag} is required.",
                    path=f"PayrollT4XmlPackage.EmployerRegistration.{tag}",
                    section="EMPLOYER_REGISTRATION",
                )

    summary = root.find("EmployerSummary")
    t4_slips = root.findall("./T4Slips/T4Slip")
    if summary is None:
        _append_issue(
            issues,
            code="employer_summary_missing",
            message="Payroll T4 XML package must include EmployerSummary.",
            path="PayrollT4XmlPackage.EmployerSummary",
            section="EMPLOYER_SUMMARY",
        )
    else:
        record_count_text = _child_text(summary, "T4RecordCount")
        try:
            record_count = int(str(record_count_text))
        except (TypeError, ValueError):
            _append_issue(
                issues,
                code="t4_record_count_invalid",
                message="Payroll T4 XML package EmployerSummary T4RecordCount must be an integer.",
                path="PayrollT4XmlPackage.EmployerSummary.T4RecordCount",
                section="EMPLOYER_SUMMARY",
            )
        else:
            if record_count != len(t4_slips):
                _append_issue(
                    issues,
                    code="t4_record_count_mismatch",
                    message="Payroll T4 XML package EmployerSummary T4RecordCount must match slip count.",
                    path="PayrollT4XmlPackage.EmployerSummary.T4RecordCount",
                    section="EMPLOYER_SUMMARY",
                )

    for index, slip in enumerate(t4_slips):
        path_prefix = f"PayrollT4XmlPackage.T4Slips.T4Slip[{index}]"
        if _text_is_blank(slip.attrib.get("t4Id")):
            _append_issue(
                issues,
                code="t4_id_missing",
                message="Each Payroll T4 XML slip must include a t4Id attribute.",
                path=f"{path_prefix}.@t4Id",
                section="T4_SLIP",
            )

        employee = slip.find("Employee")
        if employee is None:
            _append_issue(
                issues,
                code="employee_missing",
                message="Each Payroll T4 XML slip must include Employee details.",
                path=f"{path_prefix}.Employee",
                section="T4_SLIP",
            )
            continue

        for tag in ("LegalName", "Sin"):
            if _text_is_blank(_child_text(employee, tag)):
                _append_issue(
                    issues,
                    code=f"{tag.lower()}_missing",
                    message=f"Each Payroll T4 XML slip must include Employee {tag}.",
                    path=f"{path_prefix}.Employee.{tag}",
                    section="T4_SLIP",
                )

        address = employee.find("Address")
        if address is None:
            _append_issue(
                issues,
                code="address_missing",
                message="Each Payroll T4 XML slip must include Employee Address.",
                path=f"{path_prefix}.Employee.Address",
                section="T4_SLIP",
            )
        else:
            for tag in ("AddressLine1", "City", "Province", "PostalCode", "Country"):
                if _text_is_blank(_child_text(address, tag)):
                    _append_issue(
                        issues,
                        code=f"{tag.lower()}_missing",
                        message=f"Each Payroll T4 XML slip must include Employee Address {tag}.",
                        path=f"{path_prefix}.Employee.Address.{tag}",
                        section="T4_SLIP",
                    )

    prepared_payload = dict(artifact_row.prepared_payload_json or {})
    prepared_rows = list(prepared_payload.get("t4_rows") or [])
    if prepared_rows and len(prepared_rows) != len(t4_slips):
        _append_issue(
            issues,
            code="prepared_payload_row_count_mismatch",
            message="Payroll T4 XML package slip count must match the canonical filing artifact row count.",
            path="PayrollT4XmlPackage.T4Slips",
            section="CANONICAL_FILING_PAYLOAD",
        )

    return issues


INTERNAL_PAYROLL_T4_XML_VALIDATOR = PayrollT4XmlValidatorDefinition(
    validator_id=INTERNAL_XML_VALIDATOR_ID,
    validator_version=INTERNAL_XML_VALIDATOR_VERSION,
    validation_mode=INTERNAL_XML_VALIDATION_MODE,
    validate_document=lambda artifact_row, tax_year: _validate_xml_document(
        artifact_row=artifact_row,
        tax_year=tax_year,
    ),
)

SUPPORTED_PAYROLL_T4_XML_VALIDATORS: dict[tuple[str, str], PayrollT4XmlValidatorDefinition] = {
    (
        INTERNAL_PAYROLL_T4_XML_VALIDATOR.validator_id,
        INTERNAL_PAYROLL_T4_XML_VALIDATOR.validator_version,
    ): INTERNAL_PAYROLL_T4_XML_VALIDATOR,
}


def get_active_payroll_t4_xml_validator() -> PayrollT4XmlValidatorDefinition:
    return INTERNAL_PAYROLL_T4_XML_VALIDATOR


def get_supported_payroll_t4_xml_validator(
    *,
    validator_id: str,
    validator_version: str,
) -> PayrollT4XmlValidatorDefinition | None:
    return SUPPORTED_PAYROLL_T4_XML_VALIDATORS.get((str(validator_id), str(validator_version)))


def _serialize_validation_result(
    *,
    validator: PayrollT4XmlValidatorDefinition,
    artifact_row: PayrollT4FilingArtifact,
    tax_year: int,
    issues: list[PayrollT4XmlValidationIssue],
) -> dict[str, Any]:
    status = "VALID" if not issues else "INVALID"
    return {
        "validator_id": validator.validator_id,
        "validator_version": validator.validator_version,
        "validation_mode": validator.validation_mode,
        "status": status,
        "tax_year": int(tax_year),
        "xml_package_sha256": str(artifact_row.xml_package_sha256),
        "target_schema_id": artifact_row.xml_package_schema_id,
        "target_schema_version": artifact_row.xml_package_schema_version,
        "source_schema_id": dict(artifact_row.prepared_payload_json or {}).get("schema_id"),
        "source_schema_version": dict(artifact_row.prepared_payload_json or {}).get("schema_version"),
        "issue_count": len(issues),
        "issues": [
            _serialize_issue(issue)
            for issue in issues
        ],
    }


def get_stored_t4_xml_validation_result(artifact_row: PayrollT4FilingArtifact) -> dict[str, Any] | None:
    if (
        artifact_row.xml_validation_validator_id is None
        or artifact_row.xml_validation_validator_version is None
        or artifact_row.xml_validation_mode is None
        or artifact_row.xml_validation_status is None
        or artifact_row.xml_validation_result_json is None
        or artifact_row.xml_validation_xml_sha256 is None
        or artifact_row.xml_validated_at is None
    ):
        return None
    return {
        "validator_id": str(artifact_row.xml_validation_validator_id),
        "validator_version": str(artifact_row.xml_validation_validator_version),
        "validation_mode": str(artifact_row.xml_validation_mode),
        "status": str(artifact_row.xml_validation_status),
        "xml_package_sha256": str(artifact_row.xml_validation_xml_sha256),
        "validated_at": (
            artifact_row.xml_validated_at.replace(tzinfo=timezone.utc).isoformat()
            if artifact_row.xml_validated_at.tzinfo is None
            else artifact_row.xml_validated_at.astimezone(timezone.utc).isoformat()
        ),
        "validated_by_user_id": artifact_row.xml_validated_by_user_id,
        "result": dict(artifact_row.xml_validation_result_json or {}),
    }


def validate_t4_xml_package(
    *,
    db: Session,
    artifact_row: PayrollT4FilingArtifact,
    company_id: int,
    tax_year: int,
    actor_user_id: str | None,
) -> dict[str, Any]:
    validator = get_active_payroll_t4_xml_validator()
    current_hash = str(artifact_row.xml_package_sha256 or "").strip()
    existing = get_stored_t4_xml_validation_result(artifact_row)
    if (
        existing is not None
        and existing["validator_id"] == validator.validator_id
        and existing["validator_version"] == validator.validator_version
        and existing["xml_package_sha256"] == current_hash
    ):
        return existing

    issues = validator.validate_document(artifact_row, int(tax_year))
    result = _serialize_validation_result(
        validator=validator,
        artifact_row=artifact_row,
        tax_year=int(tax_year),
        issues=issues,
    )

    validated_at = datetime.now(timezone.utc)
    artifact_row.xml_validation_validator_id = validator.validator_id
    artifact_row.xml_validation_validator_version = validator.validator_version
    artifact_row.xml_validation_mode = validator.validation_mode
    artifact_row.xml_validation_status = str(result["status"])
    artifact_row.xml_validation_result_json = result
    artifact_row.xml_validation_xml_sha256 = current_hash
    artifact_row.xml_validated_at = validated_at
    artifact_row.xml_validated_by_user_id = None if actor_user_id is None else str(actor_user_id)
    db.flush()

    event_type = (
        PAYROLL_T4_XML_VALIDATION_PASSED_EVENT
        if result["status"] == "VALID"
        else PAYROLL_T4_XML_VALIDATION_FAILED_EVENT
    )
    record_payroll_audit_event(
        db=db,
        company_id=int(company_id),
        payroll_run_id=None,
        event_type=event_type,
        actor_user_id=actor_user_id,
        payload_json={
            "tax_year": int(tax_year),
            "validator_id": validator.validator_id,
            "validator_version": validator.validator_version,
            "validation_mode": validator.validation_mode,
            "status": result["status"],
            "xml_package_sha256": current_hash,
            "issue_count": int(result["issue_count"]),
            "issue_codes": [issue["code"] for issue in result["issues"]],
            "validated_at": validated_at.isoformat(),
        },
    )
    return {
        "validator_id": validator.validator_id,
        "validator_version": validator.validator_version,
        "validation_mode": validator.validation_mode,
        "status": str(result["status"]),
        "xml_package_sha256": current_hash,
        "validated_at": validated_at.isoformat(),
        "validated_by_user_id": artifact_row.xml_validated_by_user_id,
        "result": result,
    }
