from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CompanyModuleCreate(BaseModel):
    module_code: Literal["FOUNDATIONS", "WASTE_BINS"]
    is_enabled: bool = True


class CompanyModuleResponse(BaseModel):
    company_module_id: str
    company_id: int
    module_code: Literal["FOUNDATIONS", "WASTE_BINS"]
    is_enabled: bool
    created_at: datetime


class CrewAssignmentCreate(BaseModel):
    employee_id: int
    job_id: int
    scope_id: int | None = None
    assigned_date: date
    assignment_notes: str | None = None
    status: Literal["ASSIGNED", "ACKNOWLEDGED", "COMPLETED", "CANCELLED"] = "ASSIGNED"


class CrewAssignmentResponse(BaseModel):
    crew_assignment_id: str
    company_id: int
    employee_id: int
    job_id: int
    scope_id: int | None
    assigned_date: date
    assigned_by_user_id: str
    assignment_notes: str | None
    status: Literal["ASSIGNED", "ACKNOWLEDGED", "COMPLETED", "CANCELLED"]
    acknowledged_at: datetime | None
    acknowledged_by_employee_id: int | None
    created_at: datetime


class CrewAssignmentAcknowledgeCreate(BaseModel):
    acknowledged_by_employee_id: int


class CrewGroupCreate(BaseModel):
    name: str


class CrewGroupResponse(BaseModel):
    crew_group_id: str
    company_id: int
    name: str
    created_by_user_id: str
    created_at: datetime


class CrewGroupMemberCreate(BaseModel):
    employee_id: int


class CrewGroupMemberResponse(BaseModel):
    crew_group_member_id: str
    company_id: int
    crew_group_id: str
    employee_id: int
    created_at: datetime


class CrewGroupAssignCreate(BaseModel):
    job_id: int
    scope_id: int | None = None
    assigned_date: date
    assignment_notes: str | None = None


class CrewGroupAssignResponse(BaseModel):
    crew_group_id: str
    company_id: int
    created_count: int
    assignments: list[CrewAssignmentResponse]


class HazardAssessmentCreate(BaseModel):
    job_id: int
    scope_id: int | None = None
    crew_assignment_id: str | None = None
    completed_by_employee_id: int
    assessment_date: date
    form_payload: dict[str, Any]


class HazardAssessmentPhotoCreate(BaseModel):
    file_name: str
    storage_key: str
    caption: str | None = None


class HazardAssessmentPhotoUploadPrepareRequest(BaseModel):
    file_name: str
    content_type: str
    hazard_assessment_id: str
    document_type: Literal["ISSUE_PHOTO"] = "ISSUE_PHOTO"


class HazardAssessmentPhotoUploadPrepareResponse(BaseModel):
    storage_key: str
    upload_url: str | None
    required_headers: dict[str, str]
    required_fields: dict[str, str]
    expires_at: datetime | None
    available: bool
    reason: str | None


class HazardAssessmentPhotoResponse(BaseModel):
    photo_id: str
    job_document_id: str
    hazard_assessment_id: str
    company_id: int
    job_id: int
    document_type: Literal["ISSUE_PHOTO"]
    file_name: str
    storage_key: str
    caption: str | None
    uploaded_at: datetime


class HazardAssessmentPhotoAccessResponse(BaseModel):
    photo_id: str
    access_type: Literal["direct_url", "download_url", "unavailable"]
    file_url: str | None
    download_url: str | None
    file_name: str
    content_type: str | None
    expires_at: datetime | None
    available: bool
    reason: str | None


class HazardAssessmentResponse(BaseModel):
    hazard_assessment_id: str
    company_id: int
    job_id: int
    scope_id: int | None
    crew_assignment_id: str | None
    completed_by_employee_id: int
    assessment_date: date
    form_payload: dict[str, Any]
    created_at: datetime


class ToolboxMeetingCreate(BaseModel):
    job_id: int | None = None
    scope_id: int | None = None
    meeting_date: date
    completed_by_employee_id: int
    attendee_count: int | None = Field(default=None, ge=0)
    form_payload: dict[str, Any]


class ToolboxMeetingResponse(BaseModel):
    toolbox_meeting_id: str
    company_id: int
    job_id: int | None
    scope_id: int | None
    meeting_date: date
    completed_by_employee_id: int
    attendee_count: int | None
    form_payload: dict[str, Any]
    created_at: datetime


class JobDocumentDeliveryCreate(BaseModel):
    employee_id: int
    delivered_at: datetime | None = None


class JobDocumentDeliveryResponse(BaseModel):
    job_document_delivery_id: str
    company_id: int
    job_document_id: str
    employee_id: int
    delivered_at: datetime
    viewed_at: datetime | None


class FoundationsMessageCreate(BaseModel):
    job_id: int | None = None
    scope_id: int | None = None
    employee_id: int | None = None
    message_type: Literal["BROADCAST", "JOB_INSTRUCTION", "SAFETY_NOTICE"]
    subject: str | None = None
    body: str


class FoundationsMessageResponse(BaseModel):
    foundations_message_id: str
    company_id: int
    job_id: int | None
    scope_id: int | None
    employee_id: int | None
    message_type: Literal["BROADCAST", "JOB_INSTRUCTION", "SAFETY_NOTICE"]
    subject: str | None
    body: str
    created_by_user_id: str
    created_at: datetime


class FoundationActivityCreate(BaseModel):
    job_id: int
    scope_id: int
    employee_id: int
    activity_type: Literal["CLOCK_IN", "CLOCK_OUT", "JOB_PROGRESS_PHOTO", "SITE_NOTE", "ISSUE_REPORTED"]
    notes: str | None = None
    photo_url: str | None = None

    @model_validator(mode="after")
    def validate_activity_payload(self) -> "FoundationActivityCreate":
        if self.activity_type == "JOB_PROGRESS_PHOTO" and not self.photo_url:
            raise ValueError("photo_url is required for JOB_PROGRESS_PHOTO")
        if self.activity_type == "ISSUE_REPORTED" and not self.notes:
            raise ValueError("notes is required for ISSUE_REPORTED")
        return self


class FoundationActivityResponse(BaseModel):
    foundation_activity_id: str
    company_id: int
    job_id: int
    scope_id: int
    employee_id: int
    activity_type: Literal["CLOCK_IN", "CLOCK_OUT", "JOB_PROGRESS_PHOTO", "SITE_NOTE", "ISSUE_REPORTED"]
    notes: str | None
    photo_url: str | None
    created_at: datetime


class FoundationsJobDocumentResponse(BaseModel):
    document_id: str
    filename: str
    document_type: str
    uploaded_at: datetime
    download_url: str | None
