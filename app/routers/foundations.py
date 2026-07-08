from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.deps.auth import get_actor_user_id, require_auth
from app.deps.entitlements import require_company_module
from app.models.company_module import CompanyModule
from app.models.crew_assignment import CrewAssignment
from app.models.crew_group import CrewGroup
from app.models.crew_group_member import CrewGroupMember
from app.models.employee import Employee
from app.models.foundation_activity_log import FoundationActivityLog
from app.models.foundations_message import FoundationsMessage
from app.models.hazard_assessment import HazardAssessment
from app.models.job import Job
from app.models.job_document import JobDocument
from app.models.job_document_delivery import JobDocumentDelivery
from app.models.scope import Scope
from app.models.toolbox_meeting import ToolboxMeeting
from app.schemas.foundations import (
    CompanyModuleCreate,
    CompanyModuleResponse,
    CrewAssignmentAcknowledgeCreate,
    CrewGroupAssignCreate,
    CrewGroupAssignResponse,
    CrewAssignmentCreate,
    CrewAssignmentResponse,
    CrewGroupCreate,
    CrewGroupMemberCreate,
    CrewGroupMemberResponse,
    CrewGroupResponse,
    FoundationActivityCreate,
    FoundationActivityResponse,
    FoundationsJobDocumentResponse,
    FoundationsMessageCreate,
    FoundationsMessageResponse,
    HazardAssessmentCreate,
    HazardAssessmentPhotoAccessResponse,
    HazardAssessmentPhotoCreate,
    HazardAssessmentPhotoUploadPrepareRequest,
    HazardAssessmentPhotoUploadPrepareResponse,
    HazardAssessmentPhotoResponse,
    HazardAssessmentResponse,
    JobDocumentDeliveryCreate,
    JobDocumentDeliveryResponse,
    ToolboxMeetingCreate,
    ToolboxMeetingResponse,
)
from app.services.document_access_service import resolve_job_document_access
from app.services.upload_transport_service import build_storage_key, prepare_upload

router = APIRouter(tags=["Foundations"], dependencies=[Depends(require_company_module("foundations"))])


def _ensure_company(request: Request, x_company_id: int) -> int:
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")
    return int(request.state.company_id)


def _serialize_company_module(row: CompanyModule) -> CompanyModuleResponse:
    return CompanyModuleResponse(
        company_module_id=str(row.company_module_id),
        company_id=int(row.company_id),
        module_code=str(row.module_code),
        is_enabled=bool(row.is_enabled),
        created_at=row.created_at,
    )


def _serialize_crew_assignment(row: CrewAssignment) -> CrewAssignmentResponse:
    return CrewAssignmentResponse(
        crew_assignment_id=str(row.crew_assignment_id),
        company_id=int(row.company_id),
        employee_id=int(row.employee_id),
        job_id=int(row.job_id),
        scope_id=None if row.scope_id is None else int(row.scope_id),
        assigned_date=row.assigned_date,
        assigned_by_user_id=str(row.assigned_by_user_id),
        assignment_notes=row.assignment_notes,
        status=str(row.status),
        acknowledged_at=row.acknowledged_at,
        acknowledged_by_employee_id=(
            None if row.acknowledged_by_employee_id is None else int(row.acknowledged_by_employee_id)
        ),
        created_at=row.created_at,
    )


def _serialize_crew_group(row: CrewGroup) -> CrewGroupResponse:
    return CrewGroupResponse(
        crew_group_id=str(row.crew_group_id),
        company_id=int(row.company_id),
        name=str(row.name),
        created_by_user_id=str(row.created_by_user_id),
        created_at=row.created_at,
    )


def _serialize_crew_group_member(row: CrewGroupMember) -> CrewGroupMemberResponse:
    return CrewGroupMemberResponse(
        crew_group_member_id=str(row.crew_group_member_id),
        company_id=int(row.company_id),
        crew_group_id=str(row.crew_group_id),
        employee_id=int(row.employee_id),
        created_at=row.created_at,
    )


def _serialize_hazard_assessment(row: HazardAssessment) -> HazardAssessmentResponse:
    return HazardAssessmentResponse(
        hazard_assessment_id=str(row.hazard_assessment_id),
        company_id=int(row.company_id),
        job_id=int(row.job_id),
        scope_id=None if row.scope_id is None else int(row.scope_id),
        crew_assignment_id=None if row.crew_assignment_id is None else str(row.crew_assignment_id),
        completed_by_employee_id=int(row.completed_by_employee_id),
        assessment_date=row.assessment_date,
        form_payload=row.form_payload,
        created_at=row.created_at,
    )


def _serialize_hazard_assessment_photo(row: JobDocument) -> HazardAssessmentPhotoResponse:
    return HazardAssessmentPhotoResponse(
        photo_id=str(row.job_document_id),
        job_document_id=str(row.job_document_id),
        hazard_assessment_id=str(row.hazard_assessment_id),
        company_id=int(row.company_id),
        job_id=int(row.job_id),
        document_type="ISSUE_PHOTO",
        file_name=str(row.file_name),
        storage_key=str(row.storage_key),
        caption=row.caption,
        uploaded_at=row.created_at,
    )


def _serialize_hazard_assessment_photo_access(row: JobDocument) -> HazardAssessmentPhotoAccessResponse:
    access = resolve_job_document_access(row)
    return HazardAssessmentPhotoAccessResponse(
        photo_id=str(row.job_document_id),
        access_type=str(access.access_type),
        file_url=access.file_url,
        download_url=access.download_url,
        file_name=str(access.file_name),
        content_type=access.content_type,
        expires_at=None,
        available=bool(access.available),
        reason=access.reason,
    )


def _serialize_hazard_assessment_photo_upload_prepare(storage_key: str) -> HazardAssessmentPhotoUploadPrepareResponse:
    prepared = prepare_upload(storage_key=storage_key)
    return HazardAssessmentPhotoUploadPrepareResponse(
        storage_key=prepared.storage_key,
        upload_url=prepared.upload_url,
        required_headers=prepared.required_headers,
        required_fields=prepared.required_fields,
        expires_at=None,
        available=prepared.available,
        reason=prepared.reason,
    )


def _serialize_toolbox_meeting(row: ToolboxMeeting) -> ToolboxMeetingResponse:
    return ToolboxMeetingResponse(
        toolbox_meeting_id=str(row.toolbox_meeting_id),
        company_id=int(row.company_id),
        job_id=None if row.job_id is None else int(row.job_id),
        scope_id=None if row.scope_id is None else int(row.scope_id),
        meeting_date=row.meeting_date,
        completed_by_employee_id=int(row.completed_by_employee_id),
        attendee_count=None if row.attendee_count is None else int(row.attendee_count),
        form_payload=row.form_payload,
        created_at=row.created_at,
    )


def _serialize_job_document_delivery(row: JobDocumentDelivery) -> JobDocumentDeliveryResponse:
    return JobDocumentDeliveryResponse(
        job_document_delivery_id=str(row.job_document_delivery_id),
        company_id=int(row.company_id),
        job_document_id=str(row.job_document_id),
        employee_id=int(row.employee_id),
        delivered_at=row.delivered_at,
        viewed_at=row.viewed_at,
    )


def _serialize_foundations_message(row: FoundationsMessage) -> FoundationsMessageResponse:
    return FoundationsMessageResponse(
        foundations_message_id=str(row.foundations_message_id),
        company_id=int(row.company_id),
        job_id=None if row.job_id is None else int(row.job_id),
        scope_id=None if row.scope_id is None else int(row.scope_id),
        employee_id=None if row.employee_id is None else int(row.employee_id),
        message_type=str(row.message_type),
        subject=row.subject,
        body=str(row.body),
        created_by_user_id=str(row.created_by_user_id),
        created_at=row.created_at,
    )


def _serialize_foundation_activity(row: FoundationActivityLog) -> FoundationActivityResponse:
    return FoundationActivityResponse(
        foundation_activity_id=str(row.foundation_activity_id),
        company_id=int(row.company_id),
        job_id=int(row.job_id),
        scope_id=int(row.scope_id),
        employee_id=int(row.employee_id),
        activity_type=str(row.activity_type),
        notes=row.notes,
        photo_url=row.photo_url,
        created_at=row.created_at,
    )


def _serialize_foundations_job_document(row: JobDocument) -> FoundationsJobDocumentResponse:
    return FoundationsJobDocumentResponse(
        document_id=str(row.job_document_id),
        filename=str(row.file_name),
        document_type=str(row.document_type),
        uploaded_at=row.created_at,
        download_url=row.storage_key,
    )


def _assert_employee_exists(db: Session, company_id: int, employee_id: int) -> None:
    employee = (
        db.query(Employee)
        .filter(Employee.company_id == company_id)
        .filter(Employee.id == int(employee_id))
        .one_or_none()
    )
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")


def _assert_job_exists(db: Session, company_id: int, job_id: int) -> None:
    job = db.query(Job).filter(Job.company_id == company_id).filter(Job.id == int(job_id)).one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")


def _assert_scope_exists(db: Session, company_id: int, scope_id: int, job_id: int | None = None) -> None:
    query = db.query(Scope).filter(Scope.company_id == company_id).filter(Scope.id == int(scope_id))
    if job_id is not None:
        query = query.filter(Scope.job_id == int(job_id))

    scope = query.one_or_none()
    if scope is None:
        raise HTTPException(status_code=404, detail="Scope not found")


def _get_hazard_assessment(db: Session, company_id: int, hazard_assessment_id: str) -> HazardAssessment:
    row = (
        db.query(HazardAssessment)
        .filter(HazardAssessment.company_id == company_id)
        .filter(HazardAssessment.hazard_assessment_id == str(hazard_assessment_id))
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Hazard assessment not found")
    return row


def _assert_crew_group_exists(db: Session, company_id: int, crew_group_id: str) -> CrewGroup:
    row = (
        db.query(CrewGroup)
        .filter(CrewGroup.company_id == company_id)
        .filter(CrewGroup.crew_group_id == str(crew_group_id))
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Crew group not found")
    return row


@router.get("/company-modules", response_model=list[CompanyModuleResponse])
def list_company_modules(
    request: Request,
    module_code: str | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        query = db.query(CompanyModule).filter(CompanyModule.company_id == company_id)
        if module_code is not None:
            query = query.filter(CompanyModule.module_code == str(module_code))

        rows = query.order_by(CompanyModule.created_at.desc(), CompanyModule.company_module_id.asc()).all()
        return [_serialize_company_module(row) for row in rows]
    finally:
        db.close()


@router.post("/company-modules", response_model=CompanyModuleResponse)
def create_company_module(
    payload: CompanyModuleCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        row = CompanyModule(
            company_id=company_id,
            module_code=str(payload.module_code),
            is_enabled=bool(payload.is_enabled),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_company_module(row)
    except IntegrityError as exc:
        db.rollback()
        msg = str(getattr(exc, "orig", exc))
        if "uq_company_modules_company_module_code" in msg:
            raise HTTPException(status_code=409, detail="Company module already exists") from exc
        raise
    finally:
        db.close()


@router.post("/foundations/crew-groups", response_model=CrewGroupResponse)
def create_crew_group(
    payload: CrewGroupCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        row = CrewGroup(
            company_id=company_id,
            name=str(payload.name),
            created_by_user_id=get_actor_user_id(request),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_crew_group(row)
    finally:
        db.close()


@router.get("/foundations/crew-groups", response_model=list[CrewGroupResponse])
def list_crew_groups(
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        rows = (
            db.query(CrewGroup)
            .filter(CrewGroup.company_id == company_id)
            .order_by(CrewGroup.created_at.desc(), CrewGroup.crew_group_id.asc())
            .all()
        )
        return [_serialize_crew_group(row) for row in rows]
    finally:
        db.close()


@router.post("/foundations/crew-groups/{crew_group_id}/members", response_model=CrewGroupMemberResponse)
def add_crew_group_member(
    crew_group_id: str,
    payload: CrewGroupMemberCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        _assert_crew_group_exists(db, company_id, crew_group_id)
        _assert_employee_exists(db, company_id, int(payload.employee_id))

        row = CrewGroupMember(
            company_id=company_id,
            crew_group_id=str(crew_group_id),
            employee_id=int(payload.employee_id),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_crew_group_member(row)
    except IntegrityError as exc:
        db.rollback()
        msg = str(getattr(exc, "orig", exc))
        if "uq_crew_group_members_company_group_employee" in msg:
            raise HTTPException(status_code=409, detail="Employee already in crew group") from exc
        raise
    finally:
        db.close()


@router.get("/foundations/crew-groups/{crew_group_id}/members", response_model=list[CrewGroupMemberResponse])
def list_crew_group_members(
    crew_group_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        _assert_crew_group_exists(db, company_id, crew_group_id)
        rows = (
            db.query(CrewGroupMember)
            .filter(CrewGroupMember.company_id == company_id)
            .filter(CrewGroupMember.crew_group_id == str(crew_group_id))
            .order_by(CrewGroupMember.created_at.asc(), CrewGroupMember.crew_group_member_id.asc())
            .all()
        )
        return [_serialize_crew_group_member(row) for row in rows]
    finally:
        db.close()


@router.delete("/foundations/crew-groups/{crew_group_id}/members/{employee_id}", response_model=dict[str, bool])
def remove_crew_group_member(
    crew_group_id: str,
    employee_id: int,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        _assert_crew_group_exists(db, company_id, crew_group_id)
        row = (
            db.query(CrewGroupMember)
            .filter(CrewGroupMember.company_id == company_id)
            .filter(CrewGroupMember.crew_group_id == str(crew_group_id))
            .filter(CrewGroupMember.employee_id == int(employee_id))
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Crew group member not found")

        db.delete(row)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.post("/foundations/crew-groups/{crew_group_id}/assign", response_model=CrewGroupAssignResponse)
def assign_crew_group(
    crew_group_id: str,
    payload: CrewGroupAssignCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        _assert_crew_group_exists(db, company_id, crew_group_id)
        _assert_job_exists(db, company_id, int(payload.job_id))
        if payload.scope_id is not None:
            _assert_scope_exists(db, company_id, int(payload.scope_id), int(payload.job_id))

        members = (
            db.query(CrewGroupMember)
            .filter(CrewGroupMember.company_id == company_id)
            .filter(CrewGroupMember.crew_group_id == str(crew_group_id))
            .order_by(CrewGroupMember.created_at.asc(), CrewGroupMember.crew_group_member_id.asc())
            .all()
        )
        if not members:
            raise HTTPException(status_code=400, detail="Crew group has no members")

        employee_ids = [int(member.employee_id) for member in members]
        existing_rows = (
            db.query(CrewAssignment)
            .filter(CrewAssignment.company_id == company_id)
            .filter(CrewAssignment.job_id == int(payload.job_id))
            .filter(CrewAssignment.assigned_date == payload.assigned_date)
            .filter(CrewAssignment.scope_id == payload.scope_id)
            .filter(CrewAssignment.assignment_notes == payload.assignment_notes)
            .filter(CrewAssignment.employee_id.in_(employee_ids))
            .all()
        )
        existing_by_employee = {int(row.employee_id): row for row in existing_rows}

        created_rows: list[CrewAssignment] = []
        created_count = 0
        for employee_id in employee_ids:
            if employee_id in existing_by_employee:
                created_rows.append(existing_by_employee[employee_id])
                continue

            row = CrewAssignment(
                company_id=company_id,
                employee_id=employee_id,
                job_id=int(payload.job_id),
                scope_id=payload.scope_id,
                assigned_date=payload.assigned_date,
                assigned_by_user_id=get_actor_user_id(request),
                assignment_notes=payload.assignment_notes,
                status="ASSIGNED",
            )
            db.add(row)
            created_rows.append(row)
            created_count += 1

        db.commit()
        for row in created_rows:
            db.refresh(row)

        return CrewGroupAssignResponse(
            crew_group_id=str(crew_group_id),
            company_id=company_id,
            created_count=created_count,
            assignments=[_serialize_crew_assignment(row) for row in created_rows],
        )
    finally:
        db.close()


@router.post("/foundations/crew-assignments", response_model=CrewAssignmentResponse)
def create_crew_assignment(
    payload: CrewAssignmentCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        _assert_employee_exists(db, company_id, int(payload.employee_id))
        _assert_job_exists(db, company_id, int(payload.job_id))
        if payload.scope_id is not None:
            _assert_scope_exists(db, company_id, int(payload.scope_id), int(payload.job_id))

        row = CrewAssignment(
            company_id=company_id,
            employee_id=int(payload.employee_id),
            job_id=int(payload.job_id),
            scope_id=payload.scope_id,
            assigned_date=payload.assigned_date,
            assigned_by_user_id=get_actor_user_id(request),
            assignment_notes=payload.assignment_notes,
            status=str(payload.status),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_crew_assignment(row)
    finally:
        db.close()


@router.get("/foundations/crew-assignments", response_model=list[CrewAssignmentResponse])
def list_crew_assignments(
    request: Request,
    employee_id: int | None = Query(default=None),
    job_id: int | None = Query(default=None),
    scope_id: int | None = Query(default=None),
    assigned_date: date | None = Query(default=None),
    status: Literal["ASSIGNED", "ACKNOWLEDGED", "COMPLETED", "CANCELLED"] | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        query = db.query(CrewAssignment).filter(CrewAssignment.company_id == company_id)

        if employee_id is not None:
            query = query.filter(CrewAssignment.employee_id == int(employee_id))
        if job_id is not None:
            query = query.filter(CrewAssignment.job_id == int(job_id))
        if scope_id is not None:
            query = query.filter(CrewAssignment.scope_id == int(scope_id))
        if assigned_date is not None:
            query = query.filter(CrewAssignment.assigned_date == assigned_date)
        if status is not None:
            query = query.filter(CrewAssignment.status == str(status))

        rows = query.order_by(CrewAssignment.created_at.desc(), CrewAssignment.crew_assignment_id.asc()).all()
        return [_serialize_crew_assignment(row) for row in rows]
    finally:
        db.close()


@router.post("/foundations/crew-assignments/{assignment_id}/acknowledge", response_model=CrewAssignmentResponse)
def acknowledge_crew_assignment(
    assignment_id: str,
    payload: CrewAssignmentAcknowledgeCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        row = (
            db.query(CrewAssignment)
            .filter(CrewAssignment.company_id == company_id)
            .filter(CrewAssignment.crew_assignment_id == str(assignment_id))
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Crew assignment not found")

        _assert_employee_exists(db, company_id, int(payload.acknowledged_by_employee_id))

        if str(row.status) != "ASSIGNED":
            if str(row.status) == "ACKNOWLEDGED":
                raise HTTPException(status_code=409, detail="Assignment already acknowledged")
            raise HTTPException(status_code=409, detail="Only ASSIGNED assignments can be acknowledged")

        row.status = "ACKNOWLEDGED"
        row.acknowledged_at = datetime.now(timezone.utc)
        row.acknowledged_by_employee_id = int(payload.acknowledged_by_employee_id)

        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_crew_assignment(row)
    finally:
        db.close()


@router.post("/foundations/hazard-assessments", response_model=HazardAssessmentResponse)
def create_hazard_assessment(
    payload: HazardAssessmentCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        _assert_job_exists(db, company_id, int(payload.job_id))
        _assert_employee_exists(db, company_id, int(payload.completed_by_employee_id))

        if payload.scope_id is not None:
            _assert_scope_exists(db, company_id, int(payload.scope_id), int(payload.job_id))

        if payload.crew_assignment_id is not None:
            assignment = (
                db.query(CrewAssignment)
                .filter(CrewAssignment.company_id == company_id)
                .filter(CrewAssignment.crew_assignment_id == str(payload.crew_assignment_id))
                .one_or_none()
            )
            if assignment is None:
                raise HTTPException(status_code=404, detail="Crew assignment not found")

        row = HazardAssessment(
            company_id=company_id,
            job_id=int(payload.job_id),
            scope_id=payload.scope_id,
            crew_assignment_id=payload.crew_assignment_id,
            completed_by_employee_id=int(payload.completed_by_employee_id),
            assessment_date=payload.assessment_date,
            form_payload=payload.form_payload,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_hazard_assessment(row)
    finally:
        db.close()


@router.get("/foundations/hazard-assessments", response_model=list[HazardAssessmentResponse])
def list_hazard_assessments(
    request: Request,
    job_id: int | None = Query(default=None),
    scope_id: int | None = Query(default=None),
    completed_by_employee_id: int | None = Query(default=None),
    assessment_date: date | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        query = db.query(HazardAssessment).filter(HazardAssessment.company_id == company_id)

        if job_id is not None:
            query = query.filter(HazardAssessment.job_id == int(job_id))
        if scope_id is not None:
            query = query.filter(HazardAssessment.scope_id == int(scope_id))
        if completed_by_employee_id is not None:
            query = query.filter(HazardAssessment.completed_by_employee_id == int(completed_by_employee_id))
        if assessment_date is not None:
            query = query.filter(HazardAssessment.assessment_date == assessment_date)

        rows = query.order_by(HazardAssessment.created_at.desc(), HazardAssessment.hazard_assessment_id.asc()).all()
        return [_serialize_hazard_assessment(row) for row in rows]
    finally:
        db.close()


@router.post("/foundations/hazard-assessments/{hazard_assessment_id}/photos", response_model=HazardAssessmentPhotoResponse)
def create_hazard_assessment_photo(
    hazard_assessment_id: str,
    payload: HazardAssessmentPhotoCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        assessment = _get_hazard_assessment(db, company_id, hazard_assessment_id)
        row = JobDocument(
            company_id=company_id,
            job_id=int(assessment.job_id),
            scope_id=assessment.scope_id,
            hazard_assessment_id=str(assessment.hazard_assessment_id),
            document_type="ISSUE_PHOTO",
            file_name=str(payload.file_name),
            storage_key=str(payload.storage_key),
            caption=payload.caption,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_hazard_assessment_photo(row)
    finally:
        db.close()


@router.get("/foundations/hazard-assessments/{hazard_assessment_id}/photos", response_model=list[HazardAssessmentPhotoResponse])
def list_hazard_assessment_photos(
    hazard_assessment_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        _get_hazard_assessment(db, company_id, hazard_assessment_id)
        rows = (
            db.query(JobDocument)
            .filter(JobDocument.company_id == company_id)
            .filter(JobDocument.hazard_assessment_id == str(hazard_assessment_id))
            .filter(JobDocument.document_type == "ISSUE_PHOTO")
            .order_by(JobDocument.created_at.asc(), JobDocument.job_document_id.asc())
            .all()
        )
        return [_serialize_hazard_assessment_photo(row) for row in rows]
    finally:
        db.close()


@router.post(
    "/foundations/hazard-assessment-photos/uploads/prepare",
    response_model=HazardAssessmentPhotoUploadPrepareResponse,
)
def prepare_hazard_assessment_photo_upload(
    payload: HazardAssessmentPhotoUploadPrepareRequest,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        assessment = _get_hazard_assessment(db, company_id, str(payload.hazard_assessment_id))
        storage_key = build_storage_key(
            prefix="hazard-assessment-photos",
            company_id=company_id,
            context_id=f"hazard-assessments/{assessment.hazard_assessment_id}",
            file_name=str(payload.file_name),
        )
        return _serialize_hazard_assessment_photo_upload_prepare(storage_key)
    finally:
        db.close()


@router.get(
    "/foundations/hazard-assessment-photos/{photo_id}/access",
    response_model=HazardAssessmentPhotoAccessResponse,
)
def get_hazard_assessment_photo_access(
    photo_id: str,
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
            .filter(JobDocument.job_document_id == str(photo_id))
            .filter(JobDocument.document_type == "ISSUE_PHOTO")
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Hazard assessment photo not found")
        return _serialize_hazard_assessment_photo_access(row)
    finally:
        db.close()


@router.post("/foundations/toolbox-meetings", response_model=ToolboxMeetingResponse)
def create_toolbox_meeting(
    payload: ToolboxMeetingCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        _assert_employee_exists(db, company_id, int(payload.completed_by_employee_id))

        if payload.job_id is not None:
            _assert_job_exists(db, company_id, int(payload.job_id))

        if payload.scope_id is not None:
            _assert_scope_exists(db, company_id, int(payload.scope_id), payload.job_id)

        row = ToolboxMeeting(
            company_id=company_id,
            job_id=payload.job_id,
            scope_id=payload.scope_id,
            meeting_date=payload.meeting_date,
            completed_by_employee_id=int(payload.completed_by_employee_id),
            attendee_count=payload.attendee_count,
            form_payload=payload.form_payload,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_toolbox_meeting(row)
    finally:
        db.close()


@router.get("/foundations/toolbox-meetings", response_model=list[ToolboxMeetingResponse])
def list_toolbox_meetings(
    request: Request,
    job_id: int | None = Query(default=None),
    scope_id: int | None = Query(default=None),
    meeting_date: date | None = Query(default=None),
    completed_by_employee_id: int | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        query = db.query(ToolboxMeeting).filter(ToolboxMeeting.company_id == company_id)

        if job_id is not None:
            query = query.filter(ToolboxMeeting.job_id == int(job_id))
        if scope_id is not None:
            query = query.filter(ToolboxMeeting.scope_id == int(scope_id))
        if meeting_date is not None:
            query = query.filter(ToolboxMeeting.meeting_date == meeting_date)
        if completed_by_employee_id is not None:
            query = query.filter(ToolboxMeeting.completed_by_employee_id == int(completed_by_employee_id))

        rows = query.order_by(ToolboxMeeting.created_at.desc(), ToolboxMeeting.toolbox_meeting_id.asc()).all()
        return [_serialize_toolbox_meeting(row) for row in rows]
    finally:
        db.close()


@router.post("/foundations/messages", response_model=FoundationsMessageResponse)
def create_foundations_message(
    payload: FoundationsMessageCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        if payload.job_id is not None:
            _assert_job_exists(db, company_id, int(payload.job_id))
        if payload.scope_id is not None:
            _assert_scope_exists(db, company_id, int(payload.scope_id), payload.job_id)
        if payload.employee_id is not None:
            _assert_employee_exists(db, company_id, int(payload.employee_id))

        row = FoundationsMessage(
            company_id=company_id,
            job_id=payload.job_id,
            scope_id=payload.scope_id,
            employee_id=payload.employee_id,
            message_type=str(payload.message_type),
            subject=payload.subject,
            body=str(payload.body),
            created_by_user_id=get_actor_user_id(request),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_foundations_message(row)
    finally:
        db.close()


@router.get("/foundations/messages", response_model=list[FoundationsMessageResponse])
def list_foundations_messages(
    request: Request,
    employee_id: int | None = Query(default=None),
    job_id: int | None = Query(default=None),
    scope_id: int | None = Query(default=None),
    message_type: Literal["BROADCAST", "JOB_INSTRUCTION", "SAFETY_NOTICE"] | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        query = db.query(FoundationsMessage).filter(FoundationsMessage.company_id == company_id)
        if employee_id is not None:
            query = query.filter(FoundationsMessage.employee_id == int(employee_id))
        if job_id is not None:
            query = query.filter(FoundationsMessage.job_id == int(job_id))
        if scope_id is not None:
            query = query.filter(FoundationsMessage.scope_id == int(scope_id))
        if message_type is not None:
            query = query.filter(FoundationsMessage.message_type == str(message_type))

        rows = query.order_by(FoundationsMessage.created_at.desc(), FoundationsMessage.foundations_message_id.asc()).all()
        return [_serialize_foundations_message(row) for row in rows]
    finally:
        db.close()


@router.post("/foundations/activity", response_model=FoundationActivityResponse)
def create_foundation_activity(
    payload: FoundationActivityCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        _assert_employee_exists(db, company_id, int(payload.employee_id))
        _assert_job_exists(db, company_id, int(payload.job_id))
        _assert_scope_exists(db, company_id, int(payload.scope_id), int(payload.job_id))

        row = FoundationActivityLog(
            company_id=company_id,
            job_id=int(payload.job_id),
            scope_id=int(payload.scope_id),
            employee_id=int(payload.employee_id),
            activity_type=str(payload.activity_type),
            notes=payload.notes,
            photo_url=payload.photo_url,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_foundation_activity(row)
    finally:
        db.close()


@router.get("/foundations/activity", response_model=list[FoundationActivityResponse])
def list_foundation_activity(
    request: Request,
    job_id: int | None = Query(default=None),
    scope_id: int | None = Query(default=None),
    employee_id: int | None = Query(default=None),
    activity_type: Literal["CLOCK_IN", "CLOCK_OUT", "JOB_PROGRESS_PHOTO", "SITE_NOTE", "ISSUE_REPORTED"] | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        query = db.query(FoundationActivityLog).filter(FoundationActivityLog.company_id == company_id)
        if job_id is not None:
            query = query.filter(FoundationActivityLog.job_id == int(job_id))
        if scope_id is not None:
            query = query.filter(FoundationActivityLog.scope_id == int(scope_id))
        if employee_id is not None:
            query = query.filter(FoundationActivityLog.employee_id == int(employee_id))
        if activity_type is not None:
            query = query.filter(FoundationActivityLog.activity_type == str(activity_type))
        if date_from is not None:
            query = query.filter(FoundationActivityLog.created_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc))
        if date_to is not None:
            query = query.filter(FoundationActivityLog.created_at <= datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc))

        rows = query.order_by(FoundationActivityLog.created_at.desc(), FoundationActivityLog.foundation_activity_id.asc()).all()
        return [_serialize_foundation_activity(row) for row in rows]
    finally:
        db.close()


@router.get("/foundations/job-documents", response_model=list[FoundationsJobDocumentResponse])
def list_foundations_job_documents(
    request: Request,
    job_id: int | None = Query(default=None),
    scope_id: int | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        query = db.query(JobDocument).filter(JobDocument.company_id == company_id)
        if job_id is not None:
            query = query.filter(JobDocument.job_id == int(job_id))
        if scope_id is not None:
            query = query.filter(JobDocument.scope_id == int(scope_id))

        rows = query.order_by(JobDocument.created_at.desc(), JobDocument.job_document_id.asc()).all()
        return [_serialize_foundations_job_document(row) for row in rows]
    finally:
        db.close()


@router.post("/foundations/job-documents/{job_document_id}/deliver", response_model=JobDocumentDeliveryResponse)
def deliver_job_document(
    job_document_id: str,
    payload: JobDocumentDeliveryCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        document = (
            db.query(JobDocument)
            .filter(JobDocument.company_id == company_id)
            .filter(JobDocument.job_document_id == str(job_document_id))
            .one_or_none()
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Job document not found")

        _assert_employee_exists(db, company_id, int(payload.employee_id))

        row = JobDocumentDelivery(
            company_id=company_id,
            job_document_id=str(job_document_id),
            employee_id=int(payload.employee_id),
            delivered_at=payload.delivered_at,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_job_document_delivery(row)
    finally:
        db.close()


@router.get("/foundations/job-documents/deliveries", response_model=list[JobDocumentDeliveryResponse])
def list_job_document_deliveries(
    request: Request,
    employee_id: int | None = Query(default=None),
    job_id: int | None = Query(default=None),
    job_document_id: str | None = Query(default=None),
    viewed: bool | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        query = (
            db.query(JobDocumentDelivery)
            .join(JobDocument, JobDocument.job_document_id == JobDocumentDelivery.job_document_id)
            .filter(JobDocumentDelivery.company_id == company_id)
            .filter(JobDocument.company_id == company_id)
        )

        if employee_id is not None:
            query = query.filter(JobDocumentDelivery.employee_id == int(employee_id))
        if job_id is not None:
            query = query.filter(JobDocument.job_id == int(job_id))
        if job_document_id is not None:
            query = query.filter(JobDocumentDelivery.job_document_id == str(job_document_id))
        if viewed is not None:
            if viewed:
                query = query.filter(JobDocumentDelivery.viewed_at.isnot(None))
            else:
                query = query.filter(JobDocumentDelivery.viewed_at.is_(None))

        rows = query.order_by(JobDocumentDelivery.delivered_at.desc(), JobDocumentDelivery.job_document_delivery_id.asc()).all()
        return [_serialize_job_document_delivery(row) for row in rows]
    finally:
        db.close()


@router.post("/foundations/job-documents/deliveries/{delivery_id}/mark-viewed", response_model=JobDocumentDeliveryResponse)
def mark_job_document_delivery_viewed(
    delivery_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        row = (
            db.query(JobDocumentDelivery)
            .filter(JobDocumentDelivery.company_id == company_id)
            .filter(JobDocumentDelivery.job_document_delivery_id == str(delivery_id))
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Job document delivery not found")
        if row.viewed_at is not None:
            raise HTTPException(status_code=409, detail="Delivery already marked viewed")

        row.viewed_at = datetime.now(timezone.utc)
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize_job_document_delivery(row)
    finally:
        db.close()


@router.get("/foundations/compliance/hazard-assessments", response_model=list[HazardAssessmentResponse])
def list_compliance_hazard_assessments(
    request: Request,
    job_id: int | None = Query(default=None),
    scope_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    completed_by_employee_id: int | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        query = db.query(HazardAssessment).filter(HazardAssessment.company_id == company_id)
        if job_id is not None:
            query = query.filter(HazardAssessment.job_id == int(job_id))
        if scope_id is not None:
            query = query.filter(HazardAssessment.scope_id == int(scope_id))
        if completed_by_employee_id is not None:
            query = query.filter(HazardAssessment.completed_by_employee_id == int(completed_by_employee_id))
        if date_from is not None:
            query = query.filter(HazardAssessment.assessment_date >= date_from)
        if date_to is not None:
            query = query.filter(HazardAssessment.assessment_date <= date_to)

        rows = query.order_by(HazardAssessment.assessment_date.desc(), HazardAssessment.hazard_assessment_id.asc()).all()
        return [_serialize_hazard_assessment(row) for row in rows]
    finally:
        db.close()


@router.get("/foundations/compliance/toolbox-meetings", response_model=list[ToolboxMeetingResponse])
def list_compliance_toolbox_meetings(
    request: Request,
    job_id: int | None = Query(default=None),
    scope_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    completed_by_employee_id: int | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db: Session = SessionLocal()
    try:
        query = db.query(ToolboxMeeting).filter(ToolboxMeeting.company_id == company_id)
        if job_id is not None:
            query = query.filter(ToolboxMeeting.job_id == int(job_id))
        if scope_id is not None:
            query = query.filter(ToolboxMeeting.scope_id == int(scope_id))
        if completed_by_employee_id is not None:
            query = query.filter(ToolboxMeeting.completed_by_employee_id == int(completed_by_employee_id))
        if date_from is not None:
            query = query.filter(ToolboxMeeting.meeting_date >= date_from)
        if date_to is not None:
            query = query.filter(ToolboxMeeting.meeting_date <= date_to)

        rows = query.order_by(ToolboxMeeting.meeting_date.desc(), ToolboxMeeting.toolbox_meeting_id.asc()).all()
        return [_serialize_toolbox_meeting(row) for row in rows]
    finally:
        db.close()
