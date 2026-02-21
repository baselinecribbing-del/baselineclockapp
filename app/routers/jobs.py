from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.database import SessionLocal
from app.deps.auth import require_auth
from app.models.job import Job
from app.schemas.job import JobCreate, JobResponse

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("", response_model=JobResponse)
def create_job(
    payload: JobCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        row = Job(
            company_id=int(request.state.company_id),
            name=payload.name,
            is_active=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


@router.get("", response_model=List[JobResponse])
def list_jobs(
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        rows = (
            db.query(Job)
            .filter(Job.company_id == int(request.state.company_id))
            .order_by(Job.id.asc())
            .all()
        )
        return rows
    finally:
        db.close()


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: int,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        row = (
            db.query(Job)
            .filter(
                Job.id == int(job_id),
                Job.company_id == int(request.state.company_id),
            )
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return row
    finally:
        db.close()
