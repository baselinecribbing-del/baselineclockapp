from datetime import datetime
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.authorization import Role, require_role
from app.database import SessionLocal
from app.models.job_cost_ledger import JobCostLedger
from app.services import costing_service
from app.services.ledger_reporting_service import (
    job_cost_daily_summary_by_category_source,
    job_cost_summary_by_source_type,
    job_cost_summary_by_source_reference,
    job_cost_summary_by_category_source,
    job_cost_totals,
)

router = APIRouter(prefix="/costing", tags=["Costing"])


def _validate_po_traceability_filters(
    *,
    cost_source: Optional[str],
    job_purchase_order_id: Optional[str],
) -> None:
    if job_purchase_order_id is None:
        return
    if cost_source is not None and str(cost_source) != "PO":
        raise HTTPException(
            status_code=400,
            detail="job_purchase_order_id is only valid when cost_source is omitted or 'PO'",
        )


# ---------- Ledger Row Models ----------

class LedgerRow(BaseModel):
    id: int
    company_id: int
    job_id: int
    scope_id: Optional[int]
    employee_id: Optional[int]
    source_type: str
    source_reference_id: str
    cost_category: str
    job_purchase_order_id: Optional[str]
    cost_source: str
    quantity: Optional[str]
    unit_cost_cents: Optional[int]
    total_cost_cents: int
    posting_date: str
    created_at: str


class LedgerResponse(BaseModel):
    job_id: int
    scope_id: Optional[int]
    limit: int
    offset: int
    rows: list[LedgerRow]


# ---------- Totals Models ----------

class LedgerTotalsGroup(BaseModel):
    job_id: int
    scope_id: Optional[int]
    employee_id: Optional[int]
    row_count: int
    total_cost_cents: int


class LedgerTotalsResponse(BaseModel):
    company_id: int
    date_start: str
    date_end: str
    filters: dict[str, Any]
    groups: list[LedgerTotalsGroup]


class JobCostSummaryGroup(BaseModel):
    cost_category: str
    cost_source: str
    row_count: int
    total_cost_cents: int


class JobCostSummaryResponse(BaseModel):
    company_id: int
    job_id: int
    scope_id: Optional[int]
    date_start: Optional[str]
    date_end: Optional[str]
    row_count: int
    total_cost_cents: int
    groups: list[JobCostSummaryGroup]


class JobCostDailySummaryGroup(BaseModel):
    posting_date: str
    cost_category: str
    cost_source: str
    row_count: int
    total_cost_cents: int


class JobCostDailySummaryResponse(BaseModel):
    company_id: int
    job_id: int
    scope_id: Optional[int]
    date_start: Optional[str]
    date_end: Optional[str]
    row_count: int
    total_cost_cents: int
    groups: list[JobCostDailySummaryGroup]


class JobCostSourceReferenceSummaryGroup(BaseModel):
    source_type: str
    source_reference_id: str
    cost_category: str
    cost_source: str
    job_purchase_order_id: Optional[str]
    row_count: int
    total_cost_cents: int


class JobCostSourceReferenceSummaryResponse(BaseModel):
    company_id: int
    job_id: int
    scope_id: Optional[int]
    date_start: Optional[str]
    date_end: Optional[str]
    filters: dict[str, Any]
    row_count: int
    total_cost_cents: int
    groups: list[JobCostSourceReferenceSummaryGroup]


class JobCostSourceTypeSummaryGroup(BaseModel):
    source_type: str
    cost_category: str
    cost_source: str
    row_count: int
    total_cost_cents: int


class JobCostSourceTypeSummaryResponse(BaseModel):
    company_id: int
    job_id: int
    scope_id: Optional[int]
    date_start: Optional[str]
    date_end: Optional[str]
    filters: dict[str, Any]
    row_count: int
    total_cost_cents: int
    groups: list[JobCostSourceTypeSummaryGroup]


# ---------- Endpoints ----------

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


@router.get("/job/{job_id}/ledger", response_model=LedgerResponse)
def get_job_ledger(
    job_id: int,
    request: Request,
    scope_id: Optional[int] = None,
    cost_source: Optional[str] = None,
    job_purchase_order_id: Optional[str] = None,
    date_start: Optional[datetime] = None,
    date_end: Optional[datetime] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=1_000_000),
    _role=Depends(require_role(Role.MANAGER)),
):
    db = SessionLocal()
    try:
        _validate_po_traceability_filters(
            cost_source=cost_source,
            job_purchase_order_id=job_purchase_order_id,
        )

        q = db.query(JobCostLedger).filter(
            JobCostLedger.company_id == int(request.state.company_id),
            JobCostLedger.job_id == int(job_id),
        )

        if scope_id is not None:
            q = q.filter(JobCostLedger.scope_id == int(scope_id))
        if cost_source is not None:
            q = q.filter(JobCostLedger.cost_source == str(cost_source))
        if job_purchase_order_id is not None:
            q = q.filter(JobCostLedger.job_purchase_order_id == str(job_purchase_order_id))
        if date_start is not None:
            q = q.filter(JobCostLedger.posting_date >= date_start)
        if date_end is not None:
            q = q.filter(JobCostLedger.posting_date < date_end)

        rows = (
            q.order_by(JobCostLedger.posting_date.asc(), JobCostLedger.id.asc())
            .limit(int(limit))
            .offset(int(offset))
            .all()
        )

        return {
            "job_id": int(job_id),
            "scope_id": scope_id,
            "limit": int(limit),
            "offset": int(offset),
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
                    "job_purchase_order_id": r.job_purchase_order_id,
                    "cost_source": r.cost_source,
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


@router.get("/job/{job_id}/summary", response_model=JobCostSummaryResponse)
def get_job_cost_summary(
    job_id: int,
    request: Request,
    scope_id: Optional[int] = None,
    date_start: Optional[datetime] = None,
    date_end: Optional[datetime] = None,
    _role=Depends(require_role(Role.MANAGER)),
):
    db = SessionLocal()
    try:
        return job_cost_summary_by_category_source(
            company_id=int(request.state.company_id),
            job_id=int(job_id),
            scope_id=scope_id,
            date_start=date_start,
            date_end=date_end,
            db=db,
        )
    finally:
        db.close()


@router.get("/job/{job_id}/summary/daily", response_model=JobCostDailySummaryResponse)
def get_job_cost_daily_summary(
    job_id: int,
    request: Request,
    scope_id: Optional[int] = None,
    date_start: Optional[datetime] = None,
    date_end: Optional[datetime] = None,
    _role=Depends(require_role(Role.MANAGER)),
):
    db = SessionLocal()
    try:
        return job_cost_daily_summary_by_category_source(
            company_id=int(request.state.company_id),
            job_id=int(job_id),
            scope_id=scope_id,
            date_start=date_start,
            date_end=date_end,
            db=db,
        )
    finally:
        db.close()


@router.get("/job/{job_id}/summary/sources", response_model=JobCostSourceReferenceSummaryResponse)
def get_job_cost_source_reference_summary(
    job_id: int,
    request: Request,
    scope_id: Optional[int] = None,
    date_start: Optional[datetime] = None,
    date_end: Optional[datetime] = None,
    cost_category: Optional[str] = None,
    cost_source: Optional[str] = None,
    source_type: Optional[str] = None,
    job_purchase_order_id: Optional[str] = None,
    _role=Depends(require_role(Role.MANAGER)),
):
    db = SessionLocal()
    try:
        _validate_po_traceability_filters(
            cost_source=cost_source,
            job_purchase_order_id=job_purchase_order_id,
        )

        return job_cost_summary_by_source_reference(
            company_id=int(request.state.company_id),
            job_id=int(job_id),
            scope_id=scope_id,
            date_start=date_start,
            date_end=date_end,
            cost_category=cost_category,
            cost_source=cost_source,
            source_type=source_type,
            job_purchase_order_id=job_purchase_order_id,
            db=db,
        )
    finally:
        db.close()


@router.get("/job/{job_id}/summary/source-types", response_model=JobCostSourceTypeSummaryResponse)
def get_job_cost_source_type_summary(
    job_id: int,
    request: Request,
    scope_id: Optional[int] = None,
    date_start: Optional[datetime] = None,
    date_end: Optional[datetime] = None,
    cost_category: Optional[str] = None,
    cost_source: Optional[str] = None,
    job_purchase_order_id: Optional[str] = None,
    _role=Depends(require_role(Role.MANAGER)),
):
    db = SessionLocal()
    try:
        _validate_po_traceability_filters(
            cost_source=cost_source,
            job_purchase_order_id=job_purchase_order_id,
        )

        return job_cost_summary_by_source_type(
            company_id=int(request.state.company_id),
            job_id=int(job_id),
            scope_id=scope_id,
            date_start=date_start,
            date_end=date_end,
            cost_category=cost_category,
            cost_source=cost_source,
            job_purchase_order_id=job_purchase_order_id,
            db=db,
        )
    finally:
        db.close()


@router.get("/ledger/totals", response_model=LedgerTotalsResponse)
def get_ledger_totals(
    request: Request,
    date_start: datetime,
    date_end: datetime,
    job_id: Optional[int] = None,
    scope_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    cost_category: Optional[str] = None,
    source_type: Optional[str] = None,
    cost_source: Optional[str] = None,
    job_purchase_order_id: Optional[str] = None,
    _role=Depends(require_role(Role.MANAGER)),
):
    db = SessionLocal()
    try:
        _validate_po_traceability_filters(
            cost_source=cost_source,
            job_purchase_order_id=job_purchase_order_id,
        )

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
            cost_source=cost_source,
            job_purchase_order_id=job_purchase_order_id,
        )
    finally:
        db.close()
