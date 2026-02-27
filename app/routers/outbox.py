from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.authorization import Role, require_role
from app.database import SessionLocal
from app.models.event_outbox import EventOutbox

router = APIRouter(prefix="/outbox", tags=["Outbox"])


@router.get("")
def list_outbox(
    request: Request,
    processed: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    _role=Depends(require_role(Role.MANAGER)),
):
    db: Session = SessionLocal()
    try:
        q = db.query(EventOutbox).filter(
            EventOutbox.company_id == int(request.state.company_id)
        )

        if processed is not None:
            q = q.filter(EventOutbox.processed == bool(processed))

        rows = (
            q.order_by(EventOutbox.id.asc())
            .limit(int(limit))
            .offset(int(offset))
            .all()
        )

        return {
            "limit": int(limit),
            "offset": int(offset),
            "rows": [
                {
                    "id": r.id,
                    "company_id": r.company_id,
                    "event_type": r.event_type,
                    "processed": r.processed,
                    "retry_count": r.retry_count,
                    "created_at": r.created_at.isoformat(),
                    "processed_at": None if r.processed_at is None else r.processed_at.isoformat(),
                }
                for r in rows
            ],
        }
    finally:
        db.close()
