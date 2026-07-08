from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.models.payroll_t4_filing_artifact import PayrollT4FilingArtifact


@dataclass(frozen=True)
class T4FilingArtifactBlob:
    storage_key: str
    file_name: str
    content_type: str
    blob: bytes
    byte_size: int
    sha256: str


def _materialize_artifact_blob(
    *,
    storage_key: str,
    file_name: str,
    content_type: str,
    blob: bytes,
) -> T4FilingArtifactBlob:
    materialized_blob = bytes(blob)
    return T4FilingArtifactBlob(
        storage_key=str(storage_key),
        file_name=str(file_name),
        content_type=str(content_type),
        blob=materialized_blob,
        byte_size=len(materialized_blob),
        sha256=hashlib.sha256(materialized_blob).hexdigest(),
    )


def build_db_backed_t4_filing_storage_key(*, company_id: int, tax_year: int, file_name: str) -> str:
    return f"db://payroll_t4_filing_artifacts/company-{int(company_id)}/{int(tax_year)}/{file_name}"


def store_t4_filing_artifact_blob(
    artifact_row: PayrollT4FilingArtifact,
    *,
    storage_key: str,
    file_name: str,
    content_type: str,
    blob: bytes,
) -> T4FilingArtifactBlob:
    artifact = _materialize_artifact_blob(
        storage_key=storage_key,
        file_name=file_name,
        content_type=content_type,
        blob=blob,
    )
    artifact_row.artifact_storage_key = artifact.storage_key
    artifact_row.artifact_file_name = artifact.file_name
    artifact_row.artifact_content_type = artifact.content_type
    artifact_row.artifact_blob = artifact.blob
    artifact_row.artifact_byte_size = artifact.byte_size
    artifact_row.artifact_sha256 = artifact.sha256
    return artifact


def clear_t4_filing_xml_package_blob(artifact_row: PayrollT4FilingArtifact) -> None:
    artifact_row.xml_package_schema_id = None
    artifact_row.xml_package_schema_version = None
    artifact_row.xml_package_storage_key = None
    artifact_row.xml_package_file_name = None
    artifact_row.xml_package_content_type = None
    artifact_row.xml_package_blob = None
    artifact_row.xml_package_byte_size = None
    artifact_row.xml_package_sha256 = None
    artifact_row.xml_generated_at = None
    artifact_row.xml_generated_by_user_id = None
    artifact_row.xml_validation_validator_id = None
    artifact_row.xml_validation_validator_version = None
    artifact_row.xml_validation_mode = None
    artifact_row.xml_validation_status = None
    artifact_row.xml_validation_result_json = None
    artifact_row.xml_validation_xml_sha256 = None
    artifact_row.xml_validated_at = None
    artifact_row.xml_validated_by_user_id = None


def clear_t4_filing_xml_validation_state(artifact_row: PayrollT4FilingArtifact) -> None:
    artifact_row.xml_validation_validator_id = None
    artifact_row.xml_validation_validator_version = None
    artifact_row.xml_validation_mode = None
    artifact_row.xml_validation_status = None
    artifact_row.xml_validation_result_json = None
    artifact_row.xml_validation_xml_sha256 = None
    artifact_row.xml_validated_at = None
    artifact_row.xml_validated_by_user_id = None


def store_t4_filing_xml_package_blob(
    artifact_row: PayrollT4FilingArtifact,
    *,
    schema_id: str,
    schema_version: str,
    storage_key: str,
    file_name: str,
    content_type: str,
    blob: bytes,
) -> T4FilingArtifactBlob:
    artifact = _materialize_artifact_blob(
        storage_key=storage_key,
        file_name=file_name,
        content_type=content_type,
        blob=blob,
    )
    artifact_row.xml_package_schema_id = str(schema_id)
    artifact_row.xml_package_schema_version = str(schema_version)
    artifact_row.xml_package_storage_key = artifact.storage_key
    artifact_row.xml_package_file_name = artifact.file_name
    artifact_row.xml_package_content_type = artifact.content_type
    artifact_row.xml_package_blob = artifact.blob
    artifact_row.xml_package_byte_size = artifact.byte_size
    artifact_row.xml_package_sha256 = artifact.sha256
    clear_t4_filing_xml_validation_state(artifact_row)
    return artifact
