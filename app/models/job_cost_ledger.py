from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, UniqueConstraint

from app.database import Base


class JobCostLedger(Base):
    __tablename__ = "job_cost_ledger"

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "source_type",
            "source_reference_id",
            "cost_category",
            name="uq_job_cost_ledger_posting_key",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    company_id = Column(Integer, index=True, nullable=False)
    job_id = Column(Integer, index=True, nullable=False)
    scope_id = Column(Integer, index=True, nullable=True)
    employee_id = Column(Integer, index=True, nullable=True)

    source_type = Column(String, index=True, nullable=False)  # LABOR|PRODUCTION|MATERIAL|ADJUSTMENT
    source_reference_id = Column(String, index=True, nullable=False)
    cost_category = Column(String, index=True, nullable=False)

    quantity = Column(Numeric, nullable=True)
    unit_cost_cents = Column(Integer, nullable=True)
    total_cost_cents = Column(Integer, nullable=False)

    posting_date = Column(DateTime, index=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    immutable_flag = Column(Boolean, nullable=False, default=True)
