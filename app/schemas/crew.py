from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CrewCreate(BaseModel):
    name: str
    supervisor_employee_id: int | None = None
    is_active: bool = True


class CrewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    crew_id: str
    company_id: int
    name: str
    supervisor_employee_id: int | None
    is_active: bool
    created_at: datetime


class CrewMemberCreate(BaseModel):
    employee_id: int


class CrewMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    crew_member_id: str
    company_id: int
    crew_id: str
    employee_id: int
    assigned_at: datetime
    removed_at: datetime | None


class CrewDetailResponse(BaseModel):
    crew: CrewResponse
    members: list[CrewMemberResponse]
