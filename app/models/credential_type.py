import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, String, func

from app.database import Base


class CredentialType(Base):
    __tablename__ = "credential_types"

    __table_args__ = (
        CheckConstraint(
            "category IN ('SAFETY','TRADE','COMPANY')",
            name="ck_credential_types_category_valid",
        ),
    )

    credential_type_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False, index=True)
    is_company_level = Column(Boolean, nullable=False, default=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
