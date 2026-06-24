from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func

from app.database import SessionLocal
from app.deps.access_control import require_operations_permission
from app.deps.auth import require_auth
from app.deps.entitlements import require_company_module
from app.models.crew import Crew
from app.models.crew_assignment import CrewAssignment
from app.models.crew_member import CrewMember
from app.models.employee import Employee
from app.models.job import Job
from app.models.time_entry import TimeEntry
from app.services.access_control_service import PrivilegedPermission

router = APIRouter(prefix="/field", tags=["Field"], dependencies=[Depends(require_company_module("field"))])


class CrewBoardRow(BaseModel):
    employee_id: int
    employee_name: str
    status: str
    crew_id: str | None
    crew_name: str | None
    job_id: int | None
    job_name: str | None
    job_address: str | None
    clock_in_time: str | None


class CrewBoardResponse(BaseModel):
    rows: list[CrewBoardRow]


@router.get("/crew-board", response_model=CrewBoardResponse)
def get_crew_board(
    request: Request,
    crew_id: str | None = Query(default=None),
    job_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
    _permission=Depends(require_operations_permission(PrivilegedPermission.FIELD_VIEW)),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    company_id = int(request.state.company_id)
    today = date.today()

    db = SessionLocal()
    try:
        active_member = (
            db.query(CrewMember)
            .filter(CrewMember.company_id == company_id, CrewMember.removed_at.is_(None))
            .subquery()
        )

        assigned_today = (
            db.query(CrewAssignment)
            .filter(CrewAssignment.company_id == company_id, CrewAssignment.assigned_date == today)
            .subquery()
        )

        active_time = (
            db.query(TimeEntry)
            .filter(TimeEntry.company_id == company_id, TimeEntry.status == "active")
            .subquery()
        )

        query = (
            db.query(
                Employee.id,
                Employee.name,
                Crew.crew_id,
                Crew.name,
                Job.id,
                Job.name,
                Job.address_label,
                active_time.c.started_at,
            )
            .select_from(Employee)
            .outerjoin(active_member, active_member.c.employee_id == Employee.id)
            .outerjoin(Crew, (Crew.company_id == company_id) & (Crew.crew_id == active_member.c.crew_id))
            .outerjoin(active_time, active_time.c.employee_id == Employee.id)
            .outerjoin(assigned_today, assigned_today.c.employee_id == Employee.id)
            .outerjoin(Job, (Job.company_id == company_id) & (Job.id == assigned_today.c.job_id))
            .filter(Employee.company_id == company_id, Employee.is_active.is_(True))
            .order_by(Employee.name.asc())
        )

        if crew_id is not None:
            query = query.filter(Crew.crew_id == str(crew_id))
        if job_id is not None:
            query = query.filter(Job.id == int(job_id))

        rows = query.all()
        out: list[CrewBoardRow] = []
        for row in rows:
            current_status = "CLOCKED_IN" if row[7] is not None else "OFF_SHIFT"
            if status and current_status != str(status):
                continue
            out.append(
                CrewBoardRow(
                    employee_id=int(row[0]),
                    employee_name=str(row[1]),
                    status=current_status,
                    crew_id=None if row[2] is None else str(row[2]),
                    crew_name=None if row[3] is None else str(row[3]),
                    job_id=None if row[4] is None else int(row[4]),
                    job_name=None if row[5] is None else str(row[5]),
                    job_address=row[6],
                    clock_in_time=None if row[7] is None else row[7].isoformat(),
                )
            )

        return CrewBoardResponse(rows=out)
    finally:
        db.close()
