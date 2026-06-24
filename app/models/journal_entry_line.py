import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKeyConstraint, Integer, String, UniqueConstraint, func

from app.database import Base


class JournalEntryLine(Base):
    __tablename__ = "journal_entry_lines"

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "journal_entry_id",
            "line_number",
            name="uq_journal_entry_lines_company_entry_line_number",
        ),
        CheckConstraint(
            "debit_amount_cents >= 0 AND credit_amount_cents >= 0",
            name="ck_journal_entry_lines_nonnegative_amounts",
        ),
        CheckConstraint(
            "(debit_amount_cents > 0 AND credit_amount_cents = 0) OR "
            "(credit_amount_cents > 0 AND debit_amount_cents = 0)",
            name="ck_journal_entry_lines_single_side_nonzero",
        ),
        ForeignKeyConstraint(
            ["company_id", "journal_entry_id"],
            ["journal_entries.company_id", "journal_entries.journal_entry_id"],
            name="fk_journal_entry_lines_company_entry",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "account_id"],
            ["chart_of_accounts.company_id", "chart_of_accounts.account_id"],
            name="fk_journal_entry_lines_company_account",
            ondelete="RESTRICT",
        ),
    )

    journal_entry_line_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    journal_entry_id = Column(String, nullable=False, index=True)
    line_number = Column(Integer, nullable=False)
    account_id = Column(String, nullable=False, index=True)
    debit_amount_cents = Column(Integer, nullable=False, default=0, server_default="0")
    credit_amount_cents = Column(Integer, nullable=False, default=0, server_default="0")
    memo = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
