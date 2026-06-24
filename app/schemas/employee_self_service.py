from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EmployeePinSetRequest(BaseModel):
    new_pin: str = Field(min_length=4, max_length=6)


class EmployeePinVerifyRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=6)


class EmployeePinChangeRequest(BaseModel):
    current_pin: str = Field(min_length=4, max_length=6)
    new_pin: str = Field(min_length=4, max_length=6)


class EmployeePinResetRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_pin: str = Field(min_length=4, max_length=6)


class EmployeePinStatusResponse(BaseModel):
    status: str
    employee_pin_changed_at: datetime | None
    verified_at: datetime | None = None


class SelfServiceEmployeeProfileResponse(BaseModel):
    employee_id: int
    company_id: int
    name: str
    preferred_name: str | None
    phone: str | None
    email: str | None
    employment_status: str
    job_title: str | None
    department: str | None


class SelfServiceDashboardResponse(BaseModel):
    employee_id: int
    active_time_entry_id: str | None
    active_time_entry_started_at: datetime | None
    recent_completed_entries: int
    paystub_count: int


class SelfServiceTimeEntryRow(BaseModel):
    time_entry_id: str
    status: Literal["active", "completed"]
    approval_status: Literal["pending", "approved", "rejected"]
    job_id: int
    scope_id: int
    started_at: datetime
    ended_at: datetime | None


class SelfServiceTimeEntriesResponse(BaseModel):
    rows: list[SelfServiceTimeEntryRow]


class SelfServiceClockInRequest(BaseModel):
    job_id: int
    scope_id: int
    clock_in_lat: float | None = None
    clock_in_lng: float | None = None
    clock_in_accuracy_m: int | None = None
    started_at: datetime | None = None


class SelfServiceClockOutRequest(BaseModel):
    ended_at: datetime | None = None


class SelfServicePaystubRow(BaseModel):
    paystub_id: str
    payroll_run_id: str
    gross_pay_cents: int
    total_deductions_cents: int
    net_pay_cents: int
    delivery_status: Literal["PENDING", "SENT"]
    pay_period_start: str | None
    pay_period_end: str | None
    created_at: datetime


class SelfServicePaystubsResponse(BaseModel):
    rows: list[SelfServicePaystubRow]


class SelfServiceT4Row(BaseModel):
    t4_id: str
    tax_year: int
    employment_income_cents: int
    cpp_contributions_cents: int
    ei_premiums_cents: int
    income_tax_deducted_cents: int
    other_deductions_cents: int
    generated_at: datetime
    status: str
    slip_file_name: str | None = None
    slip_content_type: str | None = None
    slip_byte_size: int | None = None
    slip_generated_at: datetime | None = None
    slip_available_at: datetime | None = None
    delivery_status: Literal["PENDING_MANUAL", "DELIVERED_MANUAL"]
    delivered_at: datetime | None = None
    employee_download_count: int
    employee_first_downloaded_at: datetime | None = None
    employee_last_downloaded_at: datetime | None = None
    employee_acknowledged_at: datetime | None = None
    slip_url: str | None = None


class SelfServiceT4sResponse(BaseModel):
    rows: list[SelfServiceT4Row]
