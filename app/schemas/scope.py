from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ScopeCreate(BaseModel):
    job_id: int
    name: str


class ScopeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    job_id: int
    name: str
    is_active: bool
    created_at: datetime
