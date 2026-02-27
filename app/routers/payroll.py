from typing import Any, Optional, Union, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.authorization import Role, require_role
from app.database import SessionLocal
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun

router = APIRouter(prefix="/payroll", tags=["Payroll"])


class PayrollRunRow(BaseModel):
    payroll_run_id: str
    company_id: int
    pay_period_id: str
    status: str
    posted_at: Optional[str]
    created_at: Optional[str]


class PayrollRunsResponse(BaseModel):
    limit: int
    offset: int
    rows: list[PayrollRunRow]


class PayrollRunDetail(BaseModel):
    payroll_run_id: str
    company_id: int
    pay_period_id: str
    status: str
    posted_at: Optional[str]
    created_at: Optional[str]


class PayrollItemRow(BaseModel):
    id: int
    company_id: int
    payroll_run_id: str
    employee_id: int
    hours: Optional[str]
    rate_cents: Optional[int]
    gross_pay_cents: int
    meta: Optional[dict[str, Any]]
    created_at: str


class PayrollRunDetailResponse(BaseModel):
    payroll_run: PayrollRunDetail
    gross_total_cents: int
    items: list[PayrollItemRow]


class PayrollReconciliationOk(BaseModel):
    ok: Literal[True]
    payroll_total_cents: int
    ledger_total_cents: int
    delta_cents: int


class PayrollReconciliationError(BaseModel):
    ok: Literal[False]
    detail: str


PayrollReconciliationResponse = Union[PayrollReconciliationOk, PayrollReconciliationError]


@router.get("/runs", response_model=PayrollRunsResponse)
def list_payroll_runs(
    request: Request,
    status: Optional[str] = None,
    pay_period_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=1_000_000),
    _role=Depends(require_role(Role.MANAGER)),
):
    db: Session = SessionLocal()
    try:
        q = db.query(PayrollRun).filter(PayrollRun.company_id == int(request.state.company_id))

        if status is not None:
            q = q.filter(PayrollRun.status == str(status))

        if pay_period_id is not None:
            q = q.filter(PayrollRun.pay_period_id == str(pay_period_id))

        rows = (
            q.order_by(PayrollRun.posted_at.desc().nullslast(), PayrollRun.payroll_run_id.asc())
            .limit(int(limit))
            .offset(int(offset))
            .all()
        )

        return {
            "limit": int(limit),
            "offset": int(offset),
            "rows": [
                {
                    "payroll_run_id": r.payroll_run_id,
                    "company_id": r.company_id,
                    "pay_period_id": r.pay_period_id,
                    "status": r.status,
                    "posted_at": None if r.posted_at is None else r.posted_at.isoformat(),
                    "created_at": None if r.created_at is None else r.created_at.isoformat(),
                }
                for r in rows
            ],
        }
    finally:
        db.close()


@router.get("/runs/{payroll_run_id}", response_model=PayrollRunDetailResponse)
def get_payroll_run(
    payroll_run_id: str,
    request: Request,
    _role=Depends(require_role(Role.MANAGER)),
):
    db: Session = SessionLocal()
    try:
        pr = (
            db.query(PayrollRun)
            .filter(PayrollRun.company_id == int(request.state.company_id))
            .filter(PayrollRun.payroll_run_id == str(payroll_run_id))
            .one_or_none()
        )

        if pr is None:
            raise HTTPException(status_code=404, detail="Not found")

        items = (
            db.query(PayrollItem)
            .filter(PayrollItem.company_id == int(request.state.company_id))
            .filter(PayrollItem.payroll_run_id == str(payroll_run_id))
            .order_by(PayrollItem.id.asc())
            .all()
        )

        gross_total = (
            db.query(func.coalesce(func.sum(PayrollItem.gross_pay_cents), 0))
            .filter(PayrollItem.company_id == int(request.state.company_id))
            .filter(PayrollItem.payroll_run_id == str(payroll_run_id))
            .scalar()
        )

        return {
            "payroll_run": {
                "payroll_run_id": pr.payroll_run_id,
                "company_id": pr.company_id,
                "pay_period_id": pr.pay_period_id,
                "status": pr.status,
                "posted_at": None if pr.posted_at is None else pr.posted_at.isoformat(),
                "created_at": None if pr.created_at is None else pr.created_at.isoformat(),
            },
            "gross_total_cents": int(gross_total or 0),
            "items": [
                {
                    "id": i.id,
                    "company_id": i.company_id,
                    "payroll_run_id": i.payroll_run_id,
                    "employee_id": i.employee_id,
                    "hours": None if i.hours is None else str(i.hours),
                    "rate_cents": i.rate_cents,
                    "gross_pay_cents": i.gross_pay_cents,
                    "meta": i.meta,
                    "created_at": i.created_at.isoformat(),
                }
                for i in items
            ],
        }
    finally:
        db.close()


@router.get("/runs/{payroll_run_id}/reconciliation", response_model=PayrollReconciliationResponse)
def get_payroll_reconciliation(
    payroll_run_id: str,
    request: Request,
    _role=Depends(require_role(Role.MANAGER)),
):
    from app.services.reconciliation_service import reconcile_payroll_run_labor

    db: Session = SessionLocal()
    try:
        try:
            return reconcile_payroll_run_labor(
                company_id=int(request.state.company_id),
                payroll_run_id=str(payroll_run_id),
                db=db,
            )
        except ValueError as exc:
            return {"ok": False, "detail": str(exc)}
    finally:
        db.close()
