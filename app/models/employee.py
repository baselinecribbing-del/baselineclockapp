from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.sql import func

from app.database import Base


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    hourly_rate_cents = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # --- Columns added by later migrations; previously unmapped (drift → 500s). ---
    # Worker classification / labor costing
    labor_class = Column(String, nullable=False, server_default="PAYROLL_EMPLOYEE")
    include_wcb_cost = Column(Boolean, nullable=False, server_default="true")
    include_ei_cost = Column(Boolean, nullable=False, server_default="true")
    include_tax_cost = Column(Boolean, nullable=False, server_default="true")
    requires_payroll = Column(Boolean, nullable=False, server_default="true")
    pay_type = Column(String, nullable=False, server_default="HOURLY")
    employment_status = Column(String, nullable=False, server_default="ACTIVE")

    # Profile / contact
    legal_name = Column(String, nullable=True)
    preferred_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    trade_type_id = Column(String, nullable=True)
    crew_name = Column(String, nullable=True)
    salary_cents = Column(Integer, nullable=True)
    hire_date = Column(Date, nullable=True)
    emergency_contact_name = Column(String, nullable=True)
    emergency_contact_phone = Column(String, nullable=True)
    emergency_contact_relationship = Column(String, nullable=True)
    field_profile_notes = Column(String, nullable=True)
    documents_notes = Column(String, nullable=True)

    # Legal identity / payroll onboarding
    legal_first_name = Column(String, nullable=True)
    legal_last_name = Column(String, nullable=True)
    birth_date = Column(Date, nullable=True)
    sin = Column(String, nullable=True)

    # Home address
    address_line_1 = Column(String, nullable=True)
    address_line_2 = Column(String, nullable=True)
    city = Column(String, nullable=True)
    province = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    country = Column(String, nullable=True)

    # Mailing address
    mailing_address_line_1 = Column(String, nullable=True)
    mailing_address_line_2 = Column(String, nullable=True)
    mailing_city = Column(String, nullable=True)
    mailing_province = Column(String, nullable=True)
    mailing_postal_code = Column(String, nullable=True)
    mailing_country = Column(String, nullable=True)

    # Employment details
    termination_date = Column(Date, nullable=True)
    work_location = Column(String, nullable=True)
    manager_name = Column(String, nullable=True)
    department = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    employee_number = Column(String, nullable=True)
    pay_schedule = Column(String, nullable=True)
    base_rate_cents = Column(Integer, nullable=True)
    base_rate_effective_date = Column(Date, nullable=True)
    payment_method = Column(String, nullable=True)
    default_hours = Column(Numeric, nullable=True)

    # Tax (TD1) configuration
    province_of_employment = Column(String, nullable=True)
    federal_claim_amount = Column(Numeric, nullable=True)
    provincial_claim_amount = Column(Numeric, nullable=True)
    additional_tax_withholding = Column(Numeric, nullable=True)
    tax_exemptions = Column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("hourly_rate_cents >= 0", name="ck_employees_hourly_rate_cents_nonnegative"),
    )
