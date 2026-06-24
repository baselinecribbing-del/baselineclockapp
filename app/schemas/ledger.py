from typing import Literal

from pydantic import BaseModel


class JournalPostResponse(BaseModel):
    ok: bool
    journal_entry_id: str
    status: str
    line_count: int
    debit_total_cents: int
    credit_total_cents: int
    posted_at: str | None
    audit_event_id: str


class JournalPostErrorResponse(BaseModel):
    code: Literal[
        "JOURNAL_NOT_FOUND",
        "JOURNAL_INVALID_STATE",
        "JOURNAL_NO_LINES",
        "JOURNAL_UNBALANCED",
        "JOURNAL_PERIOD_CLOSED_OR_LOCKED",
        "JOURNAL_DB_GUARD_VIOLATION",
        "JOURNAL_PERSISTENCE_FAILURE",
    ]
    message: str
