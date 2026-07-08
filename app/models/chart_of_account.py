import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class ChartOfAccount(Base):
    __tablename__ = "chart_of_accounts"

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_chart_of_accounts_company_code"),
        UniqueConstraint("company_id", "account_id", name="uq_chart_of_accounts_company_account_id"),
        CheckConstraint(
            "account_type IN ('ASSET','LIABILITY','EQUITY','REVENUE','EXPENSE','CONTRA_ASSET','CONTRA_LIABILITY','CONTRA_REVENUE','CONTRA_EXPENSE')",
            name="ck_chart_of_accounts_account_type_valid",
        ),
        CheckConstraint("normal_balance IN ('DEBIT','CREDIT')", name="ck_chart_of_accounts_normal_balance_valid"),
        CheckConstraint("parent_account_id IS NULL OR parent_account_id <> account_id", name="ck_chart_of_accounts_parent_not_self"),
    )

    account_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    code = Column(String(32), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    account_type = Column(String(32), nullable=False, index=True)
    normal_balance = Column(String(6), nullable=False)
    parent_account_id = Column(String, ForeignKey("chart_of_accounts.account_id", ondelete="RESTRICT"), nullable=True, index=True)
    allow_posting = Column(Boolean, nullable=False, default=True, server_default="true")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    description = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
