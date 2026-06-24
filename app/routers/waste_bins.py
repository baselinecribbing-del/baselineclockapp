from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.deps.auth import require_auth
from app.deps.entitlements import require_company_module
from app.models.waste_bin import WasteBin
from app.schemas.waste_bins import WasteBinCreate, WasteBinResponse, WasteBinUpdate
from app.services.waste_bin_tracking_service import (
    assign_ticket_to_bin,
    ensure_site_belongs_to_company,
    ensure_ticket_assignable,
    validate_status_transition,
)

router = APIRouter(prefix="/waste_bins", tags=["Waste Bins"], dependencies=[Depends(require_company_module("waste_bins"))])


def _ensure_company(request: Request, x_company_id: int) -> int:
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")
    return int(request.state.company_id)


def _serialize(row: WasteBin) -> WasteBinResponse:
    return WasteBinResponse(
        id=str(row.id),
        company_id=int(row.company_id),
        bin_number=str(row.bin_number),
        capacity_yards=int(row.capacity_yards),
        status=str(row.status),
        current_site_id=row.current_site_id,
        current_ticket_id=row.current_ticket_id,
        last_service_at=row.last_service_at,
        created_at=row.created_at,
    )


@router.post("", response_model=WasteBinResponse)
def create_waste_bin(
    payload: WasteBinCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        if int(payload.capacity_yards) <= 0:
            raise HTTPException(status_code=422, detail="capacity_yards must be > 0")

        try:
            ensure_site_belongs_to_company(db=db, company_id=company_id, current_site_id=payload.current_site_id)
            ensure_ticket_assignable(db=db, company_id=company_id, ticket_id=payload.current_ticket_id)
        except ValueError as exc:
            detail = str(exc)
            if detail in {"Customer site not found", "Service ticket not found"}:
                raise HTTPException(status_code=404, detail=detail) from exc
            raise HTTPException(status_code=409, detail=detail) from exc

        row = WasteBin(
            company_id=company_id,
            bin_number=str(payload.bin_number),
            capacity_yards=int(payload.capacity_yards),
            status=str(payload.status),
            current_site_id=payload.current_site_id,
            current_ticket_id=payload.current_ticket_id,
            last_service_at=payload.last_service_at,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize(row)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        msg = str(getattr(exc, "orig", exc))
        if "uq_waste_bins_company_bin_number" in msg:
            raise HTTPException(status_code=409, detail="Bin number already exists for this company") from exc
        raise
    finally:
        db.close()


@router.get("", response_model=list[WasteBinResponse])
def list_waste_bins(
    request: Request,
    status: str | None = Query(default=None),
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        q = db.query(WasteBin).filter(WasteBin.company_id == company_id)
        if status is not None:
            q = q.filter(WasteBin.status == str(status))
        rows = q.order_by(WasteBin.created_at.desc(), WasteBin.id.asc()).all()
        return [_serialize(row) for row in rows]
    finally:
        db.close()


@router.get("/{bin_id}", response_model=WasteBinResponse)
def get_waste_bin(
    bin_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(WasteBin)
            .filter(WasteBin.company_id == company_id)
            .filter(WasteBin.id == str(bin_id))
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Waste bin not found")
        return _serialize(row)
    finally:
        db.close()


@router.patch("/{bin_id}", response_model=WasteBinResponse)
def patch_waste_bin(
    bin_id: str,
    payload: WasteBinUpdate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(WasteBin)
            .filter(WasteBin.company_id == company_id)
            .filter(WasteBin.id == str(bin_id))
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Waste bin not found")

        updates = payload.model_dump(exclude_unset=True)

        if "capacity_yards" in updates and int(updates["capacity_yards"]) <= 0:
            raise HTTPException(status_code=422, detail="capacity_yards must be > 0")

        new_status = str(updates["status"]) if "status" in updates else str(row.status)
        try:
            validate_status_transition(from_status=str(row.status), to_status=new_status)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        new_site = updates.get("current_site_id", row.current_site_id)
        new_ticket = updates.get("current_ticket_id", row.current_ticket_id)

        try:
            ensure_site_belongs_to_company(db=db, company_id=company_id, current_site_id=new_site)
            ensure_ticket_assignable(db=db, company_id=company_id, ticket_id=new_ticket)
        except ValueError as exc:
            detail = str(exc)
            if detail in {"Customer site not found", "Service ticket not found"}:
                raise HTTPException(status_code=404, detail=detail) from exc
            raise HTTPException(status_code=409, detail=detail) from exc

        if "bin_number" in updates:
            row.bin_number = str(updates["bin_number"])
        if "capacity_yards" in updates:
            row.capacity_yards = int(updates["capacity_yards"])
        row.status = new_status
        row.current_site_id = None if new_site is None else str(new_site)
        row.last_service_at = updates.get("last_service_at", row.last_service_at)

        try:
            assign_ticket_to_bin(db=db, company_id=company_id, waste_bin=row, new_ticket_id=new_ticket)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        db.commit()
        db.refresh(row)
        return _serialize(row)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        msg = str(getattr(exc, "orig", exc))
        if "uq_waste_bins_company_bin_number" in msg:
            raise HTTPException(status_code=409, detail="Bin number already exists for this company") from exc
        raise
    finally:
        db.close()
