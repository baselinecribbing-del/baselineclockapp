from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.database import SessionLocal
from app.deps.auth import require_auth
from app.models.crew import Crew
from app.models.crew_member import CrewMember
from app.models.employee import Employee
from app.schemas.crew import CrewCreate, CrewDetailResponse, CrewMemberCreate, CrewMemberResponse, CrewResponse

router = APIRouter(prefix="/crews", tags=["Crews"])


def _ensure_company(request: Request, x_company_id: int) -> int:
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")
    return int(request.state.company_id)


def _assert_employee_in_company(db, *, company_id: int, employee_id: int) -> None:
    row = (
        db.query(Employee)
        .filter(Employee.company_id == int(company_id), Employee.id == int(employee_id))
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Employee not found")


def _assert_crew_in_company(db, *, company_id: int, crew_id: str) -> Crew:
    row = (
        db.query(Crew)
        .filter(Crew.company_id == int(company_id), Crew.crew_id == str(crew_id))
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Crew not found")
    return row


@router.get("", response_model=list[CrewResponse])
def list_crews(
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db = SessionLocal()
    try:
        rows = (
            db.query(Crew)
            .filter(Crew.company_id == company_id)
            .order_by(Crew.is_active.desc(), Crew.created_at.desc(), Crew.crew_id.asc())
            .all()
        )
        return rows
    finally:
        db.close()


@router.post("", response_model=CrewResponse)
def create_crew(
    payload: CrewCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db = SessionLocal()
    try:
        if payload.supervisor_employee_id is not None:
            _assert_employee_in_company(db, company_id=company_id, employee_id=int(payload.supervisor_employee_id))

        row = Crew(
            company_id=company_id,
            name=str(payload.name),
            supervisor_employee_id=payload.supervisor_employee_id,
            is_active=bool(payload.is_active),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


@router.get("/{crew_id}", response_model=CrewDetailResponse)
def get_crew(
    crew_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db = SessionLocal()
    try:
        crew = _assert_crew_in_company(db, company_id=company_id, crew_id=crew_id)
        members = (
            db.query(CrewMember)
            .filter(CrewMember.company_id == company_id, CrewMember.crew_id == str(crew_id))
            .order_by(CrewMember.assigned_at.desc(), CrewMember.crew_member_id.asc())
            .all()
        )
        return CrewDetailResponse(
            crew=CrewResponse.model_validate(crew),
            members=[CrewMemberResponse.model_validate(row) for row in members],
        )
    finally:
        db.close()


@router.post("/{crew_id}/members", response_model=CrewMemberResponse)
def add_crew_member(
    crew_id: str,
    payload: CrewMemberCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db = SessionLocal()
    try:
        _assert_crew_in_company(db, company_id=company_id, crew_id=crew_id)
        _assert_employee_in_company(db, company_id=company_id, employee_id=int(payload.employee_id))

        existing_active = (
            db.query(CrewMember)
            .filter(
                CrewMember.company_id == company_id,
                CrewMember.crew_id == str(crew_id),
                CrewMember.employee_id == int(payload.employee_id),
                CrewMember.removed_at.is_(None),
            )
            .first()
        )
        if existing_active is not None:
            raise HTTPException(status_code=409, detail="Employee already active in crew")

        row = CrewMember(
            company_id=company_id,
            crew_id=str(crew_id),
            employee_id=int(payload.employee_id),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


@router.delete("/{crew_id}/members/{employee_id}", response_model=dict[str, bool])
def remove_crew_member(
    crew_id: str,
    employee_id: int,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    company_id = _ensure_company(request, x_company_id)
    db = SessionLocal()
    try:
        _assert_crew_in_company(db, company_id=company_id, crew_id=crew_id)

        row = (
            db.query(CrewMember)
            .filter(
                CrewMember.company_id == company_id,
                CrewMember.crew_id == str(crew_id),
                CrewMember.employee_id == int(employee_id),
                CrewMember.removed_at.is_(None),
            )
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Active crew member not found")

        row.removed_at = datetime.now(timezone.utc)
        db.add(row)
        db.commit()
        return {"ok": True}
    finally:
        db.close()
