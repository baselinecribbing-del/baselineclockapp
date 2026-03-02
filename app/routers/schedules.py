from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.database import SessionLocal
from app.deps.auth import require_auth
from app.models.schedule import Schedule

router = APIRouter(prefix="/schedules", tags=["Schedules"])


class CreateScheduleRequest(BaseModel):
    employee_id: int
    start_at: datetime
    end_at: Optional[datetime] = None
    status: str = Field(default="ACTIVE")


class ScheduleResponse(BaseModel):
    schedule_id: str
    company_id: int
    employee_id: int
    scheduled_date: date
    start_at: datetime
    end_at: Optional[datetime]
    status: str
    created_at: datetime


def _to_response(row: Schedule) -> ScheduleResponse:
    return ScheduleResponse(
        schedule_id=row.schedule_id,
        company_id=row.company_id,
        employee_id=row.employee_id,
        scheduled_date=row.scheduled_date,
        start_at=row.start_at,
        end_at=row.end_at,
        status=row.status,
        created_at=row.created_at,
    )


@router.post("", response_model=ScheduleResponse)
def create_schedule(
    payload: CreateScheduleRequest,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        row = Schedule(
            schedule_id=str(uuid4()),
            company_id=int(x_company_id),
            employee_id=int(payload.employee_id),
            scheduled_date=payload.start_at.date(),
            start_at=payload.start_at,
            end_at=payload.end_at,
            status=payload.status,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _to_response(row)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

@router.get("", response_model=list[ScheduleResponse])
def list_schedules(
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
    employee_id: Optional[int] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        q = db.query(Schedule).filter(Schedule.company_id == int(x_company_id))

        if employee_id is not None:
            q = q.filter(Schedule.employee_id == int(employee_id))
        if date_from is not None:
            q = q.filter(Schedule.scheduled_date >= date_from)
        if date_to is not None:
            q = q.filter(Schedule.scheduled_date <= date_to)

        rows = (
            q.order_by(Schedule.scheduled_date.desc(), Schedule.start_at.desc())
            .offset(int(offset))
            .limit(int(limit))
            .all()
        )
        return [_to_response(r) for r in rows]
    finally:
        db.close()
