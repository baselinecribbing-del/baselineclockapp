import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Numeric, String

from app.database import Base


class DeductionConfig(Base):
    __tablename__ = "deduction_configs"

    __table_args__ = (
        CheckConstraint(
            "(rate_percent IS NOT NULL AND amount_cents IS NULL) OR "
            "(rate_percent IS NULL AND amount_cents IS NOT NULL)",
            name="ck_deduction_configs_rate_xor_amount",
        ),
    )

    deduction_config_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    deduction_type_id = Column(
        String,
        ForeignKey("deduction_types.deduction_type_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    employee_id = Column(
        Integer,
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    rate_percent = Column(Numeric(7, 4), nullable=True)
    amount_cents = Column(Integer, nullable=True)
    annual_cap_cents = Column(Integer, nullable=True)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
