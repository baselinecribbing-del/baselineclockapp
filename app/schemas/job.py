from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobCreate(BaseModel):
    name: str


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    name: str
    is_active: bool
    created_at: datetime
