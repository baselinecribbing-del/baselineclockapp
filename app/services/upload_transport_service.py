import os
import re
import uuid
from dataclasses import dataclass
from urllib.parse import quote, urlparse


@dataclass(frozen=True)
class UploadPreparationResult:
    storage_key: str
    upload_url: str | None
    required_headers: dict[str, str]
    required_fields: dict[str, str]
    expires_at: str | None
    available: bool
    reason: str | None


def _sanitize_file_name(file_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(file_name).strip())
    return cleaned or "upload.bin"


def build_storage_key(*, prefix: str, company_id: int, context_id: str, file_name: str) -> str:
    safe_name = _sanitize_file_name(file_name)
    return f"{prefix}/company-{int(company_id)}/{context_id}/{uuid.uuid4()}-{safe_name}"


def prepare_upload(*, storage_key: str) -> UploadPreparationResult:
    base_url = (os.getenv("DOCUMENT_UPLOAD_TARGET_BASE_URL", "") or "").strip()
    if base_url:
        parsed = urlparse(base_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            upload_url = f"{base_url.rstrip('/')}/{quote(storage_key, safe='/')}"
            return UploadPreparationResult(
                storage_key=storage_key,
                upload_url=upload_url,
                required_headers={},
                required_fields={},
                expires_at=None,
                available=True,
                reason=None,
            )

    return UploadPreparationResult(
        storage_key=storage_key,
        upload_url=None,
        required_headers={},
        required_fields={},
        expires_at=None,
        available=False,
        reason="Upload target generation is not configured",
    )
