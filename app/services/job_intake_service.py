from __future__ import annotations

import re
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.email_ingestion_event import EmailIngestionEvent
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.job_document import JobDocument
from app.models.job_start_intake import JobStartIntake
from app.services.job_status_service import record_initial_job_status

NEW_START_RECEIVED_NOTIFICATION_READY = "NEW_START_RECEIVED_NOTIFICATION_READY"

_DOCUMENT_TYPE_BLUEPRINT = "BLUEPRINT"
_DOCUMENT_TYPE_GRADE_SLIP = "GRADE_SLIP"
_DOCUMENT_TYPE_SITE_PLAN = "SITE_PLAN"
_DOCUMENT_TYPE_STAKE_DATE = "STAKE_DATE"
_DOCUMENT_TYPE_OTHER = "OTHER"
_PROMOTABLE_JOB_DOCUMENT_TYPES = (
    _DOCUMENT_TYPE_BLUEPRINT,
    _DOCUMENT_TYPE_GRADE_SLIP,
    _DOCUMENT_TYPE_SITE_PLAN,
)

_DATE_PATTERNS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
)


@dataclass(frozen=True)
class IntakeAttachmentPayload:
    file_name: str
    parsed_text: str | None = None
    storage_key: str | None = None
    content_type: str | None = None


@dataclass(frozen=True)
class ParsedNewStartMetadata:
    builder_name: str | None
    project_address: str | None
    lot_number: str | None
    block_number: str | None
    stake_date: date | None
    notes: list[str]


@dataclass(frozen=True)
class IntakePromotionResult:
    intake: JobStartIntake
    job: Job


@dataclass(frozen=True)
class BuilderEmailIngestionResult:
    event: EmailIngestionEvent
    intake: JobStartIntake
    documents: list[JobDocument]
    event_hash: str
    event_emitted: bool
    idempotent_replay: bool


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _normalize_key(value: str | None) -> str:
    return _normalize_text(value).lower()


def _title_from_sender(sender_email: str | None) -> str | None:
    if not sender_email or "@" not in sender_email:
        return None
    domain = sender_email.split("@", 1)[1].strip().lower()
    labels = [label for label in domain.split(".") if label and label not in {"com", "ca", "net", "org"}]
    if not labels:
        return None
    return " ".join(part.capitalize() for part in labels[:2])


def _find_labeled_value(text: str, labels: tuple[str, ...]) -> str | None:
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for label in labels:
            lowered = line.lower()
            label_lower = label.lower()
            for separator in (":", "-"):
                prefix = f"{label_lower}{separator}"
                if lowered.startswith(prefix):
                    value = line[len(prefix):].strip()
                    if value:
                        return _normalize_text(value)

    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:\-]\s*(.+?)(?=(?:\s+[A-Za-z][A-Za-z /#&]+[:\-])|$)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _normalize_text(match.group(1))
    return None


def _parse_stake_date(text: str) -> date | None:
    keyword_match = re.search(
        r"stake\s*date\s*[:\-]?\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    candidate = None if keyword_match is None else keyword_match.group(1).strip()

    if candidate is None:
        return None

    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    return None


def _extract_lot_block(text: str) -> tuple[str | None, str | None]:
    lot = _find_labeled_value(text, ("lot", "lot number"))
    block = _find_labeled_value(text, ("block", "block number"))

    combined = re.search(r"\blot\s+([A-Za-z0-9-]+)\s+block\s+([A-Za-z0-9-]+)\b", text, flags=re.IGNORECASE)
    if combined:
        lot = lot or combined.group(1)
        block = block or combined.group(2)

    return lot, block


def _classify_document(file_name: str, parsed_text: str | None) -> str:
    haystack = _normalize_key(f"{file_name}\n{parsed_text or ''}")
    if "blueprint" in haystack or "floor plan" in haystack or "floorplan" in haystack:
        return _DOCUMENT_TYPE_BLUEPRINT
    if "grade slip" in haystack:
        return _DOCUMENT_TYPE_GRADE_SLIP
    if "site plan" in haystack:
        return _DOCUMENT_TYPE_SITE_PLAN
    if "stake date" in haystack or "stakedate" in haystack:
        return _DOCUMENT_TYPE_STAKE_DATE
    return _DOCUMENT_TYPE_OTHER


def _build_builder_email_event_hash(
    *,
    company_id: int,
    source: str,
    from_email: str,
    subject: str,
    received_at: datetime | None,
    body_text: str | None,
    attachments: list[IntakeAttachmentPayload],
) -> str:
    normalized_attachments = [
        {
            "filename": _normalize_text(attachment.file_name),
            "storage_key": _normalize_text(attachment.storage_key),
            "content_type": _normalize_text(attachment.content_type),
        }
        for attachment in attachments
    ]
    normalized_attachments.sort(
        key=lambda item: (item["filename"], item["storage_key"], item["content_type"])
    )
    payload = {
        "company_id": int(company_id),
        "source": _normalize_key(source),
        "from_email": _normalize_key(from_email),
        "subject": _normalize_text(subject),
        "received_at": None if received_at is None else received_at.isoformat(),
        "body_text": _normalize_text(body_text),
        "attachments": normalized_attachments,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _extract_metadata(event: EmailIngestionEvent, parsed_text: str, attachments: list[IntakeAttachmentPayload]) -> ParsedNewStartMetadata:
    raw = event.raw_metadata or {}
    combined_text = "\n".join(
        [event.subject or "", parsed_text, *(attachment.parsed_text or "" for attachment in attachments)]
    )

    builder_name = _normalize_text(raw.get("builder_name")) or _find_labeled_value(
        combined_text,
        ("builder", "builder name"),
    )
    if not builder_name:
        builder_name = _title_from_sender(event.sender_email)

    project_address = _normalize_text(raw.get("project_address")) or _find_labeled_value(
        combined_text,
        ("project address", "site address", "address"),
    )

    lot_number = _normalize_text(raw.get("lot_number"))
    block_number = _normalize_text(raw.get("block_number"))
    if not lot_number or not block_number:
        parsed_lot, parsed_block = _extract_lot_block(combined_text)
        lot_number = lot_number or parsed_lot
        block_number = block_number or parsed_block

    stake_date = None
    raw_stake_date = raw.get("stake_date")
    if raw_stake_date:
        try:
            stake_date = date.fromisoformat(str(raw_stake_date))
        except ValueError:
            stake_date = None
    if stake_date is None:
        stake_date = _parse_stake_date(combined_text)

    notes: list[str] = []
    if stake_date is None:
        notes.append("Missing stake date")
    if not project_address:
        notes.append("Project address not confidently extracted")

    return ParsedNewStartMetadata(
        builder_name=builder_name,
        project_address=project_address,
        lot_number=lot_number,
        block_number=block_number,
        stake_date=stake_date,
        notes=notes,
    )


def _find_duplicate(
    *,
    db: Session,
    company_id: int,
    builder_name: str | None,
    project_address: str | None,
    stake_date: date | None,
) -> JobStartIntake | None:
    if not project_address or stake_date is None:
        return None

    candidates = (
        db.query(JobStartIntake)
        .filter(JobStartIntake.company_id == int(company_id))
        .filter(JobStartIntake.project_address.isnot(None))
        .filter(JobStartIntake.stake_date == stake_date)
        .order_by(JobStartIntake.created_at.asc(), JobStartIntake.job_start_intake_id.asc())
        .all()
    )
    normalized_builder = _normalize_key(builder_name)
    normalized_address = _normalize_key(project_address)

    for row in candidates:
        if _normalize_key(row.project_address) != normalized_address:
            continue
        existing_builder = _normalize_key(row.builder_name)
        if normalized_builder and existing_builder and existing_builder != normalized_builder:
            continue
        return row
    return None


def _serialize_attachment_flags(document_types: list[str]) -> dict[str, bool]:
    values = set(document_types)
    return {
        "has_blueprint": _DOCUMENT_TYPE_BLUEPRINT in values,
        "has_grade_slip": _DOCUMENT_TYPE_GRADE_SLIP in values,
        "has_site_plan": _DOCUMENT_TYPE_SITE_PLAN in values,
        "has_stake_date_document": _DOCUMENT_TYPE_STAKE_DATE in values,
    }


def _build_job_name(intake: JobStartIntake) -> str:
    if intake.project_address:
        return str(intake.project_address)
    if intake.builder_name and intake.lot_number and intake.block_number:
        return f"{intake.builder_name} Lot {intake.lot_number} Block {intake.block_number}"
    if intake.builder_name:
        return f"{intake.builder_name} New Start"
    return f"Intake {intake.job_start_intake_id}"


def _link_intake_documents_to_job(*, db: Session, company_id: int, intake_id: str, job_id: int) -> None:
    docs = (
        db.query(JobDocument)
        .filter(JobDocument.company_id == int(company_id))
        .filter(JobDocument.job_start_intake_id == str(intake_id))
        .filter(JobDocument.document_type.in_(_PROMOTABLE_JOB_DOCUMENT_TYPES))
        .all()
    )
    for doc in docs:
        doc.job_id = int(job_id)
        db.add(doc)


def create_job_start_intake_from_email(
    *,
    db: Session,
    company_id: int,
    email_ingestion_event_id: str,
    parsed_text: str | None,
    attachments: list[IntakeAttachmentPayload],
) -> JobStartIntake:
    event = (
        db.query(EmailIngestionEvent)
        .filter(EmailIngestionEvent.company_id == int(company_id))
        .filter(EmailIngestionEvent.email_ingestion_event_id == str(email_ingestion_event_id))
        .one_or_none()
    )
    if event is None:
        raise ValueError("Email ingestion event not found")

    existing = (
        db.query(JobStartIntake)
        .filter(JobStartIntake.company_id == int(company_id))
        .filter(JobStartIntake.email_ingestion_event_id == str(email_ingestion_event_id))
        .one_or_none()
    )
    if existing is not None:
        return existing

    parsed_text_value = str(parsed_text or "")
    metadata = _extract_metadata(event, parsed_text_value, attachments)

    document_rows: list[tuple[IntakeAttachmentPayload, str]] = []
    document_types: list[str] = []
    for attachment in attachments:
        document_type = _classify_document(attachment.file_name, attachment.parsed_text)
        document_types.append(document_type)
        document_rows.append((attachment, document_type))

    flags = _serialize_attachment_flags(document_types)
    duplicate = _find_duplicate(
        db=db,
        company_id=int(company_id),
        builder_name=metadata.builder_name,
        project_address=metadata.project_address,
        stake_date=metadata.stake_date,
    )

    intake_status = "QUEUED"
    if metadata.stake_date is None:
        intake_status = "FLAGGED"
    elif duplicate is not None:
        intake_status = "DUPLICATE"

    notes = list(metadata.notes)
    if duplicate is not None:
        notes.append(f"Duplicate of intake {duplicate.job_start_intake_id}")

    intake = JobStartIntake(
        company_id=int(company_id),
        email_ingestion_event_id=str(event.email_ingestion_event_id),
        duplicate_of_job_start_intake_id=None if duplicate is None else str(duplicate.job_start_intake_id),
        builder_name=metadata.builder_name,
        source_email=str(event.sender_email),
        project_address=metadata.project_address,
        lot_number=metadata.lot_number,
        block_number=metadata.block_number,
        stake_date=metadata.stake_date,
        queue_trigger_date=metadata.stake_date,
        intake_status=intake_status,
        parse_notes=" | ".join(notes) if notes else None,
        **flags,
    )
    db.add(intake)
    db.flush()

    for attachment, document_type in document_rows:
        db.add(
            JobDocument(
                company_id=int(company_id),
                job_start_intake_id=str(intake.job_start_intake_id),
                email_ingestion_event_id=str(event.email_ingestion_event_id),
                document_type=document_type,
                file_name=str(attachment.file_name),
                storage_key=attachment.storage_key,
                parsed_text=attachment.parsed_text,
            )
        )

    event.parse_status = "PARSED"
    event.parse_notes = intake.parse_notes
    event.raw_metadata = {
        **(event.raw_metadata or {}),
        "job_start_intake": {
            "builder_name": metadata.builder_name,
            "project_address": metadata.project_address,
            "lot_number": metadata.lot_number,
            "block_number": metadata.block_number,
            "stake_date": None if metadata.stake_date is None else metadata.stake_date.isoformat(),
            "queue_trigger_date": None if metadata.stake_date is None else metadata.stake_date.isoformat(),
            "intake_status": intake_status,
            "attachments_received": flags,
        },
    }

    db.flush()

    if intake_status == "QUEUED":
        event_type = NEW_START_RECEIVED_NOTIFICATION_READY
        idempotency_key = f"{event_type}:{company_id}:{event.email_ingestion_event_id}"
        existing_event = (
            db.query(EventOutbox)
            .filter(EventOutbox.company_id == int(company_id))
            .filter(EventOutbox.idempotency_key == idempotency_key)
            .one_or_none()
        )
        if existing_event is None:
            db.add(
                EventOutbox(
                    company_id=int(company_id),
                    event_type=event_type,
                    idempotency_key=idempotency_key,
                    payload={
                        "company_id": int(company_id),
                        "job_start_intake_id": str(intake.job_start_intake_id),
                        "email_ingestion_event_id": str(event.email_ingestion_event_id),
                        "builder_name": metadata.builder_name,
                        "project_address": metadata.project_address,
                        "stake_date": metadata.stake_date.isoformat() if metadata.stake_date else None,
                        "queue_trigger_date": metadata.stake_date.isoformat() if metadata.stake_date else None,
                        "source_email": str(event.sender_email),
                    },
                )
            )

    return intake


def ingest_builder_email(
    *,
    db: Session,
    company_id: int,
    source: str,
    from_email: str,
    subject: str,
    received_at: datetime | None,
    body_text: str | None,
    attachments: list[IntakeAttachmentPayload],
) -> BuilderEmailIngestionResult:
    event_hash = _build_builder_email_event_hash(
        company_id=int(company_id),
        source=source,
        from_email=from_email,
        subject=subject,
        received_at=received_at,
        body_text=body_text,
        attachments=attachments,
    )
    source_message_id = f"{str(source).strip().lower()}:{event_hash}"

    event = (
        db.query(EmailIngestionEvent)
        .filter(EmailIngestionEvent.company_id == int(company_id))
        .filter(EmailIngestionEvent.source_message_id == source_message_id)
        .one_or_none()
    )

    idempotent_replay = event is not None
    if event is None:
        event = EmailIngestionEvent(
            company_id=int(company_id),
            source_message_id=source_message_id,
            sender_email=str(from_email),
            subject=str(subject),
            received_at=received_at,
            parse_status="RECEIVED",
            raw_metadata={
                "source": str(source),
                "event_hash": event_hash,
                "body_text": body_text,
                "attachments": [
                    {
                        "filename": str(attachment.file_name),
                        "storage_key": attachment.storage_key,
                        "content_type": attachment.content_type,
                    }
                    for attachment in attachments
                ],
            },
        )
        db.add(event)
        db.flush()

    intake = (
        db.query(JobStartIntake)
        .filter(JobStartIntake.company_id == int(company_id))
        .filter(JobStartIntake.email_ingestion_event_id == str(event.email_ingestion_event_id))
        .one_or_none()
    )
    if intake is None:
        intake = create_job_start_intake_from_email(
            db=db,
            company_id=int(company_id),
            email_ingestion_event_id=str(event.email_ingestion_event_id),
            parsed_text=body_text,
            attachments=attachments,
        )

    db.flush()

    documents = (
        db.query(JobDocument)
        .filter(JobDocument.company_id == int(company_id))
        .filter(JobDocument.email_ingestion_event_id == str(event.email_ingestion_event_id))
        .order_by(JobDocument.created_at.asc(), JobDocument.job_document_id.asc())
        .all()
    )

    outbox_idempotency_key = f"{NEW_START_RECEIVED_NOTIFICATION_READY}:{company_id}:{event.email_ingestion_event_id}"
    outbox_row = (
        db.query(EventOutbox)
        .filter(EventOutbox.company_id == int(company_id))
        .filter(EventOutbox.event_type == NEW_START_RECEIVED_NOTIFICATION_READY)
        .filter(EventOutbox.idempotency_key == outbox_idempotency_key)
        .one_or_none()
    )

    return BuilderEmailIngestionResult(
        event=event,
        intake=intake,
        documents=documents,
        event_hash=event_hash,
        event_emitted=outbox_row is not None,
        idempotent_replay=idempotent_replay,
    )


def promote_job_start_intake(
    *,
    db: Session,
    company_id: int,
    intake_id: str,
    promoted_by_user_id: str | None = None,
) -> IntakePromotionResult:
    intake = (
        db.query(JobStartIntake)
        .filter(JobStartIntake.company_id == int(company_id))
        .filter(JobStartIntake.job_start_intake_id == str(intake_id))
        .one_or_none()
    )
    if intake is None:
        raise ValueError("Job start intake not found")

    existing_job = (
        db.query(Job)
        .filter(Job.company_id == int(company_id))
        .filter(Job.source_job_start_intake_id == str(intake.job_start_intake_id))
        .one_or_none()
    )
    if existing_job is not None:
        _link_intake_documents_to_job(
            db=db,
            company_id=int(company_id),
            intake_id=str(intake.job_start_intake_id),
            job_id=int(existing_job.id),
        )
        if intake.promotion_status != "PROMOTED":
            intake.promotion_status = "PROMOTED"
        if intake.promoted_at is None:
            intake.promoted_at = existing_job.created_at
        db.add(intake)
        return IntakePromotionResult(intake=intake, job=existing_job)

    if intake.intake_status != "QUEUED":
        raise ValueError("Only queued intakes can be promoted")
    if intake.queue_trigger_date is None:
        raise ValueError("Queue trigger date is required before promotion")

    job = Job(
        company_id=int(company_id),
        name=_build_job_name(intake),
        source_job_start_intake_id=str(intake.job_start_intake_id),
        status="QUEUED",
        is_active=True,
        address_label=intake.project_address,
    )
    db.add(job)
    db.flush()
    record_initial_job_status(
        db=db,
        job=job,
        note=f"Promoted from intake {intake.job_start_intake_id}",
        transitioned_by_user_id=promoted_by_user_id,
    )
    _link_intake_documents_to_job(
        db=db,
        company_id=int(company_id),
        intake_id=str(intake.job_start_intake_id),
        job_id=int(job.id),
    )

    promoted_at = datetime.utcnow()
    intake.promotion_status = "PROMOTED"
    intake.promoted_at = promoted_at
    db.add(intake)

    event = (
        db.query(EmailIngestionEvent)
        .filter(EmailIngestionEvent.company_id == int(company_id))
        .filter(EmailIngestionEvent.email_ingestion_event_id == str(intake.email_ingestion_event_id))
        .one_or_none()
    )
    if event is not None:
        event.parsed_job_id = int(job.id)
        event.raw_metadata = {
            **(event.raw_metadata or {}),
            "job_start_intake_promotion": {
                "job_start_intake_id": str(intake.job_start_intake_id),
                "job_id": int(job.id),
                "promotion_status": "PROMOTED",
                "promoted_at": promoted_at.isoformat(),
                "promoted_by_user_id": promoted_by_user_id,
            },
        }
        db.add(event)

    return IntakePromotionResult(intake=intake, job=job)
