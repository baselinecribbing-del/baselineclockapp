import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.time_entry import TimeEntry
from app.models.workflow_execution import WorkflowExecution
from app.services import time_engine_v10 as time_engine


class Step:
    def __init__(self, id: str, label: str, required: bool = True, read_only: bool = False):
        self.id = id
        self.label = label
        self.required = required
        self.read_only = read_only


class Workflow:
    def __init__(self, name: str, steps):
        self.name = name
        self.steps = steps


clock_in_flow = Workflow(
    name="clock_in_flow",
    steps=[
        Step("confirm_employee", "Confirm Employee", required=True),
        Step("confirm_job", "Confirm Job", required=True),
        Step("confirm_scope", "Confirm Scope", required=True),
    ],
)

clock_out_flow = Workflow(
    name="clock_out_flow",
    steps=[
        Step("confirm_employee", "Confirm Employee", required=True),
        Step("confirm_clock_out", "Confirm Clock Out", required=True),
    ],
)

flows = {
    "clock_in_flow": clock_in_flow,
    "clock_out_flow": clock_out_flow,
}


def get_workflow(flow_name: str) -> Workflow:
    if flow_name not in flows:
        raise ValueError("Invalid workflow")
    return flows[flow_name]


def _get_db() -> Session:
    return SessionLocal()


def _utc_now():
    return datetime.now(timezone.utc)


def _require_company_employee_from_context(context: dict) -> tuple[int, int]:
    company_id = context.get("company_id")
    employee_id = context.get("employee_id")
    if company_id is None or employee_id is None:
        raise ValueError("Execution context missing company_id/employee_id")
    return int(company_id), int(employee_id)


def _has_active_execution(db: Session, company_id: int, employee_id: int) -> bool:
    rows = (
        db.query(WorkflowExecution)
        .filter(WorkflowExecution.status == "in_progress")
        .order_by(WorkflowExecution.execution_id.desc())
        .limit(200)
        .all()
    )

    for ex in rows:
        ctx = ex.context or {}
        try:
            if int(ctx.get("company_id")) == int(company_id) and int(ctx.get("employee_id")) == int(employee_id):
                return True
        except (TypeError, ValueError):
            continue

    return False


def _has_active_time_entry(db: Session, company_id: int, employee_id: int) -> bool:
    row = (
        db.query(TimeEntry)
        .filter(
            TimeEntry.company_id == int(company_id),
            TimeEntry.employee_id == int(employee_id),
            TimeEntry.status == "active",
        )
        .first()
    )
    return row is not None


def start_execution(flow_name: str, context: dict) -> WorkflowExecution:
    workflow = get_workflow(flow_name)

    company_id, employee_id = _require_company_employee_from_context(context)

    db = _get_db()
    try:
        # One active execution per employee/company
        if _has_active_execution(db, company_id=company_id, employee_id=employee_id):
            raise ValueError("Active workflow execution already exists for employee in company")

        # Workflow-level protection around time entry state
        if flow_name == "clock_in_flow":
            if _has_active_time_entry(db, company_id=company_id, employee_id=employee_id):
                raise ValueError("Active time entry already exists for employee in company")

        if flow_name == "clock_out_flow":
            if not _has_active_time_entry(db, company_id=company_id, employee_id=employee_id):
                raise ValueError("No active time entry found for employee in company")

        execution_id = str(uuid.uuid4())

        execution = WorkflowExecution(
            execution_id=execution_id,
            flow_name=flow_name,
            context=context,
            status="in_progress",
            current_step_id=workflow.steps[0].id,
            completed_steps=[],
        )

        db.add(execution)
        db.commit()
        db.refresh(execution)
        return execution
    finally:
        db.close()


def _get_execution(db: Session, execution_id: str) -> WorkflowExecution:
    execution = db.query(WorkflowExecution).filter_by(execution_id=execution_id).first()
    if execution is None:
        raise ValueError("Execution not found")
    return execution


def get_current_step(execution_id: str) -> Step:
    db = _get_db()
    try:
        execution = _get_execution(db, execution_id)
        workflow = get_workflow(execution.flow_name)

        for step in workflow.steps:
            if step.id == execution.current_step_id:
                return step

        raise ValueError("Current step not found")
    finally:
        db.close()


def get_next_step(execution_id: str) -> Optional[Step]:
    db = _get_db()
    try:
        execution = _get_execution(db, execution_id)
        workflow = get_workflow(execution.flow_name)

        for i, step in enumerate(workflow.steps):
            if step.id == execution.current_step_id:
                if i + 1 < len(workflow.steps):
                    return workflow.steps[i + 1]
                return None

        return None
    finally:
        db.close()


def submit_step(execution_id: str, step_input: dict):
    db = _get_db()
    try:
        execution = _get_execution(db, execution_id)
        step_id = step_input.get("step_id")

        if step_id != execution.current_step_id:
            raise ValueError("Invalid step submission")

        completed = execution.completed_steps or []
        if step_id not in completed:
            completed.append(step_id)
            execution.completed_steps = completed

        db.commit()
    finally:
        db.close()


def _finalize_time_engine(execution: WorkflowExecution):
    ctx = execution.context or {}

    company_id = ctx.get("company_id")
    employee_id = ctx.get("employee_id")
    job_id = ctx.get("job_id")
    scope_id = ctx.get("scope_id")

    if company_id is None or employee_id is None:
        raise ValueError("Execution context missing company_id/employee_id")

    company_id = int(company_id)
    employee_id = int(employee_id)

    now = _utc_now()

    if execution.flow_name == "clock_in_flow":
        if job_id is None or scope_id is None:
            raise ValueError("Clock-in requires job_id and scope_id in context")

        time_engine.clock_in(
            company_id=company_id,
            employee_id=employee_id,
            job_id=int(job_id),
            scope_id=int(scope_id),
            started_at=now,
        )

    if execution.flow_name == "clock_out_flow":
        time_engine.clock_out(
            company_id=company_id,
            employee_id=employee_id,
            ended_at=now,
        )


def advance_execution(execution_id: str):
    db = _get_db()
    try:
        execution = _get_execution(db, execution_id)
        workflow = get_workflow(execution.flow_name)

        current_step = None
        for step in workflow.steps:
            if step.id == execution.current_step_id:
                current_step = step
                break

        if current_step is None:
            raise ValueError("Current step not found")

        if current_step.required and current_step.id not in (execution.completed_steps or []):
            raise ValueError("Required step must be completed before advancing")

        # Determine next state without committing yet
        next_status = execution.status
        next_current_step_id = execution.current_step_id

        for i, step in enumerate(workflow.steps):
            if step.id == execution.current_step_id:
                if i + 1 < len(workflow.steps):
                    next_current_step_id = workflow.steps[i + 1].id
                else:
                    next_status = "completed"
                    next_current_step_id = None
                break

        # If completing, run time engine FIRST (rollback behavior)
        if next_status == "completed":
            _finalize_time_engine(execution)

        # Persist state after time engine succeeds
        execution.status = next_status
        execution.current_step_id = next_current_step_id
        db.commit()

    except Exception as exc:
        db.rollback()
        raise ValueError(str(exc)) from exc
    finally:
        db.close()


def complete_workflow(execution_id: str):
    db = _get_db()
    try:
        execution = _get_execution(db, execution_id)

        # Run time engine FIRST (rollback behavior)
        _finalize_time_engine(execution)

        execution.status = "completed"
        execution.current_step_id = None
        db.commit()

    except Exception as exc:
        db.rollback()
        raise ValueError(str(exc)) from exc
    finally:
        db.close()
