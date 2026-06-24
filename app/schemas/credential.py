from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

CredentialCategory = Literal["SAFETY", "TRADE", "COMPANY"]
VerificationStatus = Literal["PENDING", "VERIFIED", "EXPIRED"]


class TradeTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trade_type_id: str
    code: str
    name: str
    is_active: bool
    created_at: datetime


class CredentialTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    credential_type_id: str
    code: str
    name: str
    category: CredentialCategory
    is_company_level: bool
    is_active: bool
    created_at: datetime


class EmployeeCredentialCreate(BaseModel):
    employee_id: int
    credential_type_id: str
    certificate_number: str | None = None
    issued_date: date | None = None
    expiry_date: date | None = None
    document_url: str | None = None
    verification_status: VerificationStatus = "PENDING"


class EmployeeCredentialUpdate(BaseModel):
    certificate_number: str | None = None
    issued_date: date | None = None
    expiry_date: date | None = None
    document_url: str | None = None
    verification_status: VerificationStatus | None = None


class EmployeeCredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_credential_id: str
    company_id: int
    employee_id: int
    credential_type_id: str
    certificate_number: str | None
    issued_date: date | None
    expiry_date: date | None
    document_url: str | None
    verification_status: VerificationStatus
    created_at: datetime


class JobTradeRequirementCreate(BaseModel):
    job_id: int
    scope_id: int | None = None
    trade_type_id: str
    credential_type_id: str
    is_required: bool = True


class JobTradeRequirementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_trade_requirement_id: str
    company_id: int
    job_id: int
    scope_id: int | None
    trade_type_id: str
    credential_type_id: str
    is_required: bool
    created_at: datetime
