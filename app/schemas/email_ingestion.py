from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class BuilderEmailAttachmentInput(BaseModel):
    filename: str
    storage_key: str | None = None
    content_type: str | None = None


class BuilderEmailIngestionRequest(BaseModel):
    company_id: int
    source: Literal["builder_email"]
    from_email: str
    subject: str
    received_at: datetime | None = None
    body_text: str | None = None
    attachments: list[BuilderEmailAttachmentInput] = Field(default_factory=list)


class BuilderEmailIngestionAttachmentResponse(BaseModel):
    filename: str
    storage_key: str | None
    content_type: str | None
    document_type: Literal["BLUEPRINT", "GRADE_SLIP", "SITE_PLAN", "STAKE_DATE", "OTHER"]
    job_document_id: str


class BuilderEmailIngestionResponse(BaseModel):
    email_ingestion_event_id: str
    job_start_intake_id: str
    company_id: int
    source: Literal["builder_email"]
    event_hash: str
    idempotent_replay: bool
    builder_name: str | None
    project_address: str | None
    lot_number: str | None
    block_number: str | None
    stake_date: date | None
    queue_trigger_date: date | None
    intake_status: Literal["QUEUED", "FLAGGED", "DUPLICATE"]
    duplicate_of_job_start_intake_id: str | None
    event_emitted: bool
    attachments: list[BuilderEmailIngestionAttachmentResponse]
