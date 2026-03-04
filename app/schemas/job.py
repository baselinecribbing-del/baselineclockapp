from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class JobCreate(BaseModel):
    name: str
    site_lat: Optional[float] = None
    site_lng: Optional[float] = None
    site_radius_m: Optional[int] = None


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    name: str
    is_active: bool
    created_at: datetime
    site_lat: Optional[float] = None
    site_lng: Optional[float] = None
    site_radius_m: Optional[int] = None
