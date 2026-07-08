from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps.access_control import (
    AuthenticatedAccountContext,
    require_employee_pin_verified,
    require_employee_self_service,
    require_self_employee_access,
)
from app.models.employee import Employee
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.pay_period import PayPeriod
from app.models.payroll_run import PayrollRun
from app.models.payroll_t4 import PayrollT4
from app.models.paystub import Paystub
from app.models.time_entry import TimeEntry
from app.schemas.employee_self_service import (
    EmployeePinChangeRequest,
    EmployeePinResetRequest,
    EmployeePinSetRequest,
    EmployeePinStatusResponse,
    EmployeePinVerifyRequest,
    SelfServiceClockInRequest,
    SelfServiceClockOutRequest,
    SelfServiceDashboardResponse,
    SelfServiceEmployeeProfileResponse,
    SelfServicePaystubsResponse,
    SelfServiceT4Row,
    SelfServiceT4sResponse,
    SelfServiceTimeEntriesResponse,
)
from app.services import time_engine_v10
from app.services.employee_pin_service import (
    EmployeePinError,
    change_employee_pin,
    reset_employee_pin,
    set_employee_pin,
    verify_employee_pin,
)
from app.services.location import haversine_distance_m
from app.services.payroll_t4_output_service import mark_t4_employee_downloaded
from app.services.self_service_t4_service import acknowledge_self_service_t4
from app.services.payroll_t4_storage_service import load_t4_slip_artifact
from app.services.self_service_t4_service import list_self_service_t4s

router = APIRouter(prefix="/employee-self-service", tags=["Employee Self Service"])


def _serialize_self_service_t4_row(*, employee_id: int, row) -> dict[str, object]:
    return {
        "t4_id": row.t4_id,
        "tax_year": int(row.tax_year),
        "employment_income_cents": int(row.employment_income_cents),
        "cpp_contributions_cents": int(row.cpp_contributions_cents),
        "ei_premiums_cents": int(row.ei_premiums_cents),
        "income_tax_deducted_cents": int(row.income_tax_deducted_cents),
        "other_deductions_cents": int(row.other_deductions_cents),
        "generated_at": row.generated_at,
        "status": row.slip_status,
        "slip_file_name": row.slip_file_name,
        "slip_content_type": row.slip_content_type,
        "slip_byte_size": row.slip_byte_size,
        "slip_generated_at": row.slip_generated_at,
        "slip_available_at": row.slip_available_at,
        "delivery_status": row.delivery_status,
        "delivered_at": row.delivered_at,
        "employee_download_count": row.employee_download_count,
        "employee_first_downloaded_at": row.employee_first_downloaded_at,
        "employee_last_downloaded_at": row.employee_last_downloaded_at,
        "employee_acknowledged_at": row.employee_acknowledged_at,
        "slip_url": (
            None
            if row.slip_status != "AVAILABLE"
            else f"/employee-self-service/employees/{int(employee_id)}/t4s/{row.t4_id}/download"
        ),
    }


def _employee_or_404(*, db: Session, company_id: int, employee_id: int) -> Employee:
    employee = (
        db.query(Employee)
        .filter(Employee.company_id == int(company_id), Employee.id == int(employee_id))
        .one_or_none()
    )
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee


def _pin_error_response(exc: EmployeePinError) -> HTTPException:
    detail = {"code": exc.code, "message": exc.message}
    if exc.lockout_until is not None:
        detail["lockout_until"] = exc.lockout_until.isoformat()
    return HTTPException(status_code=423 if exc.code == "employee_pin_locked" else 400, detail=detail)


@router.post("/pin/set", response_model=EmployeePinStatusResponse, dependencies=[Depends(require_employee_self_service)])
def set_employee_pin_endpoint(
    payload: EmployeePinSetRequest,
    context: AuthenticatedAccountContext = Depends(require_employee_self_service),
    db: Session = Depends(get_db),
) -> EmployeePinStatusResponse:
    try:
        result = set_employee_pin(
            db=db,
            user_account_id=str(context.account.user_account_id),
            company_id=int(context.account.company_id),
            new_pin=payload.new_pin,
        )
    except EmployeePinError as exc:
        raise _pin_error_response(exc) from exc
    return EmployeePinStatusResponse(
        status="employee_pin_set",
        employee_pin_changed_at=result.account.employee_pin_changed_at,
    )


@router.post("/pin/verify", response_model=EmployeePinStatusResponse, dependencies=[Depends(require_employee_self_service)])
def verify_employee_pin_endpoint(
    payload: EmployeePinVerifyRequest,
    context: AuthenticatedAccountContext = Depends(require_employee_self_service),
    db: Session = Depends(get_db),
) -> EmployeePinStatusResponse:
    try:
        result = verify_employee_pin(
            db=db,
            user_account_id=str(context.account.user_account_id),
            company_id=int(context.account.company_id),
            pin=payload.pin,
        )
    except EmployeePinError as exc:
        raise _pin_error_response(exc) from exc
    return EmployeePinStatusResponse(
        status="employee_pin_verified",
        employee_pin_changed_at=result.account.employee_pin_changed_at,
        verified_at=result.verified_at,
    )


@router.post("/pin/change", response_model=EmployeePinStatusResponse, dependencies=[Depends(require_employee_self_service)])
def change_employee_pin_endpoint(
    payload: EmployeePinChangeRequest,
    context: AuthenticatedAccountContext = Depends(require_employee_self_service),
    db: Session = Depends(get_db),
) -> EmployeePinStatusResponse:
    try:
        result = change_employee_pin(
            db=db,
            user_account_id=str(context.account.user_account_id),
            company_id=int(context.account.company_id),
            current_pin=payload.current_pin,
            new_pin=payload.new_pin,
        )
    except EmployeePinError as exc:
        raise _pin_error_response(exc) from exc
    return EmployeePinStatusResponse(
        status="employee_pin_changed",
        employee_pin_changed_at=result.account.employee_pin_changed_at,
    )


@router.post("/pin/reset", response_model=EmployeePinStatusResponse, dependencies=[Depends(require_employee_self_service)])
def reset_employee_pin_endpoint(
    payload: EmployeePinResetRequest,
    context: AuthenticatedAccountContext = Depends(require_employee_self_service),
    db: Session = Depends(get_db),
) -> EmployeePinStatusResponse:
    try:
        result = reset_employee_pin(
            db=db,
            user_account_id=str(context.account.user_account_id),
            company_id=int(context.account.company_id),
            current_password=payload.current_password,
            new_pin=payload.new_pin,
        )
    except EmployeePinError as exc:
        raise _pin_error_response(exc) from exc
    return EmployeePinStatusResponse(
        status="employee_pin_reset",
        employee_pin_changed_at=result.account.employee_pin_changed_at,
    )


@router.get(
    "/employees/{employee_id}/profile",
    response_model=SelfServiceEmployeeProfileResponse,
    dependencies=[Depends(require_self_employee_access())],
)
def get_self_service_profile(
    employee_id: int,
    context: AuthenticatedAccountContext = Depends(require_self_employee_access()),
    db: Session = Depends(get_db),
) -> SelfServiceEmployeeProfileResponse:
    employee = _employee_or_404(db=db, company_id=int(context.account.company_id), employee_id=int(employee_id))
    return SelfServiceEmployeeProfileResponse(
        employee_id=int(employee.id),
        company_id=int(employee.company_id),
        name=str(employee.name),
        preferred_name=employee.preferred_name,
        phone=employee.phone,
        email=employee.email,
        employment_status=str(employee.employment_status),
        job_title=employee.job_title,
        department=employee.department,
    )


@router.get(
    "/employees/{employee_id}/dashboard",
    response_model=SelfServiceDashboardResponse,
    dependencies=[Depends(require_self_employee_access()), Depends(require_employee_pin_verified)],
)
def get_self_service_dashboard(
    employee_id: int,
    context: AuthenticatedAccountContext = Depends(require_self_employee_access()),
    db: Session = Depends(get_db),
) -> SelfServiceDashboardResponse:
    active_entry = (
        db.query(TimeEntry)
        .filter(
            TimeEntry.company_id == int(context.account.company_id),
            TimeEntry.employee_id == int(employee_id),
            TimeEntry.status == "active",
        )
        .order_by(TimeEntry.started_at.desc())
        .first()
    )
    recent_completed_entries = (
        db.query(TimeEntry)
        .filter(
            TimeEntry.company_id == int(context.account.company_id),
            TimeEntry.employee_id == int(employee_id),
            TimeEntry.status == "completed",
        )
        .count()
    )
    paystub_count = (
        db.query(Paystub)
        .filter(
            Paystub.company_id == int(context.account.company_id),
            Paystub.employee_id == int(employee_id),
        )
        .count()
    )
    return SelfServiceDashboardResponse(
        employee_id=int(employee_id),
        active_time_entry_id=None if active_entry is None else str(active_entry.time_entry_id),
        active_time_entry_started_at=None if active_entry is None else active_entry.started_at,
        recent_completed_entries=int(recent_completed_entries),
        paystub_count=int(paystub_count),
    )


@router.get(
    "/employees/{employee_id}/time-entries",
    response_model=SelfServiceTimeEntriesResponse,
    dependencies=[Depends(require_self_employee_access()), Depends(require_employee_pin_verified)],
)
def list_self_service_time_entries(
    employee_id: int,
    context: AuthenticatedAccountContext = Depends(require_self_employee_access()),
    db: Session = Depends(get_db),
) -> SelfServiceTimeEntriesResponse:
    rows = (
        db.query(TimeEntry)
        .filter(
            TimeEntry.company_id == int(context.account.company_id),
            TimeEntry.employee_id == int(employee_id),
        )
        .order_by(TimeEntry.started_at.desc(), TimeEntry.time_entry_id.desc())
        .all()
    )
    return SelfServiceTimeEntriesResponse(
        rows=[
            {
                "time_entry_id": str(row.time_entry_id),
                "status": str(row.status),
                "approval_status": str(row.approval_status),
                "job_id": int(row.job_id),
                "scope_id": int(row.scope_id),
                "started_at": row.started_at,
                "ended_at": row.ended_at,
            }
            for row in rows
        ]
    )


@router.post(
    "/employees/{employee_id}/clock-in",
    dependencies=[Depends(require_self_employee_access()), Depends(require_employee_pin_verified)],
)
def self_service_clock_in(
    employee_id: int,
    payload: SelfServiceClockInRequest,
    context: AuthenticatedAccountContext = Depends(require_self_employee_access()),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    job = db.query(Job).filter(Job.company_id == int(context.account.company_id), Job.id == int(payload.job_id)).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    dist: int | None = None
    if job.site_lat is not None and job.site_lng is not None:
        if payload.clock_in_lat is None or payload.clock_in_lng is None:
            raise HTTPException(status_code=422, detail="GPS location required for this job")
        radius_m = int(job.site_radius_m) if job.site_radius_m is not None else 500
        dist = int(round(haversine_distance_m(
            float(payload.clock_in_lat),
            float(payload.clock_in_lng),
            float(job.site_lat),
            float(job.site_lng),
        )))
        if dist > radius_m:
            raise HTTPException(status_code=409, detail="Employee outside job geofence")

    started_at = payload.started_at or datetime.now(timezone.utc)
    try:
        entry = time_engine_v10.clock_in(
            company_id=int(context.account.company_id),
            employee_id=int(employee_id),
            job_id=int(payload.job_id),
            scope_id=int(payload.scope_id),
            started_at=started_at,
            db=db,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    entry.clock_in_lat = payload.clock_in_lat
    entry.clock_in_lng = payload.clock_in_lng
    entry.clock_in_accuracy_m = payload.clock_in_accuracy_m
    entry.clock_in_distance_m = dist
    db.add(
        EventOutbox(
            company_id=int(context.account.company_id),
            event_type="TIME_ENTRY_CLOCKED_IN",
            idempotency_key=f"time_entry:{entry.time_entry_id}:clock_in",
            payload={
                "time_entry_id": str(entry.time_entry_id),
                "employee_id": int(employee_id),
                "job_id": int(payload.job_id),
                "scope_id": int(payload.scope_id),
                "started_at": entry.started_at.isoformat() if entry.started_at else None,
            },
        )
    )
    db.commit()
    db.refresh(entry)
    return {"time_entry_id": str(entry.time_entry_id), "status": str(entry.status)}


@router.post(
    "/employees/{employee_id}/clock-out",
    dependencies=[Depends(require_self_employee_access()), Depends(require_employee_pin_verified)],
)
def self_service_clock_out(
    employee_id: int,
    payload: SelfServiceClockOutRequest,
    context: AuthenticatedAccountContext = Depends(require_self_employee_access()),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    ended_at = payload.ended_at or datetime.now(timezone.utc)
    try:
        entry = time_engine_v10.clock_out(
            company_id=int(context.account.company_id),
            employee_id=int(employee_id),
            ended_at=ended_at,
            db=db,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(entry)
    return {"time_entry_id": str(entry.time_entry_id), "status": str(entry.status)}


@router.get(
    "/employees/{employee_id}/paystubs",
    response_model=SelfServicePaystubsResponse,
    dependencies=[Depends(require_self_employee_access()), Depends(require_employee_pin_verified)],
)
def list_self_service_paystubs(
    employee_id: int,
    context: AuthenticatedAccountContext = Depends(require_self_employee_access()),
    db: Session = Depends(get_db),
) -> SelfServicePaystubsResponse:
    rows = (
        db.query(Paystub, PayrollRun, PayPeriod)
        .join(
            PayrollRun,
            (PayrollRun.company_id == Paystub.company_id) & (PayrollRun.payroll_run_id == Paystub.payroll_run_id),
        )
        .outerjoin(
            PayPeriod,
            (PayPeriod.company_id == PayrollRun.company_id) & (PayPeriod.pay_period_id == PayrollRun.pay_period_id),
        )
        .filter(
            Paystub.company_id == int(context.account.company_id),
            Paystub.employee_id == int(employee_id),
        )
        .order_by(Paystub.created_at.desc(), Paystub.paystub_id.desc())
        .all()
    )
    return SelfServicePaystubsResponse(
        rows=[
            {
                "paystub_id": str(paystub.paystub_id),
                "payroll_run_id": str(paystub.payroll_run_id),
                "gross_pay_cents": int(paystub.gross_pay_cents),
                "total_deductions_cents": int(paystub.total_deductions_cents),
                "net_pay_cents": int(paystub.net_pay_cents),
                "delivery_status": str(paystub.delivery_status),
                "pay_period_start": None if pay_period is None else pay_period.start_date.isoformat(),
                "pay_period_end": None if pay_period is None else pay_period.end_date.isoformat(),
                "created_at": paystub.created_at,
            }
            for paystub, _payroll_run, pay_period in rows
        ]
    )


@router.get(
    "/employees/{employee_id}/t4s",
    response_model=SelfServiceT4sResponse,
    dependencies=[Depends(require_self_employee_access()), Depends(require_employee_pin_verified)],
)
def list_employee_self_service_t4s(
    employee_id: int,
    context: AuthenticatedAccountContext = Depends(require_self_employee_access()),
    db: Session = Depends(get_db),
) -> SelfServiceT4sResponse:
    _employee_or_404(db=db, company_id=int(context.account.company_id), employee_id=int(employee_id))
    rows = list_self_service_t4s(
        db=db,
        company_id=int(context.account.company_id),
        employee_id=int(employee_id),
    )
    return SelfServiceT4sResponse(
        rows=[_serialize_self_service_t4_row(employee_id=int(employee_id), row=row) for row in rows]
    )


@router.get(
    "/employees/{employee_id}/t4s/{t4_id}/download",
    dependencies=[Depends(require_self_employee_access()), Depends(require_employee_pin_verified)],
)
def download_employee_self_service_t4(
    employee_id: int,
    t4_id: str,
    context: AuthenticatedAccountContext = Depends(require_self_employee_access()),
    db: Session = Depends(get_db),
) -> Response:
    row = (
        db.query(PayrollT4)
        .filter(PayrollT4.company_id == int(context.account.company_id))
        .filter(PayrollT4.employee_id == int(employee_id))
        .filter(PayrollT4.t4_id == str(t4_id))
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="T4 record not found")
    artifact = load_t4_slip_artifact(row)
    if str(row.slip_status) != "AVAILABLE" or artifact is None:
        raise HTTPException(status_code=409, detail="T4 slip is not available")

    mark_t4_employee_downloaded(row, actor_user_id=str(context.account.user_account_id))
    db.commit()
    return Response(
        content=artifact.blob,
        media_type=artifact.content_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.file_name}"'},
    )


@router.post(
    "/employees/{employee_id}/t4s/{t4_id}/acknowledge",
    response_model=SelfServiceT4Row,
    dependencies=[Depends(require_self_employee_access()), Depends(require_employee_pin_verified)],
)
def acknowledge_employee_self_service_t4(
    employee_id: int,
    t4_id: str,
    context: AuthenticatedAccountContext = Depends(require_self_employee_access()),
    db: Session = Depends(get_db),
) -> SelfServiceT4Row:
    try:
        row, _changed = acknowledge_self_service_t4(
            db=db,
            company_id=int(context.account.company_id),
            employee_id=int(employee_id),
            t4_id=str(t4_id),
            actor_user_id=str(context.account.user_account_id),
        )
    except ValueError as exc:
        detail = str(exc)
        if detail == "T4 record not found":
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=409, detail=detail) from exc
    db.commit()
    refreshed = list_self_service_t4s(
        db=db,
        company_id=int(context.account.company_id),
        employee_id=int(employee_id),
    )
    response_row = next((item for item in refreshed if item.t4_id == str(t4_id)), None)
    if response_row is None:
        raise HTTPException(status_code=404, detail="T4 record not found")
    return SelfServiceT4Row(**_serialize_self_service_t4_row(employee_id=int(employee_id), row=response_row))
