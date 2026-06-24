from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class PayrollT4FilingArtifact(Base):
    __tablename__ = "payroll_t4_filing_artifacts"

    __table_args__ = (
        UniqueConstraint("company_id", "tax_year", name="uq_payroll_t4_filing_artifacts_company_tax_year"),
        CheckConstraint("tax_year >= 2000", name="ck_payroll_t4_filing_artifacts_tax_year_min"),
        CheckConstraint(
            "filing_status IN ('FILING_ARTIFACT_READY', 'FILING_ARTIFACT_BLOCKED')",
            name="ck_payroll_t4_filing_artifacts_status_valid",
        ),
        CheckConstraint(
            "artifact_byte_size >= 0",
            name="ck_payroll_t4_filing_artifacts_byte_size_nonnegative",
        ),
        CheckConstraint(
            "xml_package_byte_size IS NULL OR xml_package_byte_size >= 0",
            name="ck_payroll_t4_filing_artifacts_xml_byte_size_nonnegative",
        ),
        CheckConstraint(
            "artifact_storage_key IS NOT NULL AND artifact_file_name IS NOT NULL AND artifact_content_type IS NOT NULL "
            "AND artifact_blob IS NOT NULL AND artifact_byte_size IS NOT NULL AND artifact_sha256 IS NOT NULL",
            name="ck_payroll_t4_filing_artifacts_artifact_complete",
        ),
        CheckConstraint(
            "("
            "xml_package_schema_id IS NULL AND xml_package_schema_version IS NULL "
            "AND xml_package_storage_key IS NULL AND xml_package_file_name IS NULL "
            "AND xml_package_content_type IS NULL AND xml_package_blob IS NULL "
            "AND xml_package_byte_size IS NULL AND xml_package_sha256 IS NULL "
            "AND xml_generated_at IS NULL AND xml_generated_by_user_id IS NULL"
            ") OR ("
            "xml_package_schema_id IS NOT NULL AND xml_package_schema_version IS NOT NULL "
            "AND xml_package_storage_key IS NOT NULL AND xml_package_file_name IS NOT NULL "
            "AND xml_package_content_type IS NOT NULL AND xml_package_blob IS NOT NULL "
            "AND xml_package_byte_size IS NOT NULL AND xml_package_sha256 IS NOT NULL "
            "AND xml_generated_at IS NOT NULL AND xml_generated_by_user_id IS NOT NULL"
            ")",
            name="ck_payroll_t4_filing_artifacts_xml_package_complete",
        ),
        CheckConstraint(
            "("
            "xml_validation_validator_id IS NULL AND xml_validation_validator_version IS NULL "
            "AND xml_validation_mode IS NULL AND xml_validation_status IS NULL "
            "AND xml_validation_result_json IS NULL AND xml_validation_xml_sha256 IS NULL "
            "AND xml_validated_at IS NULL AND xml_validated_by_user_id IS NULL"
            ") OR ("
            "xml_validation_validator_id IS NOT NULL AND xml_validation_validator_version IS NOT NULL "
            "AND xml_validation_mode IS NOT NULL AND xml_validation_status IS NOT NULL "
            "AND xml_validation_result_json IS NOT NULL AND xml_validation_xml_sha256 IS NOT NULL "
            "AND xml_validated_at IS NOT NULL"
            ")",
            name="ck_payroll_t4_filing_artifacts_xml_validation_complete",
        ),
        CheckConstraint(
            "xml_validation_mode IS NULL OR xml_validation_mode IN ('INTERNAL_ONLY')",
            name="ck_payroll_t4_filing_artifacts_xml_validation_mode_valid",
        ),
        CheckConstraint(
            "xml_validation_status IS NULL OR xml_validation_status IN ('VALID', 'INVALID')",
            name="ck_payroll_t4_filing_artifacts_xml_validation_status_valid",
        ),
    )

    filing_artifact_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    tax_year = Column(Integer, nullable=False, index=True)
    filing_status = Column(String, nullable=False, index=True)
    prepared_payload_json = Column(JSONB(none_as_null=True), nullable=False)
    artifact_storage_key = Column(String, nullable=False)
    artifact_file_name = Column(String, nullable=False)
    artifact_content_type = Column(String, nullable=False)
    artifact_blob = Column(LargeBinary, nullable=False)
    artifact_byte_size = Column(Integer, nullable=False)
    artifact_sha256 = Column(String, nullable=False)
    xml_package_schema_id = Column(String, nullable=True)
    xml_package_schema_version = Column(String, nullable=True)
    xml_package_storage_key = Column(String, nullable=True)
    xml_package_file_name = Column(String, nullable=True)
    xml_package_content_type = Column(String, nullable=True)
    xml_package_blob = Column(LargeBinary, nullable=True)
    xml_package_byte_size = Column(Integer, nullable=True)
    xml_package_sha256 = Column(String, nullable=True)
    xml_generated_at = Column(DateTime(timezone=True), nullable=True)
    xml_generated_by_user_id = Column(String, nullable=True)
    xml_validation_validator_id = Column(String, nullable=True)
    xml_validation_validator_version = Column(String, nullable=True)
    xml_validation_mode = Column(String, nullable=True)
    xml_validation_status = Column(String, nullable=True)
    xml_validation_result_json = Column(JSONB(none_as_null=True), nullable=True)
    xml_validation_xml_sha256 = Column(String, nullable=True)
    xml_validated_at = Column(DateTime(timezone=True), nullable=True)
    xml_validated_by_user_id = Column(String, nullable=True)
    prepared_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    prepared_by_user_id = Column(String, nullable=True)
