from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.authorization import Role, require_role
from app.database import SessionLocal
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun

router = APIRouter(prefix="/payroll", tags=["Payroll"])


@router.get("/runs")
def list_payroll_runs(
    request: Request,
    status: Optional[str] = None,
    pay_period_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
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


@router.get("/runs/{payroll_run_id}")
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

@router.get("/runs/{payroll_run_id}/reconciliation")
def get_payroll_reconciliation(
    payroll_run_id: str,
    request: Request,
    _role=Depends(require_role(Role.MANAGER)),
):
    from app.services.reconciliation_service import reconcile_payroll_run_labor

    db: Session = SessionLocal()
    try:
        # We call the service but catch mismatch to report status instead of raising.
        try:
            result = reconcile_payroll_run_labor(
                company_id=int(request.state.company_id),
                payroll_run_id=str(payroll_run_id),
                db=db,
            )
            return result
        except ValueError as exc:
            # Extract numbers from message if possible
            msg = str(exc)
            return {
                "ok": False,
                "detail": msg,
            }
    finally:
        db.close()
