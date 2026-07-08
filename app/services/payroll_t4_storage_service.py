from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.models.payroll_t4 import PayrollT4


@dataclass(frozen=True)
class T4SlipArtifact:
    storage_key: str
    file_name: str
    content_type: str
    blob: bytes
    byte_size: int
    sha256: str


def build_db_backed_t4_storage_key(*, company_id: int, t4_id: str, file_name: str) -> str:
    return f"db://payroll_t4s/company-{int(company_id)}/{str(t4_id)}/{file_name}"


def store_t4_slip_artifact(
    payroll_t4: PayrollT4,
    *,
    storage_key: str,
    file_name: str,
    content_type: str,
    blob: bytes,
) -> T4SlipArtifact:
    materialized_blob = bytes(blob)
    artifact = T4SlipArtifact(
        storage_key=str(storage_key),
        file_name=str(file_name),
        content_type=str(content_type),
        blob=materialized_blob,
        byte_size=len(materialized_blob),
        sha256=hashlib.sha256(materialized_blob).hexdigest(),
    )
    payroll_t4.slip_storage_key = artifact.storage_key
    payroll_t4.slip_file_name = artifact.file_name
    payroll_t4.slip_content_type = artifact.content_type
    payroll_t4.slip_blob = artifact.blob
    payroll_t4.slip_byte_size = artifact.byte_size
    payroll_t4.slip_sha256 = artifact.sha256
    return artifact


def load_t4_slip_artifact(payroll_t4: PayrollT4) -> T4SlipArtifact | None:
    if (
        payroll_t4.slip_storage_key is None
        or payroll_t4.slip_file_name is None
        or payroll_t4.slip_content_type is None
        or payroll_t4.slip_blob is None
        or payroll_t4.slip_byte_size is None
        or payroll_t4.slip_sha256 is None
    ):
        return None
    return T4SlipArtifact(
        storage_key=str(payroll_t4.slip_storage_key),
        file_name=str(payroll_t4.slip_file_name),
        content_type=str(payroll_t4.slip_content_type),
        blob=bytes(payroll_t4.slip_blob),
        byte_size=int(payroll_t4.slip_byte_size),
        sha256=str(payroll_t4.slip_sha256),
    )


def clear_t4_slip_artifact(payroll_t4: PayrollT4) -> None:
    payroll_t4.slip_storage_key = None
    payroll_t4.slip_file_name = None
    payroll_t4.slip_content_type = None
    payroll_t4.slip_blob = None
    payroll_t4.slip_byte_size = None
    payroll_t4.slip_sha256 = None
