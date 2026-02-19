from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel

from app.database import SessionLocal
from app.deps.auth import require_auth
from app.models.job_cost_ledger import JobCostLedger
from app.services import costing_service

router = APIRouter(prefix="/costing", tags=["Costing"])


class ProductionPostRequest(BaseModel):
    date_start: datetime
    date_end: datetime


@router.post("/post/labor/{pay_period_id}")
def post_labor(
    pay_period_id: int,
    request: Request,
    _auth: tuple[str, int] = Depends(require_auth),
):
    try:
        return costing_service.post_labor_costs(
            company_id=int(request.state.company_id),
            pay_period_id=pay_period_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/post/production")
def post_production(
    payload: ProductionPostRequest,
    request: Request,
    _auth: tuple[str, int] = Depends(require_auth),
):
    try:
        return costing_service.post_production_costs(
            company_id=int(request.state.company_id),
            date_start=payload.date_start,
            date_end=payload.date_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/job/{job_id}/ledger")
def get_job_ledger(
    job_id: int,
    request: Request,
    scope_id: Optional[int] = None,
    _auth: tuple[str, int] = Depends(require_auth),
):
    db = SessionLocal()
    try:
        q = db.query(JobCostLedger).filter(
            JobCostLedger.company_id == int(request.state.company_id),
            JobCostLedger.job_id == int(job_id),
        )
        if scope_id is not None:
            q = q.filter(JobCostLedger.scope_id == int(scope_id))

        rows = q.order_by(JobCostLedger.posting_date.asc(), JobCostLedger.id.asc()).all()

        return {
            "job_id": int(job_id),
            "scope_id": scope_id,
            "rows": [
                {
                    "id": r.id,
                    "company_id": r.company_id,
                    "job_id": r.job_id,
                    "scope_id": r.scope_id,
                    "employee_id": r.employee_id,
                    "source_type": r.source_type,
                    "source_reference_id": r.source_reference_id,
                    "cost_category": r.cost_category,
                    "quantity": None if r.quantity is None else str(r.quantity),
                    "unit_cost_cents": r.unit_cost_cents,
                    "total_cost_cents": r.total_cost_cents,
                    "posting_date": r.posting_date.isoformat(),
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ],
        }
    finally:
        db.close()
