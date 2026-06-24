import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.database import Base


class DeductionType(Base):
    __tablename__ = "deduction_types"

    deduction_type_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=True, index=True)
    code = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    calculation_method = Column(String, nullable=False)
    is_statutory = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
