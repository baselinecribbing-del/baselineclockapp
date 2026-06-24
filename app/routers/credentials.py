from datetime import date
from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.database import SessionLocal
from app.deps.auth import require_auth
from app.deps.entitlements import require_company_module
from app.models.credential_type import CredentialType
from app.models.employee import Employee
from app.models.employee_credential import EmployeeCredential
from app.models.job import Job
from app.models.job_trade_requirement import JobTradeRequirement
from app.models.scope import Scope
from app.models.trade_type import TradeType
from app.schemas.credential import (
    CredentialCategory,
    CredentialTypeResponse,
    EmployeeCredentialCreate,
    EmployeeCredentialResponse,
    EmployeeCredentialUpdate,
    JobTradeRequirementCreate,
    JobTradeRequirementResponse,
    TradeTypeResponse,
    VerificationStatus,
)

router = APIRouter(
    prefix="/credentials",
    tags=["Credentials"],
    dependencies=[Depends(require_company_module("credentials"))],
)


def _ensure_company(request: Request, x_company_id: int) -> int:
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")
    return int(request.state.company_id)


def _validate_employee_company(db, company_id: int, employee_id: int) -> None:
    employee = (
        db.query(Employee)
        .filter(Employee.company_id == company_id, Employee.id == int(employee_id))
        .first()
    )
    if employee is None:
        raise HTTPException(status_code=400, detail="Invalid employee_id")


def _validate_job_company(db, company_id: int, job_id: int) -> None:
    job = db.query(Job).filter(Job.company_id == company_id, Job.id == int(job_id)).first()
    if job is None:
        raise HTTPException(status_code=400, detail="Invalid job_id")


def _validate_scope_company(db, company_id: int, scope_id: int, job_id: int | None = None) -> None:
    query = db.query(Scope).filter(Scope.company_id == company_id, Scope.id == int(scope_id))
    if job_id is not None:
        query = query.filter(Scope.job_id == int(job_id))

    scope = query.first()
    if scope is None:
        raise HTTPException(status_code=400, detail="Invalid scope_id")


def _validate_trade_type(db, trade_type_id: str) -> None:
    trade_type = db.query(TradeType).filter(TradeType.trade_type_id == str(trade_type_id)).first()
    if trade_type is None:
        raise HTTPException(status_code=400, detail="Invalid trade_type_id")


def _validate_credential_type(db, credential_type_id: str) -> None:
    credential_type = (
        db.query(CredentialType)
        .filter(CredentialType.credential_type_id == str(credential_type_id))
        .first()
    )
    if credential_type is None:
        raise HTTPException(status_code=400, detail="Invalid credential_type_id")


@router.get("/trade-types", response_model=List[TradeTypeResponse])
def list_trade_types(
    request: Request,
    is_active: bool | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    _ensure_company(request, x_company_id)

    db = SessionLocal()
    try:
        query = db.query(TradeType)
        if is_active is not None:
            query = query.filter(TradeType.is_active == bool(is_active))
        return query.order_by(TradeType.name.asc()).all()
    finally:
        db.close()


@router.get("/credential-types", response_model=List[CredentialTypeResponse])
def list_credential_types(
    request: Request,
    category: CredentialCategory | None = Query(default=None),
    is_company_level: bool | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    _ensure_company(request, x_company_id)

    db = SessionLocal()
    try:
        query = db.query(CredentialType)
        if category is not None:
            query = query.filter(CredentialType.category == str(category))
        if is_company_level is not None:
            query = query.filter(CredentialType.is_company_level == bool(is_company_level))
        if is_active is not None:
            query = query.filter(CredentialType.is_active == bool(is_active))
        return query.order_by(CredentialType.name.asc()).all()
    finally:
        db.close()


@router.post("/employee", response_model=EmployeeCredentialResponse)
def create_employee_credential(
    payload: EmployeeCredentialCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db = SessionLocal()
    try:
        _validate_employee_company(db, company_id, int(payload.employee_id))
        _validate_credential_type(db, str(payload.credential_type_id))

        row = EmployeeCredential(
            company_id=company_id,
            employee_id=int(payload.employee_id),
            credential_type_id=str(payload.credential_type_id),
            certificate_number=payload.certificate_number,
            issued_date=payload.issued_date,
            expiry_date=payload.expiry_date,
            document_url=payload.document_url,
            verification_status=str(payload.verification_status),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


@router.get("/employee", response_model=List[EmployeeCredentialResponse])
def list_employee_credentials(
    request: Request,
    employee_id: int | None = Query(default=None),
    credential_type_id: str | None = Query(default=None),
    verification_status: VerificationStatus | None = Query(default=None),
    expires_before: date | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db = SessionLocal()
    try:
        query = db.query(EmployeeCredential).filter(EmployeeCredential.company_id == company_id)

        if employee_id is not None:
            query = query.filter(EmployeeCredential.employee_id == int(employee_id))
        if credential_type_id is not None:
            query = query.filter(EmployeeCredential.credential_type_id == str(credential_type_id))
        if verification_status is not None:
            query = query.filter(EmployeeCredential.verification_status == str(verification_status))
        if expires_before is not None:
            query = query.filter(
                EmployeeCredential.expiry_date.isnot(None),
                EmployeeCredential.expiry_date <= expires_before,
            )

        return (
            query.order_by(EmployeeCredential.created_at.desc(), EmployeeCredential.employee_credential_id.asc()).all()
        )
    finally:
        db.close()


@router.patch("/employee/{employee_credential_id}", response_model=EmployeeCredentialResponse)
def update_employee_credential(
    employee_credential_id: str,
    payload: EmployeeCredentialUpdate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db = SessionLocal()
    try:
        row = (
            db.query(EmployeeCredential)
            .filter(
                EmployeeCredential.employee_credential_id == str(employee_credential_id),
                EmployeeCredential.company_id == company_id,
            )
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Employee credential not found")

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No update fields provided")

        for key, value in updates.items():
            setattr(row, key, value)

        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


@router.post("/job-requirements", response_model=JobTradeRequirementResponse)
def create_job_trade_requirement(
    payload: JobTradeRequirementCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db = SessionLocal()
    try:
        _validate_job_company(db, company_id, int(payload.job_id))
        if payload.scope_id is not None:
            _validate_scope_company(db, company_id, int(payload.scope_id), int(payload.job_id))
        _validate_trade_type(db, str(payload.trade_type_id))
        _validate_credential_type(db, str(payload.credential_type_id))

        row = JobTradeRequirement(
            company_id=company_id,
            job_id=int(payload.job_id),
            scope_id=payload.scope_id,
            trade_type_id=str(payload.trade_type_id),
            credential_type_id=str(payload.credential_type_id),
            is_required=bool(payload.is_required),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


@router.get("/job-requirements", response_model=List[JobTradeRequirementResponse])
def list_job_trade_requirements(
    request: Request,
    job_id: int | None = Query(default=None),
    scope_id: int | None = Query(default=None),
    trade_type_id: str | None = Query(default=None),
    credential_type_id: str | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)

    db = SessionLocal()
    try:
        query = db.query(JobTradeRequirement).filter(JobTradeRequirement.company_id == company_id)

        if job_id is not None:
            query = query.filter(JobTradeRequirement.job_id == int(job_id))
        if scope_id is not None:
            query = query.filter(JobTradeRequirement.scope_id == int(scope_id))
        if trade_type_id is not None:
            query = query.filter(JobTradeRequirement.trade_type_id == str(trade_type_id))
        if credential_type_id is not None:
            query = query.filter(JobTradeRequirement.credential_type_id == str(credential_type_id))

        return (
            query.order_by(
                JobTradeRequirement.created_at.desc(),
                JobTradeRequirement.job_trade_requirement_id.asc(),
            ).all()
        )
    finally:
        db.close()
