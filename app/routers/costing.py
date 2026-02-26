from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel

from app.core.authorization import Role, require_role
from app.database import SessionLocal
from app.models.job_cost_ledger import JobCostLedger
from app.services import costing_service
from app.services.ledger_reporting_service import job_cost_totals

router = APIRouter(prefix="/costing", tags=["Costing"])


class ProductionPostRequest(BaseModel):
    date_start: datetime
    date_end: datetime


@router.post("/post/labor/run/{payroll_run_id}")
def post_labor_for_run(
    payroll_run_id: str,
    request: Request,
    _role=Depends(require_role(Role.MANAGER)),
):
    db = SessionLocal()
    try:
        return costing_service.post_labor_costs(
            company_id=int(request.state.company_id),
            payroll_run_id=str(payroll_run_id),
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        db.close()


@router.post("/post/production")
def post_production(
    payload: ProductionPostRequest,
    request: Request,
    _role=Depends(require_role(Role.MANAGER)),
):
    # Placeholder: not implemented in this repo state.
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/job/{job_id}/ledger")
def get_job_ledger(
    job_id: int,
    request: Request,
    scope_id: Optional[int] = None,
    _role=Depends(require_role(Role.MANAGER)),
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


@router.get("/ledger/totals")
def get_ledger_totals(
    request: Request,
    date_start: datetime,
    date_end: datetime,
    job_id: Optional[int] = None,
    scope_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    cost_category: Optional[str] = None,
    source_type: Optional[str] = None,
    _role=Depends(require_role(Role.MANAGER)),
):
    db = SessionLocal()
    try:
        return job_cost_totals(
            company_id=int(request.state.company_id),
            date_start=date_start,
            date_end=date_end,
            db=db,
            job_id=job_id,
            scope_id=scope_id,
            employee_id=employee_id,
            cost_category=cost_category,
            source_type=source_type,
        )
    finally:
        db.close()
