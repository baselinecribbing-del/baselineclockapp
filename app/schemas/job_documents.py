from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

QueueStatus = Literal["RECEIVED", "UNMATCHED", "MATCHED", "READY_FOR_OPS", "CLOSED"]


class EmailIngestionEventCreate(BaseModel):
    source_message_id: str
    sender_email: str
    subject: str
    received_at: datetime | None = None
    parse_status: Literal["RECEIVED", "PARSED", "FAILED"] = "RECEIVED"
    parsed_job_id: int | None = None
    parsed_scope_id: int | None = None
    parsed_po_number: str | None = None
    parse_notes: str | None = None
    raw_metadata: dict[str, Any] | None = None


class EmailIngestionEventResponse(BaseModel):
    email_ingestion_event_id: str
    company_id: int
    source_message_id: str
    sender_email: str
    subject: str
    received_at: datetime
    parse_status: Literal["RECEIVED", "PARSED", "FAILED"]
    parsed_job_id: int | None
    parsed_scope_id: int | None
    parsed_po_number: str | None
    parse_notes: str | None
    raw_metadata: dict[str, Any] | None


class JobPurchaseOrderCreate(BaseModel):
    job_id: int
    scope_id: int | None = None
    po_number: str
    vendor_name: str | None = None
    vendor_email: str | None = None
    source_email_ingestion_event_id: str | None = None
    status: Literal["DRAFT", "ISSUED", "CLOSED", "VOID"] = "DRAFT"
    issued_date: date | None = None


class JobPurchaseOrderResponse(BaseModel):
    job_purchase_order_id: str
    company_id: int
    job_id: int
    scope_id: int | None
    po_number: str
    vendor_name: str | None
    vendor_email: str | None
    source_email_ingestion_event_id: str | None
    status: Literal["DRAFT", "ISSUED", "CLOSED", "VOID"]
    issued_date: date | None
    queue_status: QueueStatus
    matched_job_id: int | None
    matched_scope_id: int | None
    matched_customer_site_id: str | None
    reviewed_by_user_id: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    created_at: datetime


class JobPurchaseOrderQueueMatchRequest(BaseModel):
    matched_job_id: int
    matched_scope_id: int | None = None
    matched_customer_site_id: str
    review_notes: str | None = None


class JobPurchaseOrderQueueTransitionRequest(BaseModel):
    review_notes: str | None = None


class JobPurchaseOrderCostCreate(BaseModel):
    amount_cents: int
    description: str


class JobPurchaseOrderCostResponse(BaseModel):
    id: int
    company_id: int
    job_purchase_order_id: str
    amount_cents: int
    description: str
    source_reference_id: str
    posting_date: datetime
    created_at: datetime


class JobStartIntakeAttachmentInput(BaseModel):
    file_name: str
    parsed_text: str | None = None
    storage_key: str | None = None


class JobStartIntakeFromEmailRequest(BaseModel):
    email_ingestion_event_id: str
    parsed_text: str | None = None
    attachments: list[JobStartIntakeAttachmentInput] = Field(default_factory=list)


class JobStartIntakeResponse(BaseModel):
    job_start_intake_id: str
    company_id: int
    email_ingestion_event_id: str
    job_id: int | None = None
    duplicate_of_job_start_intake_id: str | None
    builder_name: str | None
    source_email: str
    project_address: str | None
    lot_number: str | None
    block_number: str | None
    stake_date: date | None
    queue_trigger_date: date | None
    intake_status: Literal["QUEUED", "FLAGGED", "DUPLICATE"]
    has_blueprint: bool
    has_grade_slip: bool
    has_site_plan: bool
    has_stake_date_document: bool
    promotion_status: Literal["NOT_PROMOTED", "PROMOTED"]
    promoted_at: datetime | None
    attachments_received: dict[str, bool]
    parse_notes: str | None
    created_at: datetime


class JobStartIntakePromotionResponse(BaseModel):
    intake_id: str
    job_id: int
    promotion_status: Literal["PROMOTED"]
    promoted_at: datetime
    queue_trigger_date: date | None
    builder_name: str | None
    project_address: str | None


class JobDocumentUploadPrepareRequest(BaseModel):
    file_name: str
    content_type: str
    document_type: Literal["BLUEPRINT", "GRADE_SLIP", "SITE_PLAN"]
    intake_id: str | None = None
    job_id: int | None = None

    @model_validator(mode="after")
    def validate_context(self) -> "JobDocumentUploadPrepareRequest":
        if (self.intake_id is None) == (self.job_id is None):
            raise ValueError("Exactly one of intake_id or job_id must be provided")
        return self


class JobDocumentUploadPrepareResponse(BaseModel):
    storage_key: str
    upload_url: str | None
    required_headers: dict[str, str]
    required_fields: dict[str, str]
    expires_at: datetime | None
    available: bool
    reason: str | None


class JobDocumentCreate(BaseModel):
    file_name: str
    storage_key: str
    document_type: Literal["BLUEPRINT", "GRADE_SLIP", "SITE_PLAN"]
    intake_id: str | None = None
    job_id: int | None = None
    caption: str | None = None

    @model_validator(mode="after")
    def validate_context(self) -> "JobDocumentCreate":
        if (self.intake_id is None) == (self.job_id is None):
            raise ValueError("Exactly one of intake_id or job_id must be provided")
        return self


class JobDocumentResponse(BaseModel):
    document_id: str
    job_document_id: str
    company_id: int
    job_id: int | None
    job_start_intake_id: str | None
    email_ingestion_event_id: str | None
    document_type: Literal["BLUEPRINT", "GRADE_SLIP", "SITE_PLAN", "STAKE_DATE", "OTHER", "ISSUE_PHOTO"]
    file_name: str
    storage_key: str | None
    caption: str | None
    created_at: datetime


class JobDocumentAccessResponse(BaseModel):
    document_id: str
    access_type: Literal["direct_url", "download_url", "unavailable"]
    file_url: str | None
    download_url: str | None
    file_name: str
    content_type: str | None
    expires_at: datetime | None
    available: bool
    reason: str | None
