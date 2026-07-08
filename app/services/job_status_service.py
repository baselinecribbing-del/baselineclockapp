from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.job_status_history import JobStatusHistory

JOB_STATUSES = ("QUEUED", "UPCOMING", "ACTIVE", "ON_HOLD", "COMPLETE")
INITIAL_JOB_STATUS = "QUEUED"

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "QUEUED": {"UPCOMING"},
    "UPCOMING": {"ACTIVE", "ON_HOLD"},
    "ACTIVE": {"ON_HOLD", "COMPLETE"},
    "ON_HOLD": {"ACTIVE"},
    "COMPLETE": set(),
}


@dataclass(frozen=True)
class JobTransitionResult:
    job: Job
    transition: JobStatusHistory


def _is_active_for_status(status: str) -> bool:
    return status != "COMPLETE"


def record_initial_job_status(
    *,
    db: Session,
    job: Job,
    note: str | None = None,
    transitioned_by_user_id: str | None = None,
) -> JobStatusHistory:
    _ = note, transitioned_by_user_id
    job.status = INITIAL_JOB_STATUS
    job.is_active = _is_active_for_status(INITIAL_JOB_STATUS)
    transition = JobStatusHistory(
        company_id=int(job.company_id),
        job_id=int(job.id),
        from_status=None,
        to_status=INITIAL_JOB_STATUS,
    )
    db.add(job)
    db.add(transition)
    return transition


def transition_job_status(
    *,
    db: Session,
    job: Job,
    target_status: str,
    note: str | None = None,
    transitioned_by_user_id: str | None = None,
) -> JobTransitionResult:
    _ = note, transitioned_by_user_id
    current_status = str(job.status)
    target_status_value = str(target_status)

    if target_status_value not in JOB_STATUSES:
        raise ValueError("Unsupported target status")
    if current_status == target_status_value:
        raise ValueError("Job is already in the requested status")
    if target_status_value not in _ALLOWED_TRANSITIONS.get(current_status, set()):
        raise ValueError(f"Invalid status transition from {current_status} to {target_status_value}")

    transition = JobStatusHistory(
        company_id=int(job.company_id),
        job_id=int(job.id),
        from_status=current_status,
        to_status=target_status_value,
    )
    job.status = target_status_value
    job.is_active = _is_active_for_status(target_status_value)
    db.add(job)
    db.add(transition)
    return JobTransitionResult(job=job, transition=transition)


def list_job_status_history(
    *,
    db: Session,
    company_id: int,
    job_id: int,
) -> list[JobStatusHistory]:
    return (
        db.query(JobStatusHistory)
        .filter(
            JobStatusHistory.company_id == int(company_id),
            JobStatusHistory.job_id == int(job_id),
        )
        .order_by(JobStatusHistory.changed_at.asc(), JobStatusHistory.id.asc())
        .all()
    )
