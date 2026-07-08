from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.deps.auth import get_actor_user_id, require_auth
from app.deps.entitlements import require_company_module
from app.models.email_ingestion_event import EmailIngestionEvent
from app.models.job import Job
from app.models.job_cost_ledger import JobCostLedger
from app.models.job_document import JobDocument
from app.models.job_purchase_order import JobPurchaseOrder
from app.models.job_start_intake import JobStartIntake
from app.models.scope import Scope
from app.schemas.job_documents import (
    EmailIngestionEventCreate,
    EmailIngestionEventResponse,
    JobDocumentAccessResponse,
    JobDocumentCreate,
    JobDocumentResponse,
    JobDocumentUploadPrepareRequest,
    JobDocumentUploadPrepareResponse,
    JobStartIntakeFromEmailRequest,
    JobStartIntakePromotionResponse,
    JobStartIntakeResponse,
    JobPurchaseOrderCostCreate,
    JobPurchaseOrderCostResponse,
    JobPurchaseOrderCreate,
    JobPurchaseOrderQueueMatchRequest,
    JobPurchaseOrderQueueTransitionRequest,
    JobPurchaseOrderResponse,
    QueueStatus,
)
from app.services.document_access_service import resolve_job_document_access
from app.services.job_intake_service import (
    IntakeAttachmentPayload,
    create_job_start_intake_from_email,
    promote_job_start_intake,
)
from app.services.po_costing_service import record_po_cost
from app.services.po_queue_service import close_po_queue_item, mark_ready_for_ops, match_to_job_scope_site
from app.services.upload_transport_service import build_storage_key, prepare_upload

router = APIRouter(
    prefix="/job-documents",
    tags=["Job Documents"],
    dependencies=[Depends(require_company_module("jobs"))],
)

_JOB_BLUEPRINT_DOCUMENT_TYPES = ("BLUEPRINT", "GRADE_SLIP", "SITE_PLAN")


def _ensure_company(request: Request, x_company_id: int) -> int:
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")
    return int(request.state.company_id)


def _serialize_email_ingestion_event(row: EmailIngestionEvent) -> EmailIngestionEventResponse:
    return EmailIngestionEventResponse(
        email_ingestion_event_id=str(row.email_ingestion_event_id),
        company_id=int(row.company_id),
        source_message_id=str(row.source_message_id),
        sender_email=str(row.sender_email),
        subject=str(row.subject),
        received_at=row.received_at,
        parse_status=str(row.parse_status),
        parsed_job_id=None if row.parsed_job_id is None else int(row.parsed_job_id),
        parsed_scope_id=None if row.parsed_scope_id is None else int(row.parsed_scope_id),
        parsed_po_number=row.parsed_po_number,
        parse_notes=row.parse_notes,
        raw_metadata=row.raw_metadata,
    )


def _serialize_job_po(row: JobPurchaseOrder) -> JobPurchaseOrderResponse:
    return JobPurchaseOrderResponse(
        job_purchase_order_id=str(row.job_purchase_order_id),
        company_id=int(row.company_id),
        job_id=int(row.job_id),
        scope_id=None if row.scope_id is None else int(row.scope_id),
        po_number=str(row.po_number),
        vendor_name=row.vendor_name,
        vendor_email=row.vendor_email,
        source_email_ingestion_event_id=row.source_email_ingestion_event_id,
        status=str(row.status),
        issued_date=row.issued_date,
        queue_status=str(row.queue_status),
        matched_job_id=None if row.matched_job_id is None else int(row.matched_job_id),
        matched_scope_id=None if row.matched_scope_id is None else int(row.matched_scope_id),
        matched_customer_site_id=row.matched_customer_site_id,
        reviewed_by_user_id=row.reviewed_by_user_id,
        reviewed_at=row.reviewed_at,
        review_notes=row.review_notes,
        created_at=row.created_at,
    )


def _serialize_po_cost(row: JobCostLedger) -> JobPurchaseOrderCostResponse:
    prefix = f"po:{row.job_purchase_order_id}:"
    description = str(row.source_reference_id)
    if description.startswith(prefix):
        description = description[len(prefix):]

    return JobPurchaseOrderCostResponse(
        id=int(row.id),
        company_id=int(row.company_id),
        job_purchase_order_id=str(row.job_purchase_order_id),
        amount_cents=int(row.total_cost_cents),
        description=description,
        source_reference_id=str(row.source_reference_id),
        posting_date=row.posting_date,
        created_at=row.created_at,
    )


def _serialize_job_start_intake(row: JobStartIntake, job_id: int | None = None) -> JobStartIntakeResponse:
    return JobStartIntakeResponse(
        job_start_intake_id=str(row.job_start_intake_id),
        company_id=int(row.company_id),
        email_ingestion_event_id=str(row.email_ingestion_event_id),
        job_id=job_id,
        duplicate_of_job_start_intake_id=row.duplicate_of_job_start_intake_id,
        builder_name=row.builder_name,
        source_email=str(row.source_email),
        project_address=row.project_address,
        lot_number=row.lot_number,
        block_number=row.block_number,
        stake_date=row.stake_date,
        queue_trigger_date=row.queue_trigger_date,
        intake_status=str(row.intake_status),
        has_blueprint=bool(row.has_blueprint),
        has_grade_slip=bool(row.has_grade_slip),
        has_site_plan=bool(row.has_site_plan),
        has_stake_date_document=bool(row.has_stake_date_document),
        promotion_status=str(row.promotion_status),
        promoted_at=row.promoted_at,
        attachments_received={
            "has_blueprint": bool(row.has_blueprint),
            "has_grade_slip": bool(row.has_grade_slip),
            "has_site_plan": bool(row.has_site_plan),
            "has_stake_date_document": bool(row.has_stake_date_document),
        },
        parse_notes=row.parse_notes,
        created_at=row.created_at,
    )


def _serialize_job_document(row: JobDocument) -> JobDocumentResponse:
    return JobDocumentResponse(
        document_id=str(row.job_document_id),
        job_document_id=str(row.job_document_id),
        company_id=int(row.company_id),
        job_id=None if row.job_id is None else int(row.job_id),
        job_start_intake_id=None if row.job_start_intake_id is None else str(row.job_start_intake_id),
        email_ingestion_event_id=None if row.email_ingestion_event_id is None else str(row.email_ingestion_event_id),
        document_type=str(row.document_type),
        file_name=str(row.file_name),
        storage_key=row.storage_key,
        caption=row.caption,
        created_at=row.created_at,
    )


def _serialize_job_document_access(row: JobDocument) -> JobDocumentAccessResponse:
    access = resolve_job_document_access(row)
    return JobDocumentAccessResponse(
        document_id=str(row.job_document_id),
        access_type=str(access.access_type),
        file_url=access.file_url,
        download_url=access.download_url,
        file_name=str(access.file_name),
        content_type=access.content_type,
        expires_at=None,
        available=bool(access.available),
        reason=access.reason,
    )


def _get_job_start_intake(db: Session, company_id: int, intake_id: str) -> JobStartIntake:
    row = (
        db.query(JobStartIntake)
        .filter(JobStartIntake.company_id == company_id)
        .filter(JobStartIntake.job_start_intake_id == str(intake_id))
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Job start intake not found")
    return row


def _get_job(db: Session, company_id: int, job_id: int) -> Job:
    row = (
        db.query(Job)
        .filter(Job.company_id == company_id)
        .filter(Job.id == int(job_id))
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return row


def _serialize_job_document_upload_prepare(storage_key: str) -> JobDocumentUploadPrepareResponse:
    prepared = prepare_upload(storage_key=storage_key)
    return JobDocumentUploadPrepareResponse(
        storage_key=prepared.storage_key,
        upload_url=prepared.upload_url,
        required_headers=prepared.required_headers,
        required_fields=prepared.required_fields,
        expires_at=None,
        available=prepared.available,
        reason=prepared.reason,
    )


@router.post("/email-ingestion-events", response_model=EmailIngestionEventResponse)
def create_email_ingestion_event(
    payload: EmailIngestionEventCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        row = EmailIngestionEvent(
            company_id=company_id,
            source_message_id=str(payload.source_message_id),
            sender_email=str(payload.sender_email),
            subject=str(payload.subject),
            received_at=payload.received_at,
            parse_status=str(payload.parse_status),
            parsed_job_id=payload.parsed_job_id,
            parsed_scope_id=payload.parsed_scope_id,
            parsed_po_number=payload.parsed_po_number,
            parse_notes=payload.parse_notes,
            raw_metadata=payload.raw_metadata,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_email_ingestion_event(row)
    finally:
        db.close()


@router.get("/email-ingestion-events", response_model=list[EmailIngestionEventResponse])
def list_email_ingestion_events(
    request: Request,
    parse_status: Literal["RECEIVED", "PARSED", "FAILED"] | None = Query(default=None),
    parsed_po_number: str | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        q = db.query(EmailIngestionEvent).filter(EmailIngestionEvent.company_id == company_id)

        if parse_status is not None:
            q = q.filter(EmailIngestionEvent.parse_status == str(parse_status))
        if parsed_po_number is not None:
            q = q.filter(EmailIngestionEvent.parsed_po_number == str(parsed_po_number))

        rows = q.order_by(EmailIngestionEvent.received_at.desc(), EmailIngestionEvent.email_ingestion_event_id.asc()).all()
        return [_serialize_email_ingestion_event(row) for row in rows]
    finally:
        db.close()


@router.post("/job-start-intakes/from-email", response_model=JobStartIntakeResponse)
def create_job_start_intake_from_email_endpoint(
    payload: JobStartIntakeFromEmailRequest,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        try:
            row = create_job_start_intake_from_email(
                db=db,
                company_id=company_id,
                email_ingestion_event_id=str(payload.email_ingestion_event_id),
                parsed_text=payload.parsed_text,
                attachments=[
                    IntakeAttachmentPayload(
                        file_name=str(attachment.file_name),
                        parsed_text=attachment.parsed_text,
                        storage_key=attachment.storage_key,
                    )
                    for attachment in payload.attachments
                ],
            )
        except ValueError as exc:
            detail = str(exc)
            if detail == "Email ingestion event not found":
                raise HTTPException(status_code=404, detail=detail) from exc
            raise HTTPException(status_code=422, detail=detail) from exc

        db.commit()
        db.refresh(row)
        return _serialize_job_start_intake(row)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/job-start-intakes", response_model=list[JobStartIntakeResponse])
def list_job_start_intakes(
    request: Request,
    intake_status: Literal["QUEUED", "FLAGGED", "DUPLICATE"] | None = Query(default=None),
    source_email_ingestion_event_id: str | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        q = db.query(JobStartIntake).filter(JobStartIntake.company_id == company_id)
        if intake_status is not None:
            q = q.filter(JobStartIntake.intake_status == str(intake_status))
        if source_email_ingestion_event_id is not None:
            q = q.filter(JobStartIntake.email_ingestion_event_id == str(source_email_ingestion_event_id))

        rows = q.order_by(JobStartIntake.created_at.desc(), JobStartIntake.job_start_intake_id.asc()).all()
        intake_ids = [str(row.job_start_intake_id) for row in rows]
        linked_jobs = (
            db.query(Job.source_job_start_intake_id, Job.id)
            .filter(Job.company_id == company_id)
            .filter(Job.source_job_start_intake_id.in_(intake_ids))
            .all()
            if intake_ids
            else []
        )
        job_ids_by_intake = {str(intake_id): int(job_id) for intake_id, job_id in linked_jobs if intake_id is not None}
        return [_serialize_job_start_intake(row, job_id=job_ids_by_intake.get(str(row.job_start_intake_id))) for row in rows]
    finally:
        db.close()


@router.get("/job-start-intakes/{intake_id}/documents", response_model=list[JobDocumentResponse])
def list_job_start_intake_documents(
    intake_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        intake = (
            db.query(JobStartIntake)
            .filter(JobStartIntake.company_id == company_id)
            .filter(JobStartIntake.job_start_intake_id == str(intake_id))
            .one_or_none()
        )
        if intake is None:
            raise HTTPException(status_code=404, detail="Job start intake not found")

        rows = (
            db.query(JobDocument)
            .filter(JobDocument.company_id == company_id)
            .filter(JobDocument.job_start_intake_id == str(intake_id))
            .order_by(JobDocument.created_at.asc(), JobDocument.file_name.asc(), JobDocument.job_document_id.asc())
            .all()
        )
        return [_serialize_job_document(row) for row in rows]
    finally:
        db.close()


@router.post("/uploads/prepare", response_model=JobDocumentUploadPrepareResponse)
def prepare_job_document_upload(
    payload: JobDocumentUploadPrepareRequest,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        if payload.intake_id is not None:
            intake = _get_job_start_intake(db, company_id, str(payload.intake_id))
            context_id = f"intakes/{intake.job_start_intake_id}"
        else:
            job = _get_job(db, company_id, int(payload.job_id))
            context_id = f"jobs/{job.id}"

        storage_key = build_storage_key(
            prefix="job-documents",
            company_id=company_id,
            context_id=context_id,
            file_name=str(payload.file_name),
        )
        return _serialize_job_document_upload_prepare(storage_key)
    finally:
        db.close()


@router.post("", response_model=JobDocumentResponse)
def create_job_document(
    payload: JobDocumentCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        intake_id = None
        job_id = None

        if payload.intake_id is not None:
            intake = _get_job_start_intake(db, company_id, str(payload.intake_id))
            intake_id = str(intake.job_start_intake_id)
            linked_job = (
                db.query(Job)
                .filter(Job.company_id == company_id)
                .filter(Job.source_job_start_intake_id == intake_id)
                .one_or_none()
            )
            if linked_job is not None:
                job_id = int(linked_job.id)
        else:
            job = _get_job(db, company_id, int(payload.job_id))
            job_id = int(job.id)
            intake_id = None if job.source_job_start_intake_id is None else str(job.source_job_start_intake_id)

        row = JobDocument(
            company_id=company_id,
            job_id=job_id,
            job_start_intake_id=intake_id,
            document_type=str(payload.document_type),
            file_name=str(payload.file_name),
            storage_key=str(payload.storage_key),
            caption=payload.caption,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_job_document(row)
    finally:
        db.close()


@router.get("/jobs/{job_id}/documents", response_model=list[JobDocumentResponse])
def list_job_documents_for_job(
    job_id: int,
    request: Request,
    document_type: Literal["BLUEPRINT", "GRADE_SLIP", "SITE_PLAN"] | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        job = (
            db.query(Job)
            .filter(Job.company_id == company_id)
            .filter(Job.id == int(job_id))
            .one_or_none()
        )
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        query = (
            db.query(JobDocument)
            .filter(JobDocument.company_id == company_id)
            .filter(JobDocument.job_id == int(job_id))
            .filter(JobDocument.document_type.in_(_JOB_BLUEPRINT_DOCUMENT_TYPES))
        )
        if document_type is not None:
            query = query.filter(JobDocument.document_type == str(document_type))

        rows = query.order_by(JobDocument.created_at.asc(), JobDocument.file_name.asc(), JobDocument.job_document_id.asc()).all()
        return [_serialize_job_document(row) for row in rows]
    finally:
        db.close()


@router.get("/records/{document_id}/access", response_model=JobDocumentAccessResponse)
def get_job_document_access(
    document_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        row = (
            db.query(JobDocument)
            .filter(JobDocument.company_id == company_id)
            .filter(JobDocument.job_document_id == str(document_id))
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Job document not found")
        return _serialize_job_document_access(row)
    finally:
        db.close()


@router.post("/job-start-intakes/{intake_id}/promote", response_model=JobStartIntakePromotionResponse)
def promote_job_start_intake_endpoint(
    intake_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        try:
            result = promote_job_start_intake(
                db=db,
                company_id=company_id,
                intake_id=str(intake_id),
                promoted_by_user_id=getattr(request.state, "user_id", None),
            )
        except ValueError as exc:
            detail = str(exc)
            if detail == "Job start intake not found":
                raise HTTPException(status_code=404, detail=detail) from exc
            if detail == "Queue trigger date is required before promotion":
                raise HTTPException(status_code=422, detail=detail) from exc
            raise HTTPException(status_code=409, detail=detail) from exc

        db.commit()
        db.refresh(result.intake)
        db.refresh(result.job)
        return JobStartIntakePromotionResponse(
            intake_id=str(result.intake.job_start_intake_id),
            job_id=int(result.job.id),
            promotion_status="PROMOTED",
            promoted_at=result.intake.promoted_at or result.job.created_at,
            queue_trigger_date=result.intake.queue_trigger_date,
            builder_name=result.intake.builder_name,
            project_address=result.intake.project_address,
        )
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/purchase-orders", response_model=JobPurchaseOrderResponse)
def create_purchase_order(
    payload: JobPurchaseOrderCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        job = db.query(Job).filter(Job.company_id == company_id, Job.id == int(payload.job_id)).one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        if payload.scope_id is not None:
            scope = (
                db.query(Scope)
                .filter(
                    Scope.company_id == company_id,
                    Scope.id == int(payload.scope_id),
                    Scope.job_id == int(payload.job_id),
                )
                .one_or_none()
            )
            if scope is None:
                raise HTTPException(status_code=404, detail="Scope not found")

        if payload.source_email_ingestion_event_id is not None:
            event = (
                db.query(EmailIngestionEvent)
                .filter(
                    EmailIngestionEvent.company_id == company_id,
                    EmailIngestionEvent.email_ingestion_event_id == str(payload.source_email_ingestion_event_id),
                )
                .one_or_none()
            )
            if event is None:
                raise HTTPException(status_code=404, detail="Email ingestion event not found")

        row = JobPurchaseOrder(
            company_id=company_id,
            job_id=int(payload.job_id),
            scope_id=payload.scope_id,
            po_number=str(payload.po_number),
            vendor_name=payload.vendor_name,
            vendor_email=payload.vendor_email,
            source_email_ingestion_event_id=payload.source_email_ingestion_event_id,
            status=str(payload.status),
            issued_date=payload.issued_date,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_job_po(row)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        msg = str(getattr(exc, "orig", exc))
        if "uq_job_purchase_orders_company_po_number" in msg:
            raise HTTPException(status_code=409, detail="Purchase order already exists for this company") from exc
        raise
    finally:
        db.close()


@router.get("/purchase-orders", response_model=list[JobPurchaseOrderResponse])
def list_purchase_orders(
    request: Request,
    job_id: int | None = Query(default=None),
    scope_id: int | None = Query(default=None),
    po_number: str | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        q = db.query(JobPurchaseOrder).filter(JobPurchaseOrder.company_id == company_id)

        if job_id is not None:
            q = q.filter(JobPurchaseOrder.job_id == int(job_id))
        if scope_id is not None:
            q = q.filter(JobPurchaseOrder.scope_id == int(scope_id))
        if po_number is not None:
            q = q.filter(JobPurchaseOrder.po_number == str(po_number))

        rows = q.order_by(JobPurchaseOrder.created_at.desc(), JobPurchaseOrder.job_purchase_order_id.asc()).all()
        return [_serialize_job_po(row) for row in rows]
    finally:
        db.close()


@router.get("/purchase-orders/queue", response_model=list[JobPurchaseOrderResponse])
def list_purchase_order_queue(
    request: Request,
    queue_status: QueueStatus | None = Query(default=None),
    po_number: str | None = Query(default=None),
    matched_job_id: int | None = Query(default=None),
    matched_scope_id: int | None = Query(default=None),
    matched_customer_site_id: str | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        q = db.query(JobPurchaseOrder).filter(JobPurchaseOrder.company_id == company_id)
        if queue_status is not None:
            q = q.filter(JobPurchaseOrder.queue_status == str(queue_status))
        if po_number is not None:
            q = q.filter(JobPurchaseOrder.po_number == str(po_number))
        if matched_job_id is not None:
            q = q.filter(JobPurchaseOrder.matched_job_id == int(matched_job_id))
        if matched_scope_id is not None:
            q = q.filter(JobPurchaseOrder.matched_scope_id == int(matched_scope_id))
        if matched_customer_site_id is not None:
            q = q.filter(JobPurchaseOrder.matched_customer_site_id == str(matched_customer_site_id))

        rows = q.order_by(JobPurchaseOrder.created_at.desc(), JobPurchaseOrder.job_purchase_order_id.asc()).all()
        return [_serialize_job_po(row) for row in rows]
    finally:
        db.close()


def _handle_po_queue_service_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    if detail in {
        "Job purchase order not found",
        "Matched job not found",
        "Matched scope not found",
        "Matched customer site not found",
    }:
        return HTTPException(status_code=404, detail=detail)
    if detail.startswith("Invalid queue status transition:") or detail == "Cannot mark ready for ops without matched job and customer site linkage":
        return HTTPException(status_code=409, detail=detail)
    return HTTPException(status_code=422, detail=detail)


@router.post("/purchase-orders/{po_id}/match", response_model=JobPurchaseOrderResponse)
def match_purchase_order_queue_item(
    po_id: str,
    payload: JobPurchaseOrderQueueMatchRequest,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        try:
            row = match_to_job_scope_site(
                db=db,
                company_id=company_id,
                job_purchase_order_id=str(po_id),
                matched_job_id=int(payload.matched_job_id),
                matched_scope_id=payload.matched_scope_id,
                matched_customer_site_id=str(payload.matched_customer_site_id),
                reviewed_by_user_id=get_actor_user_id(request),
                review_notes=payload.review_notes,
            )
        except ValueError as exc:
            raise _handle_po_queue_service_error(exc) from exc

        db.commit()
        db.refresh(row)
        return _serialize_job_po(row)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/purchase-orders/{po_id}/ready", response_model=JobPurchaseOrderResponse)
def mark_purchase_order_ready_for_ops(
    po_id: str,
    payload: JobPurchaseOrderQueueTransitionRequest,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        try:
            row = mark_ready_for_ops(
                db=db,
                company_id=company_id,
                job_purchase_order_id=str(po_id),
                reviewed_by_user_id=get_actor_user_id(request),
                review_notes=payload.review_notes,
            )
        except ValueError as exc:
            raise _handle_po_queue_service_error(exc) from exc

        db.commit()
        db.refresh(row)
        return _serialize_job_po(row)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/purchase-orders/{po_id}/close", response_model=JobPurchaseOrderResponse)
def close_purchase_order_queue_item(
    po_id: str,
    payload: JobPurchaseOrderQueueTransitionRequest,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        try:
            row = close_po_queue_item(
                db=db,
                company_id=company_id,
                job_purchase_order_id=str(po_id),
                reviewed_by_user_id=get_actor_user_id(request),
                review_notes=payload.review_notes,
            )
        except ValueError as exc:
            raise _handle_po_queue_service_error(exc) from exc

        db.commit()
        db.refresh(row)
        return _serialize_job_po(row)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.post(
    "/purchase-orders/{po_id}/costs",
    response_model=JobPurchaseOrderCostResponse,
    dependencies=[Depends(require_company_module("costing"))],
)
def create_purchase_order_cost(
    po_id: str,
    payload: JobPurchaseOrderCostCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        try:
            row = record_po_cost(
                company_id=company_id,
                job_purchase_order_id=str(po_id),
                amount_cents=int(payload.amount_cents),
                description=str(payload.description),
                db=db,
            )
        except ValueError as exc:
            detail = str(exc)
            if detail == "Job purchase order not found":
                raise HTTPException(status_code=404, detail=detail) from exc
            raise HTTPException(status_code=422, detail=detail) from exc

        db.commit()
        db.refresh(row)
        return _serialize_po_cost(row)
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@router.get(
    "/purchase-orders/{po_id}/costs",
    response_model=list[JobPurchaseOrderCostResponse],
    dependencies=[Depends(require_company_module("costing"))],
)
def list_purchase_order_costs(
    po_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        po = (
            db.query(JobPurchaseOrder)
            .filter(JobPurchaseOrder.company_id == company_id)
            .filter(JobPurchaseOrder.job_purchase_order_id == str(po_id))
            .one_or_none()
        )
        if po is None:
            raise HTTPException(status_code=404, detail="Job purchase order not found")

        rows = (
            db.query(JobCostLedger)
            .filter(JobCostLedger.company_id == company_id)
            .filter(JobCostLedger.job_purchase_order_id == str(po_id))
            .filter(JobCostLedger.cost_source == "PO")
            .order_by(JobCostLedger.posting_date.asc(), JobCostLedger.id.asc())
            .all()
        )
        return [_serialize_po_cost(row) for row in rows]
    finally:
        db.close()
