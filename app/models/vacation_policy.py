import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, Numeric, String, func

from app.database import Base


class VacationPolicy(Base):
    __tablename__ = "vacation_policies"

    __table_args__ = (
        CheckConstraint(
            "((accrual_rate_percent IS NOT NULL AND payout_rate_percent IS NULL) OR "
            "(accrual_rate_percent IS NULL AND payout_rate_percent IS NOT NULL))",
            name="ck_vacation_policies_rate_xor_valid",
        ),
        CheckConstraint(
            "accrual_rate_percent IS NULL OR accrual_rate_percent >= 0",
            name="ck_vacation_policies_accrual_rate_nonnegative",
        ),
        CheckConstraint(
            "payout_rate_percent IS NULL OR payout_rate_percent >= 0",
            name="ck_vacation_policies_payout_rate_nonnegative",
        ),
        CheckConstraint(
            "payout_method IN ('accrued','each_pay_period')",
            name="ck_vacation_policies_payout_method_valid",
        ),
    )

    vacation_policy_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False)
    accrual_rate_percent = Column(Numeric(7, 4), nullable=True)
    payout_rate_percent = Column(Numeric(7, 4), nullable=True)
    payout_method = Column(String(32), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
