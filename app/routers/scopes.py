from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.database import SessionLocal
from app.deps.auth import require_auth
from app.models.job import Job
from app.models.scope import Scope
from app.schemas.scope import ScopeCreate, ScopeResponse

router = APIRouter(prefix="/scopes", tags=["Scopes"])


@router.post("", response_model=ScopeResponse)
def create_scope(
    payload: ScopeCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        job = (
            db.query(Job)
            .filter(
                Job.id == int(payload.job_id),
                Job.company_id == int(request.state.company_id),
            )
            .first()
        )
        if job is None:
            raise HTTPException(status_code=400, detail="Invalid job_id")

        row = Scope(
            company_id=int(request.state.company_id),
            job_id=int(payload.job_id),
            name=payload.name,
            is_active=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


@router.get("", response_model=List[ScopeResponse])
def list_scopes(
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        rows = (
            db.query(Scope)
            .filter(Scope.company_id == int(request.state.company_id))
            .order_by(Scope.id.asc())
            .all()
        )
        return rows
    finally:
        db.close()


@router.get("/{scope_id}", response_model=ScopeResponse)
def get_scope(
    scope_id: int,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        row = (
            db.query(Scope)
            .filter(
                Scope.id == int(scope_id),
                Scope.company_id == int(request.state.company_id),
            )
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Scope not found")
        return row
    finally:
        db.close()
