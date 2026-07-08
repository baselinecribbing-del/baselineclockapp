from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps.access_control import require_operations_permission
from app.deps.auth import require_auth
from app.schemas.ledger import JournalPostErrorResponse, JournalPostResponse
from app.services.journal_posting_service import (
    ERROR_CODE_DB_GUARD,
    ERROR_CODE_INVALID_STATE,
    ERROR_CODE_NO_LINES,
    ERROR_CODE_NOT_FOUND,
    ERROR_CODE_PERIOD_CLOSED,
    ERROR_CODE_PERSISTENCE,
    ERROR_CODE_UNBALANCED,
    JournalPostingApplicationError,
    post_journal_entry_with_audit,
)
from app.services.access_control_service import PrivilegedPermission

router = APIRouter(prefix="/ledger", tags=["Ledger"])


def _ensure_company(request: Request, x_company_id: int) -> int:
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")
    return int(request.state.company_id)


def _status_for_error_code(code: str) -> int:
    if code == ERROR_CODE_NOT_FOUND:
        return 404
    if code in {
        ERROR_CODE_INVALID_STATE,
        ERROR_CODE_NO_LINES,
        ERROR_CODE_UNBALANCED,
        ERROR_CODE_PERIOD_CLOSED,
        ERROR_CODE_DB_GUARD,
    }:
        return 409
    if code == ERROR_CODE_PERSISTENCE:
        return 500
    return 500


@router.post(
    "/journal-entries/{journal_entry_id}/post",
    response_model=JournalPostResponse,
    responses={
        404: {
            "model": JournalPostErrorResponse,
            "description": "Journal entry not found for the company scope.",
            "content": {
                "application/json": {
                    "examples": {
                        "not_found": {
                            "summary": "Journal entry not found",
                            "value": {"code": "JOURNAL_NOT_FOUND", "message": "Journal entry was not found"},
                        }
                    }
                }
            },
        },
        409: {
            "model": JournalPostErrorResponse,
            "description": "Posting conflict due to journal state, balancing, period, or DB guard rules.",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_state": {
                            "summary": "Entry not in draft state",
                            "value": {"code": "JOURNAL_INVALID_STATE", "message": "Journal entry is not in DRAFT status"},
                        },
                        "no_lines": {
                            "summary": "No lines present",
                            "value": {"code": "JOURNAL_NO_LINES", "message": "Journal entry must have at least one line"},
                        },
                        "unbalanced": {
                            "summary": "Debits and credits do not match",
                            "value": {"code": "JOURNAL_UNBALANCED", "message": "Journal entry debits and credits must balance"},
                        },
                        "period_closed": {
                            "summary": "Closed or locked fiscal period",
                            "value": {
                                "code": "JOURNAL_PERIOD_CLOSED_OR_LOCKED",
                                "message": "Posting is blocked because the fiscal period is CLOSED or LOCKED",
                            },
                        },
                        "db_guard": {
                            "summary": "Database guard blocked mutation",
                            "value": {
                                "code": "JOURNAL_DB_GUARD_VIOLATION",
                                "message": "Posting was blocked by a database integrity guard",
                            },
                        },
                    }
                }
            },
        },
        500: {
            "model": JournalPostErrorResponse,
            "description": "Unexpected posting persistence failure.",
            "content": {
                "application/json": {
                    "examples": {
                        "persistence_failure": {
                            "summary": "Unexpected persistence failure",
                            "value": {
                                "code": "JOURNAL_PERSISTENCE_FAILURE",
                                "message": "Unexpected persistence failure during journal posting",
                            },
                        }
                    }
                }
            },
        },
    },
)
def post_journal_entry(
    journal_entry_id: str,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
    _permission=Depends(require_operations_permission(PrivilegedPermission.LEDGER_JOURNALS_POST)),
    db: Session = Depends(get_db),
):
    company_id = _ensure_company(request, x_company_id)
    actor_user_id = getattr(request.state, "actor_user_id", None)
    try:
        result = post_journal_entry_with_audit(
            db=db,
            company_id=company_id,
            journal_entry_id=str(journal_entry_id),
            posted_by_user_account_id=None if actor_user_id is None else str(actor_user_id),
        )
        db.commit()
        return JournalPostResponse(**result)
    except JournalPostingApplicationError as exc:
        db.rollback()
        return JSONResponse(
            status_code=_status_for_error_code(exc.code),
            content=JournalPostErrorResponse(code=str(exc.code), message=str(exc.message)).model_dump(),
        )
