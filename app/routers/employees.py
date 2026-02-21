from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.database import SessionLocal
from app.deps.auth import require_auth
from app.models.employee import Employee
from app.schemas.employee import EmployeeCreate, EmployeeResponse

router = APIRouter(prefix="/employees", tags=["Employees"])


@router.post("", response_model=EmployeeResponse)
def create_employee(
    payload: EmployeeCreate,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        row = Employee(
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


@router.get("", response_model=List[EmployeeResponse])
def list_employees(
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        rows = (
            db.query(Employee)
            .filter(Employee.company_id == int(request.state.company_id))
            .order_by(Employee.id.asc())
            .all()
        )
        return rows
    finally:
        db.close()


@router.get("/{employee_id}", response_model=EmployeeResponse)
def get_employee(
    employee_id: int,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    db = SessionLocal()
    try:
        row = (
            db.query(Employee)
            .filter(
                Employee.id == int(employee_id),
                Employee.company_id == int(request.state.company_id),
            )
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Employee not found")
        return row
    finally:
        db.close()
