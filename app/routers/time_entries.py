from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.database import SessionLocal
from app.deps.auth import require_auth
from app.models.time_entry import TimeEntry

router = APIRouter(
    prefix="/time_entries",
    tags=["Time Entries"],
)


@router.get("/active")
def get_active_time_entry(
    employee_id: int,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
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
    db.close()

    if entry is None:
        raise HTTPException(status_code=404, detail="No active time entry")

    return {
        "time_entry_id": entry.time_entry_id,
        "company_id": entry.company_id,
        "employee_id": entry.employee_id,
        "job_id": entry.job_id,
        "scope_id": entry.scope_id,
        "status": entry.status,
        "started_at": entry.started_at,
        "ended_at": entry.ended_at,
    }


@router.get("/latest")
def get_latest_time_entry(
    employee_id: int,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    entry = (
        db.query(TimeEntry)
        .filter(
            TimeEntry.company_id == int(x_company_id),
            TimeEntry.employee_id == int(employee_id),
        )
        .order_by(TimeEntry.started_at.desc())
        .first()
    )
    db.close()

    if entry is None:
        raise HTTPException(status_code=404, detail="No time entries found")

    return {
        "time_entry_id": entry.time_entry_id,
        "company_id": entry.company_id,
        "employee_id": entry.employee_id,
        "job_id": entry.job_id,
        "scope_id": entry.scope_id,
        "status": entry.status,
        "started_at": entry.started_at,
        "ended_at": entry.ended_at,
    }
