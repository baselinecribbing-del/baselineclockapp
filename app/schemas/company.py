from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

PrimaryTrade = Literal[
    "Foundations",
    "Waste Hauling",
    "Excavation",
    "Concrete",
    "Framing",
    "Roofing",
    "Electrical",
    "Plumbing",
    "Landscaping",
    "Demolition",
]
CompanyTier = Literal[
    "tier_1_clock_in",
    "tier_2_clock_in_payroll",
    "tier_3_full_system",
]
CompanyModuleCode = Literal[
    "foundations",
    "waste_bins",
    "jobs",
    "payroll",
    "costing",
    "invoices",
    "field",
    "dispatch",
    "credentials",
]


class CompanyProfileUpsert(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    primary_trade: PrimaryTrade
    country: str = Field(min_length=1, max_length=64)
    province_or_state: str = Field(min_length=1, max_length=64)
    selected_tier: CompanyTier
    enabled_modules: list[CompanyModuleCode]
    onboarding_completed: bool = False

    @field_validator("company_name", "country", "province_or_state", mode="before")
    @classmethod
    def _strip_required_strings(cls, value: object) -> str:
        if value is None:
            raise ValueError("value is required")
        text = str(value).strip()
        if not text:
            raise ValueError("value cannot be blank")
        return text

    @field_validator("enabled_modules")
    @classmethod
    def _dedupe_enabled_modules(cls, value: list[CompanyModuleCode]) -> list[CompanyModuleCode]:
        seen: set[str] = set()
        deduped: list[CompanyModuleCode] = []
        for module_code in value:
            if module_code in seen:
                continue
            seen.add(module_code)
            deduped.append(module_code)
        return deduped


class CompanyProfileResponse(BaseModel):
    company_id: int
    company_name: str
    primary_trade: PrimaryTrade
    country: str
    province_or_state: str
    selected_tier: CompanyTier
    enabled_modules: list[CompanyModuleCode]
    onboarding_completed: bool
    created_at: datetime
    updated_at: datetime


class CompanyEntitlementsResponse(BaseModel):
    company_id: int
    selected_tier: CompanyTier
    entitled_modules: list[CompanyModuleCode]
    enabled_modules: list[CompanyModuleCode]
    entitled_capabilities: list[str]
    onboarding_completed: bool
