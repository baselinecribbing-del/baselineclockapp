import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, String, UniqueConstraint, func

from app.database import Base


class CompanyModule(Base):
    __tablename__ = "company_modules"

    __table_args__ = (
        UniqueConstraint("company_id", "module_code", name="uq_company_modules_company_module_code"),
        CheckConstraint(
            "module_code IN ('FOUNDATIONS','WASTE_BINS')",
            name="ck_company_modules_module_code_valid",
        ),
    )

    company_module_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    module_code = Column(String, nullable=False, index=True)
    is_enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
