from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.database import SessionLocal
from app.deps.auth import require_auth
from app.models.job import Job
from app.schemas.job import JobCreate, JobResponse

router = APIRouter(prefix="/jobs", tags=["Jobs"])


def _to_response(row: Job) -> JobResponse:
    return JobResponse(
        id=row.id,
        company_id=row.company_id,
        name=row.name,
        is_active=row.is_active,
        created_at=row.created_at,
        site_lat=float(row.site_lat) if row.site_lat is not None else None,
        site_lng=float(row.site_lng) if row.site_lng is not None else None,
        site_radius_m=row.site_radius_m,
    )


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
            site_lat=payload.site_lat,
            site_lng=payload.site_lng,
            site_radius_m=payload.site_radius_m,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _to_response(row)
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
        return [_to_response(row) for row in rows]
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
        return _to_response(row)
    finally:
        db.close()
