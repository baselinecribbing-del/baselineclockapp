import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class EmployeeCredential(Base):
    __tablename__ = "employee_credentials"

    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('PENDING','VERIFIED','EXPIRED')",
            name="ck_employee_credentials_verification_status_valid",
        ),
    )

    employee_credential_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False, index=True)
    credential_type_id = Column(
        String,
        ForeignKey("credential_types.credential_type_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    certificate_number = Column(String, nullable=True)
    issued_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True, index=True)
    document_url = Column(String, nullable=True)
    verification_status = Column(String, nullable=False, default="PENDING", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
