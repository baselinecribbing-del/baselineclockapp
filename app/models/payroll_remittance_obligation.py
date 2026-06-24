from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class PayrollRemittanceObligation(Base):
    __tablename__ = "payroll_remittance_obligations"

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "payroll_run_id",
            name="uq_payroll_remittance_obligations_company_run",
        ),
        CheckConstraint(
            "tax_year >= 2000",
            name="ck_payroll_remittance_obligations_tax_year_min",
        ),
        CheckConstraint(
            "tax_month >= 1 AND tax_month <= 12",
            name="ck_payroll_remittance_obligations_tax_month_range",
        ),
        CheckConstraint(
            "employee_deductions_cents >= 0",
            name="ck_payroll_remit_oblig_emp_ded_nonneg",
        ),
        CheckConstraint(
            "employer_contributions_cents >= 0",
            name="ck_payroll_remit_oblig_empr_contrib_nonneg",
        ),
        CheckConstraint(
            "total_remittance_cents >= 0",
            name="ck_payroll_remit_oblig_total_nonneg",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'REMITTED_MANUAL')",
            name="ck_payroll_remittance_obligations_status_valid",
        ),
        CheckConstraint(
            "remittance_type IN ('SOURCE_DEDUCTIONS')",
            name="ck_payroll_remittance_obligations_type_valid",
        ),
        CheckConstraint(
            "currency IN ('CAD')",
            name="ck_payroll_remittance_obligations_currency_valid",
        ),
        CheckConstraint(
            "(status <> 'REMITTED_MANUAL') OR (marked_remitted_at IS NOT NULL AND marked_remitted_by_user_id IS NOT NULL)",
            name="ck_payroll_remit_oblig_remitted_has_actor",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    payroll_run_id = Column(
        String,
        ForeignKey("payroll_run.payroll_run_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    remittance_type = Column(String, nullable=False, server_default="SOURCE_DEDUCTIONS")
    tax_year = Column(Integer, nullable=False)
    tax_month = Column(Integer, nullable=False)
    due_date = Column(Date, nullable=True)
    remittance_period_label = Column(String, nullable=True)
    employee_deductions_cents = Column(Integer, nullable=False, server_default="0")
    employer_contributions_cents = Column(Integer, nullable=False, server_default="0")
    total_remittance_cents = Column(Integer, nullable=False, server_default="0")
    currency = Column(String, nullable=False, server_default="CAD")
    status = Column(String, nullable=False, server_default="PENDING", index=True)
    reference_note = Column(String, nullable=True)
    remitted_reference = Column(String, nullable=True)
    prepared_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    marked_remitted_at = Column(DateTime(timezone=True), nullable=True)
    marked_remitted_by_user_id = Column(String, nullable=True)
