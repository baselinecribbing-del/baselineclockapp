import mimetypes
from dataclasses import dataclass
from urllib.parse import urlparse

from app.models.job_document import JobDocument


@dataclass(frozen=True)
class DocumentAccessResult:
    access_type: str
    file_url: str | None
    download_url: str | None
    file_name: str
    content_type: str | None
    expires_at: str | None
    available: bool
    reason: str | None


def resolve_job_document_access(document: JobDocument) -> DocumentAccessResult:
    storage_key = (document.storage_key or "").strip()
    content_type = mimetypes.guess_type(document.file_name)[0]

    if not storage_key:
        return DocumentAccessResult(
            access_type="unavailable",
            file_url=None,
            download_url=None,
            file_name=str(document.file_name),
            content_type=content_type,
            expires_at=None,
            available=False,
            reason="No storage reference is available for this document",
        )

    parsed = urlparse(storage_key)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return DocumentAccessResult(
            access_type="direct_url",
            file_url=storage_key,
            download_url=None,
            file_name=str(document.file_name),
            content_type=content_type,
            expires_at=None,
            available=True,
            reason=None,
        )

    return DocumentAccessResult(
        access_type="unavailable",
        file_url=None,
        download_url=None,
        file_name=str(document.file_name),
        content_type=content_type,
        expires_at=None,
        available=False,
        reason="Storage reference cannot be resolved into a usable file URL",
    )
