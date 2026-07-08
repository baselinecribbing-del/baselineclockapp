from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.deps.auth import require_auth
from app.schemas.email_ingestion import BuilderEmailIngestionResponse, BuilderEmailIngestionRequest
from app.services.job_intake_service import IntakeAttachmentPayload, ingest_builder_email

router = APIRouter(tags=["Email Ingestion"])


def _ensure_company(request: Request, x_company_id: int, payload_company_id: int) -> int:
    request_company_id = int(request.state.company_id)
    if int(x_company_id) != request_company_id:
        raise HTTPException(status_code=403, detail="Company mismatch")
    if int(payload_company_id) != request_company_id:
        raise HTTPException(status_code=403, detail="Company mismatch")
    return request_company_id


@router.post("/email-ingestion-events", response_model=BuilderEmailIngestionResponse)
def ingest_builder_email_event(
    payload: BuilderEmailIngestionRequest,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id, payload.company_id)

    db: Session = SessionLocal()
    try:
        result = ingest_builder_email(
            db=db,
            company_id=company_id,
            source=str(payload.source),
            from_email=str(payload.from_email),
            subject=str(payload.subject),
            received_at=payload.received_at,
            body_text=payload.body_text,
            attachments=[
                IntakeAttachmentPayload(
                    file_name=str(attachment.filename),
                    storage_key=attachment.storage_key,
                    content_type=attachment.content_type,
                )
                for attachment in payload.attachments
            ],
        )
        db.commit()

        return BuilderEmailIngestionResponse(
            email_ingestion_event_id=str(result.event.email_ingestion_event_id),
            job_start_intake_id=str(result.intake.job_start_intake_id),
            company_id=int(result.intake.company_id),
            source="builder_email",
            event_hash=result.event_hash,
            idempotent_replay=bool(result.idempotent_replay),
            builder_name=result.intake.builder_name,
            project_address=result.intake.project_address,
            lot_number=result.intake.lot_number,
            block_number=result.intake.block_number,
            stake_date=result.intake.stake_date,
            queue_trigger_date=result.intake.queue_trigger_date,
            intake_status=str(result.intake.intake_status),
            duplicate_of_job_start_intake_id=result.intake.duplicate_of_job_start_intake_id,
            event_emitted=bool(result.event_emitted),
            attachments=[
                {
                    "filename": str(document.file_name),
                    "storage_key": document.storage_key,
                    "content_type": next(
                        (
                            attachment.content_type
                            for attachment in payload.attachments
                            if str(attachment.filename) == str(document.file_name)
                            and attachment.storage_key == document.storage_key
                        ),
                        None,
                    ),
                    "document_type": str(document.document_type),
                    "job_document_id": str(document.job_document_id),
                }
                for document in result.documents
            ],
        )
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()
