from collections.abc import Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.foundation_activity_log import FoundationActivityLog
from app.models.hazard_assessment import HazardAssessment
from app.models.job import Job
from app.models.job_document import JobDocument
from app.models.job_start_intake import JobStartIntake
from app.schemas.job import (
    JobWorkspaceActivityItem,
    JobWorkspaceDocumentItem,
    JobWorkspaceHazardItem,
    JobWorkspaceHazardPhotoItem,
    JobWorkspaceJobSummary,
    JobWorkspaceResponse,
)

_WORKSPACE_BLUEPRINT_TYPES = {"BLUEPRINT", "GRADE_SLIP", "SITE_PLAN"}


def _build_lot_block(intake: JobStartIntake | None) -> str | None:
    if intake is None:
        return None
    parts: list[str] = []
    if intake.lot_number:
        parts.append(f"Lot {intake.lot_number}")
    if intake.block_number:
        parts.append(f"Block {intake.block_number}")
    return " ".join(parts) if parts else None


def _hazard_title(row: HazardAssessment) -> str | None:
    payload = row.form_payload or {}
    return payload.get("title") or payload.get("hazard") or payload.get("summary")


def _hazard_description(row: HazardAssessment) -> str | None:
    payload = row.form_payload or {}
    return payload.get("description") or payload.get("summary")


def _hazard_status(row: HazardAssessment) -> str | None:
    payload = row.form_payload or {}
    value = payload.get("status")
    return None if value is None else str(value)


def build_job_workspace(*, db: Session, company_id: int, job_id: int) -> JobWorkspaceResponse | None:
    job = (
        db.query(Job)
        .filter(Job.company_id == int(company_id))
        .filter(Job.id == int(job_id))
        .one_or_none()
    )
    if job is None:
        return None

    intake = None
    if job.source_job_start_intake_id is not None:
        intake = (
            db.query(JobStartIntake)
            .filter(JobStartIntake.company_id == int(company_id))
            .filter(JobStartIntake.job_start_intake_id == str(job.source_job_start_intake_id))
            .one_or_none()
        )

    document_query = db.query(JobDocument).filter(JobDocument.company_id == int(company_id))
    if job.source_job_start_intake_id is not None:
        document_query = document_query.filter(
            or_(
                JobDocument.job_id == int(job.id),
                JobDocument.job_start_intake_id == str(job.source_job_start_intake_id),
            )
        )
    else:
        document_query = document_query.filter(JobDocument.job_id == int(job.id))

    documents = (
        document_query
        .filter(JobDocument.document_type != "ISSUE_PHOTO")
        .order_by(JobDocument.created_at.desc(), JobDocument.job_document_id.asc())
        .all()
    )

    hazards = (
        db.query(HazardAssessment)
        .filter(HazardAssessment.company_id == int(company_id))
        .filter(HazardAssessment.job_id == int(job.id))
        .order_by(HazardAssessment.created_at.desc(), HazardAssessment.hazard_assessment_id.asc())
        .all()
    )
    hazard_ids = [str(row.hazard_assessment_id) for row in hazards]

    hazard_photos = (
        db.query(JobDocument)
        .filter(JobDocument.company_id == int(company_id))
        .filter(JobDocument.document_type == "ISSUE_PHOTO")
        .filter(JobDocument.hazard_assessment_id.in_(hazard_ids))
        .order_by(JobDocument.created_at.desc(), JobDocument.job_document_id.asc())
        .all()
        if hazard_ids
        else []
    )

    activity_rows = (
        db.query(FoundationActivityLog)
        .filter(FoundationActivityLog.company_id == int(company_id))
        .filter(FoundationActivityLog.job_id == int(job.id))
        .order_by(FoundationActivityLog.created_at.desc(), FoundationActivityLog.foundation_activity_id.asc())
        .all()
    )

    workspace_docs: Sequence[JobDocument] = documents
    blueprints = [
        JobWorkspaceDocumentItem(
            document_id=str(row.job_document_id),
            file_name=str(row.file_name),
            type=str(row.document_type),
            created_at=row.created_at,
        )
        for row in workspace_docs
        if str(row.document_type) in _WORKSPACE_BLUEPRINT_TYPES
    ]
    other_documents = [
        JobWorkspaceDocumentItem(
            document_id=str(row.job_document_id),
            file_name=str(row.file_name),
            type=str(row.document_type),
            created_at=row.created_at,
        )
        for row in workspace_docs
        if str(row.document_type) not in _WORKSPACE_BLUEPRINT_TYPES
    ]

    return JobWorkspaceResponse(
        job=JobWorkspaceJobSummary(
            id=int(job.id),
            builder_name=None if intake is None else intake.builder_name,
            project_address=(None if intake is None else intake.project_address) or job.address_label,
            lot_block=_build_lot_block(intake),
            stake_date=None if intake is None else intake.stake_date,
            queue_trigger_date=None if intake is None else intake.queue_trigger_date,
            status=str(job.status),
        ),
        blueprints=blueprints,
        documents=other_documents,
        hazards=[
            JobWorkspaceHazardItem(
                hazard_id=str(row.hazard_assessment_id),
                title=_hazard_title(row),
                description=_hazard_description(row),
                status=_hazard_status(row),
                created_at=row.created_at,
            )
            for row in hazards
        ],
        hazard_photos=[
            JobWorkspaceHazardPhotoItem(
                photo_id=str(row.job_document_id),
                hazard_id=str(row.hazard_assessment_id),
                file_name=row.file_name,
                storage_key=row.storage_key,
                created_at=row.created_at,
            )
            for row in hazard_photos
        ],
        activity=[
            JobWorkspaceActivityItem(
                activity_id=str(row.foundation_activity_id),
                type=str(row.activity_type),
                description=row.notes or row.photo_url,
                created_at=row.created_at,
            )
            for row in activity_rows
        ],
    )
