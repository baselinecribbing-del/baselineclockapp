from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList

from app.database import Base


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    company_id = Column(Integer, primary_key=True)
    company_name = Column(String, nullable=False)
    primary_trade = Column(String, nullable=False)
    country = Column(String(64), nullable=False)
    province_or_state = Column(String(64), nullable=False)
    selected_tier = Column(String, nullable=False)
    enabled_modules = Column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    onboarding_completed = Column(Boolean, nullable=False, default=False, server_default="false")
    cra_business_number = Column(String(32), nullable=True)
    cra_payroll_program_account_number = Column(String(32), nullable=True)
    payroll_registration_country = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "selected_tier IN ('tier_1_clock_in','tier_2_clock_in_payroll','tier_3_full_system')",
            name="ck_company_profiles_selected_tier_valid",
        ),
        CheckConstraint("jsonb_typeof(enabled_modules) = 'array'", name="ck_company_profiles_enabled_modules_array"),
    )
