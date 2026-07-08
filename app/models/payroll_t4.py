import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint, func

from app.database import Base


class PayrollT4(Base):
    __tablename__ = "payroll_t4s"

    __table_args__ = (
        UniqueConstraint("company_id", "employee_id", "tax_year", name="uq_payroll_t4s_company_employee_year"),
        CheckConstraint("tax_year >= 2000", name="ck_payroll_t4s_tax_year_min"),
        CheckConstraint("employment_income_cents >= 0", name="ck_payroll_t4s_income_nonnegative"),
        CheckConstraint("cpp_contributions_cents >= 0", name="ck_payroll_t4s_cpp_nonnegative"),
        CheckConstraint("ei_premiums_cents >= 0", name="ck_payroll_t4s_ei_nonnegative"),
        CheckConstraint("income_tax_deducted_cents >= 0", name="ck_payroll_t4s_income_tax_nonnegative"),
        CheckConstraint("other_deductions_cents >= 0", name="ck_payroll_t4s_other_deductions_nonnegative"),
        CheckConstraint("slip_download_count >= 0", name="ck_payroll_t4s_slip_download_count_nonnegative"),
        CheckConstraint("employee_download_count >= 0", name="ck_payroll_t4s_employee_download_count_nonnegative"),
        CheckConstraint(
            "slip_status IN ('RECORD_ONLY', 'AVAILABLE')",
            name="ck_payroll_t4s_slip_status_valid",
        ),
        CheckConstraint(
            "delivery_status IN ('PENDING_MANUAL', 'DELIVERED_MANUAL')",
            name="ck_payroll_t4s_delivery_status_valid",
        ),
        CheckConstraint(
            "(slip_status <> 'AVAILABLE') OR "
            "(slip_storage_key IS NOT NULL AND slip_file_name IS NOT NULL AND slip_content_type IS NOT NULL "
            "AND slip_blob IS NOT NULL AND slip_byte_size IS NOT NULL AND slip_sha256 IS NOT NULL "
            "AND slip_generated_at IS NOT NULL AND slip_available_at IS NOT NULL)",
            name="ck_payroll_t4s_available_requires_artifact",
        ),
        CheckConstraint(
            "(delivery_status = 'PENDING_MANUAL' AND delivered_at IS NULL AND delivered_by_user_id IS NULL) OR "
            "(delivery_status = 'DELIVERED_MANUAL' AND delivered_at IS NOT NULL AND delivered_by_user_id IS NOT NULL)",
            name="ck_payroll_t4s_delivery_state_consistent",
        ),
        CheckConstraint(
            "(employee_acknowledged_at IS NULL AND employee_acknowledged_by_user_id IS NULL) OR "
            "(employee_acknowledged_at IS NOT NULL AND employee_acknowledged_by_user_id IS NOT NULL)",
            name="ck_payroll_t4s_employee_ack_state_consistent",
        ),
    )

    t4_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    employee_id = Column(
        Integer,
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    tax_year = Column(Integer, nullable=False, index=True)
    employment_income_cents = Column(Integer, nullable=False)
    cpp_contributions_cents = Column(Integer, nullable=False, default=0, server_default="0")
    ei_premiums_cents = Column(Integer, nullable=False, default=0, server_default="0")
    income_tax_deducted_cents = Column(Integer, nullable=False, default=0, server_default="0")
    other_deductions_cents = Column(Integer, nullable=False, default=0, server_default="0")
    slip_status = Column(String, nullable=False, default="RECORD_ONLY", server_default="RECORD_ONLY", index=True)
    slip_storage_key = Column(String, nullable=True)
    slip_file_name = Column(String, nullable=True)
    slip_content_type = Column(String, nullable=True)
    slip_blob = Column(LargeBinary, nullable=True)
    slip_byte_size = Column(Integer, nullable=True)
    slip_sha256 = Column(String, nullable=True)
    slip_generated_at = Column(DateTime(timezone=True), nullable=True)
    slip_generated_by_user_id = Column(String, nullable=True)
    slip_available_at = Column(DateTime(timezone=True), nullable=True)
    delivery_status = Column(
        String,
        nullable=False,
        default="PENDING_MANUAL",
        server_default="PENDING_MANUAL",
        index=True,
    )
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    delivered_by_user_id = Column(String, nullable=True)
    slip_download_count = Column(Integer, nullable=False, default=0, server_default="0")
    slip_last_downloaded_at = Column(DateTime(timezone=True), nullable=True)
    slip_last_downloaded_by_user_id = Column(String, nullable=True)
    employee_download_count = Column(Integer, nullable=False, default=0, server_default="0")
    employee_first_downloaded_at = Column(DateTime(timezone=True), nullable=True)
    employee_last_downloaded_at = Column(DateTime(timezone=True), nullable=True)
    employee_last_downloaded_by_user_id = Column(String, nullable=True)
    employee_acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    employee_acknowledged_by_user_id = Column(String, nullable=True)
    generated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    generated_by_user_id = Column(String, nullable=True)
