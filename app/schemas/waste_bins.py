from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class WasteBinCreate(BaseModel):
    bin_number: str
    capacity_yards: int
    status: Literal["AVAILABLE", "ON_SITE", "IN_TRANSIT", "AT_LANDFILL", "OUT_OF_SERVICE"] = "AVAILABLE"
    current_site_id: str | None = None
    current_ticket_id: str | None = None
    last_service_at: datetime | None = None


class WasteBinUpdate(BaseModel):
    bin_number: str | None = None
    capacity_yards: int | None = None
    status: Literal["AVAILABLE", "ON_SITE", "IN_TRANSIT", "AT_LANDFILL", "OUT_OF_SERVICE"] | None = None
    current_site_id: str | None = None
    current_ticket_id: str | None = None
    last_service_at: datetime | None = None


class WasteBinResponse(BaseModel):
    id: str
    company_id: int
    bin_number: str
    capacity_yards: int
    status: Literal["AVAILABLE", "ON_SITE", "IN_TRANSIT", "AT_LANDFILL", "OUT_OF_SERVICE"]
    current_site_id: str | None
    current_ticket_id: str | None
    last_service_at: datetime | None
    created_at: datetime
