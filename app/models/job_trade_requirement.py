import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class JobTradeRequirement(Base):
    __tablename__ = "job_trade_requirements"

    job_trade_requirement_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True)
    scope_id = Column(Integer, ForeignKey("scopes.id", ondelete="RESTRICT"), nullable=True, index=True)
    trade_type_id = Column(String, ForeignKey("trade_types.trade_type_id", ondelete="RESTRICT"), nullable=False, index=True)
    credential_type_id = Column(
        String,
        ForeignKey("credential_types.credential_type_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_required = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
