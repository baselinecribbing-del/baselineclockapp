from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.database import SessionLocal
from app.deps.auth import require_auth
from app.models.job import Job
from app.models.time_entry import TimeEntry
from app.models.event_outbox import EventOutbox
from app.services import time_engine_v10

router = APIRouter(
    prefix="/time_entries",
    tags=["Time Entries"],
)


class ClockInRequest(BaseModel):
    employee_id: int
    job_id: int
    scope_id: int
    clock_in_lat: Optional[float] = None
    clock_in_lng: Optional[float] = None
    clock_in_accuracy_m: Optional[int] = None
    started_at: Optional[datetime] = Field(
        default=None,
        description="If omitted, server uses current UTC time.",
    )


class ClockOutRequest(BaseModel):
    employee_id: int
    ended_at: Optional[datetime] = Field(
        default=None,
        description="If omitted, server uses current UTC time.",
    )


class TimeEntryResponse(BaseModel):
    time_entry_id: str
    company_id: int
    employee_id: int
    job_id: int
    scope_id: int
    status: str
    started_at: datetime
    ended_at: Optional[datetime]
    clock_in_lat: Optional[float] = None
    clock_in_lng: Optional[float] = None
    clock_in_accuracy_m: Optional[int] = None
    clock_in_distance_m: Optional[int] = None
    clock_in_address: Optional[str] = None
    clock_in_address_source: Optional[str] = None


def _to_response(entry: TimeEntry) -> TimeEntryResponse:
    return TimeEntryResponse(
        time_entry_id=entry.time_entry_id,
        company_id=entry.company_id,
        employee_id=entry.employee_id,
        job_id=entry.job_id,
        scope_id=entry.scope_id,
        status=entry.status,
        started_at=entry.started_at,
        ended_at=entry.ended_at,
        clock_in_lat=float(entry.clock_in_lat) if entry.clock_in_lat is not None else None,
        clock_in_lng=float(entry.clock_in_lng) if entry.clock_in_lng is not None else None,
        clock_in_accuracy_m=entry.clock_in_accuracy_m,
        clock_in_distance_m=entry.clock_in_distance_m,
        clock_in_address=entry.clock_in_address,
        clock_in_address_source=entry.clock_in_address_source,
    )


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return int(round(r * c))


@router.get("", response_model=list[TimeEntryResponse])
def list_time_entries(
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
    employee_id: Optional[int] = Query(default=None),
    job_id: Optional[int] = Query(default=None),
    scope_id: Optional[int] = Query(default=None),
    status: Optional[Literal["active", "completed"]] = Query(default=None),
    started_at_from: Optional[datetime] = Query(default=None),
    started_at_to: Optional[datetime] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        q = db.query(TimeEntry).filter(TimeEntry.company_id == int(x_company_id))

        if employee_id is not None:
            q = q.filter(TimeEntry.employee_id == int(employee_id))
        if job_id is not None:
            q = q.filter(TimeEntry.job_id == int(job_id))
        if scope_id is not None:
            q = q.filter(TimeEntry.scope_id == int(scope_id))
        if status is not None:
            q = q.filter(TimeEntry.status == status)
        if started_at_from is not None:
            q = q.filter(TimeEntry.started_at >= started_at_from)
        if started_at_to is not None:
            q = q.filter(TimeEntry.started_at <= started_at_to)

        rows = (
            q.order_by(TimeEntry.started_at.desc())
            .offset(int(offset))
            .limit(int(limit))
            .all()
        )
        return [_to_response(r) for r in rows]
    finally:
        db.close()


@router.post("/clock_in", response_model=TimeEntryResponse)
def clock_in_endpoint(
    payload: ClockInRequest,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    started_at = payload.started_at or datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        dist: Optional[int] = None
        job = db.query(Job).filter(Job.company_id == int(x_company_id), Job.id == int(payload.job_id)).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        if job.site_lat is not None and job.site_lng is not None:
            if payload.clock_in_lat is None or payload.clock_in_lng is None:
                raise HTTPException(status_code=422, detail="clock_in_lat/clock_in_lng required for geofenced jobs")

            radius_m = job.site_radius_m or 1000
            dist = _haversine_m(
                float(payload.clock_in_lat),
                float(payload.clock_in_lng),
                float(job.site_lat),
                float(job.site_lng),
            )
            if dist > radius_m:
                raise HTTPException(status_code=403, detail="Clock-in outside job geofence")

        entry = time_engine_v10.clock_in(
            company_id=int(x_company_id),
            employee_id=int(payload.employee_id),
            job_id=int(payload.job_id),
            scope_id=int(payload.scope_id),
            started_at=started_at,
            db=db,
        )
        entry.clock_in_lat = payload.clock_in_lat
        entry.clock_in_lng = payload.clock_in_lng
        entry.clock_in_accuracy_m = payload.clock_in_accuracy_m
        entry.clock_in_distance_m = dist if dist is not None else None
        entry.clock_in_address = None
        entry.clock_in_address_source = None
        db.add(
            EventOutbox(
                company_id=int(x_company_id),
                event_type="TIME_ENTRY_CLOCKED_IN",
                idempotency_key=f"time_entry:{entry.time_entry_id}:clock_in",
                payload={
                    "time_entry_id": entry.time_entry_id,
                    "employee_id": entry.employee_id,
                    "job_id": entry.job_id,
                    "scope_id": entry.scope_id,
                    "started_at": entry.started_at.isoformat() if entry.started_at else None,
                    "clock_in_lat": entry.clock_in_lat,
                    "clock_in_lng": entry.clock_in_lng,
                    "clock_in_accuracy_m": entry.clock_in_accuracy_m,
                    "clock_in_distance_m": entry.clock_in_distance_m,
                },
            )
        )
        db.commit()
        db.refresh(entry)
        return _to_response(entry)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/clock_out", response_model=TimeEntryResponse)
def clock_out_endpoint(
    payload: ClockOutRequest,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    ended_at = payload.ended_at or datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        entry = time_engine_v10.clock_out(
            company_id=int(x_company_id),
            employee_id=int(payload.employee_id),
            ended_at=ended_at,
            db=db,
        )
        # durable outbox (same transaction as clock_out)
        db.add(
            EventOutbox(
                company_id=int(x_company_id),
                event_type="TIME_ENTRY_CLOCKED_OUT",
                idempotency_key=f"time_entry:{entry.time_entry_id}:clock_out",
                payload={
                    "time_entry_id": entry.time_entry_id,
                    "employee_id": entry.employee_id,
                    "job_id": entry.job_id,
                    "scope_id": entry.scope_id,
                    "started_at": entry.started_at.isoformat() if entry.started_at else None,
                    "ended_at": entry.ended_at.isoformat() if entry.ended_at else None,
                    "status": entry.status,
                },
            )
        )

        db.commit()
        db.refresh(entry)
        return _to_response(entry)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/active", response_model=TimeEntryResponse)
def get_active_time_entry(
    employee_id: int,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        entry = (
            db.query(TimeEntry)
            .filter(
                TimeEntry.company_id == int(x_company_id),
                TimeEntry.employee_id == int(employee_id),
                TimeEntry.status == "active",
            )
            .order_by(TimeEntry.started_at.desc())
            .first()
        )
        if entry is None:
            raise HTTPException(status_code=404, detail="No active time entry")
        return _to_response(entry)
    finally:
        db.close()


@router.get("/latest", response_model=TimeEntryResponse)
def get_latest_time_entry(
    employee_id: int,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        entry = (
            db.query(TimeEntry)
            .filter(
                TimeEntry.company_id == int(x_company_id),
                TimeEntry.employee_id == int(employee_id),
            )
            .order_by(TimeEntry.started_at.desc())
            .first()
        )
        if entry is None:
            raise HTTPException(status_code=404, detail="No time entries found")
        return _to_response(entry)
    finally:
        db.close()
