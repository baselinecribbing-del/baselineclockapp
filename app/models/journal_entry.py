import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    __table_args__ = (
        UniqueConstraint("company_id", "journal_entry_id", name="uq_journal_entries_company_entry_id"),
        CheckConstraint(
            "status IN ('DRAFT','POSTED')",
            name="ck_journal_entries_status_valid",
        ),
        CheckConstraint(
            "(status = 'POSTED' AND posted_at IS NOT NULL) OR "
            "(status = 'DRAFT' AND posted_at IS NULL)",
            name="ck_journal_entries_posted_state_consistent",
        ),
    )

    journal_entry_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    fiscal_period_id = Column(
        String,
        ForeignKey("fiscal_periods.fiscal_period_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    entry_date = Column(Date, nullable=False, index=True)
    status = Column(String(16), nullable=False, default="DRAFT", server_default="DRAFT", index=True)
    source_type = Column(String(64), nullable=False, index=True)
    source_reference_id = Column(String(128), nullable=True, index=True)
    reference_number = Column(String(64), nullable=True, index=True)
    memo = Column(String, nullable=True)
    posted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    posted_by_user_account_id = Column(
        String,
        ForeignKey("user_accounts.user_account_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
