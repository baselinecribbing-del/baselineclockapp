from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.templating import Jinja2Templates

from app.database import SessionLocal
from app.deps.auth import require_auth
from app.models.workflow_execution import WorkflowExecution
from app.schemas.workflow_preview import StartExecutionRequest, SubmitStepRequest
from app.services import workflow_service

router = APIRouter(
    prefix="/preview",
    tags=["Preview"],
)

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "preview_templates")
)


def _serialize_step(step):
    return {
        "id": step.id,
        "label": step.label,
        "required": step.required,
        "read_only": step.read_only,
    }


def _load_execution_or_404(execution_id: str) -> WorkflowExecution:
    db = SessionLocal()
    execution = db.query(WorkflowExecution).filter_by(execution_id=execution_id).first()
    db.close()

    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    return execution


def _require_company_access(execution: WorkflowExecution, company_id: int):
    ctx = execution.context or {}
    exec_company_id = ctx.get("company_id")
    if exec_company_id is None:
        raise HTTPException(status_code=400, detail="Execution missing company_id context")

    if int(exec_company_id) != int(company_id):
        raise HTTPException(status_code=403, detail="Forbidden for this company")


def _build_execution_snapshot(execution_id: str) -> dict:
    execution = _load_execution_or_404(execution_id)

    current_step = None
    next_step = None

    if execution.status != "completed" and execution.current_step_id is not None:
        try:
            current_step_obj = workflow_service.get_current_step(execution_id)
            current_step = _serialize_step(current_step_obj)
        except ValueError:
            current_step = None

        try:
            next_step_obj = workflow_service.get_next_step(execution_id)
            next_step = None if next_step_obj is None else _serialize_step(next_step_obj)
        except ValueError:
            next_step = None

    return {
        "execution_id": execution.execution_id,
        "flow_name": execution.flow_name,
        "status": execution.status,
        "current_step": current_step,
        "next_step": next_step,
        "completed_steps": execution.completed_steps or [],
    }


@router.get("/health")
def preview_health():
    return {"ok": True}


@router.get("/flows")
def preview_flows():
    return {"flows": ["clock_in_flow", "clock_out_flow"]}


@router.get("/executions")
def list_executions(
    company_id: int,
    employee_id: int,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(company_id) or int(request.state.company_id) != int(company_id):
        raise HTTPException(status_code=403, detail="Forbidden for this company")

    db = SessionLocal()
    try:
        rows = (
            db.query(WorkflowExecution)
            .filter(WorkflowExecution.status == "in_progress")
            .order_by(WorkflowExecution.execution_id.desc())
            .limit(500)
            .all()
        )

        matches = []
        for ex in rows:
            ctx = ex.context or {}
            try:
                if int(ctx.get("company_id")) != int(company_id):
                    continue
                if int(ctx.get("employee_id")) != int(employee_id):
                    continue
            except (TypeError, ValueError):
                continue

            matches.append(_build_execution_snapshot(ex.execution_id))

        return {"executions": matches}
    finally:
        db.close()


@router.get("/reset")
def reset_executions(
    company_id: int,
    employee_id: int,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(company_id) or int(request.state.company_id) != int(company_id):
        raise HTTPException(status_code=403, detail="Forbidden for this company")

    db = SessionLocal()
    try:
        rows = (
            db.query(WorkflowExecution)
            .filter(WorkflowExecution.status == "in_progress")
            .order_by(WorkflowExecution.execution_id.desc())
            .limit(500)
            .all()
        )

        updated = 0
        for ex in rows:
            ctx = ex.context or {}
            try:
                if int(ctx.get("company_id")) != int(company_id):
                    continue
                if int(ctx.get("employee_id")) != int(employee_id):
                    continue
            except (TypeError, ValueError):
                continue

            ex.status = "cancelled"
            ex.current_step_id = None
            updated += 1

        if updated:
            db.commit()

        return {"reset": updated}
    finally:
        db.close()


@router.post("/start")
def start_workflow_execution(
    payload: StartExecutionRequest,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    if int(x_company_id) != int(payload.company_id) or int(request.state.company_id) != int(payload.company_id):
        raise HTTPException(status_code=403, detail="Forbidden for this company")

    try:
        execution = workflow_service.start_execution(
            flow_name=payload.flow_name,
            context={
                "company_id": payload.company_id,
                "employee_id": payload.employee_id,
                "job_id": payload.job_id,
                "scope_id": payload.scope_id,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "execution_id": execution.execution_id,
        "flow_name": execution.flow_name,
    }


@router.post("/{execution_id}/submit")
def submit_step(
    execution_id: str,
    payload: SubmitStepRequest,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    execution = _load_execution_or_404(execution_id)
    _require_company_access(execution, x_company_id)

    try:
        current_step = workflow_service.get_current_step(execution_id)
        workflow_service.submit_step(
            execution_id=execution_id,
            step_input={
                "step_id": current_step.id,
                "value": payload.value,
                "notes": payload.notes,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _build_execution_snapshot(execution_id)


@router.post("/{execution_id}/advance")
def advance_workflow(
    execution_id: str,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    execution = _load_execution_or_404(execution_id)
    _require_company_access(execution, x_company_id)

    try:
        workflow_service.advance_execution(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _build_execution_snapshot(execution_id)


@router.post("/{execution_id}/complete")
def complete_workflow(
    execution_id: str,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    execution = _load_execution_or_404(execution_id)
    _require_company_access(execution, x_company_id)

    try:
        workflow_service.complete_workflow(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _build_execution_snapshot(execution_id)


@router.get("/{execution_id}")
def get_execution_status(
    execution_id: str,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
):
    execution = _load_execution_or_404(execution_id)
    _require_company_access(execution, x_company_id)

    return _build_execution_snapshot(execution_id)
