import uuid

from sqlalchemy import Boolean, Column, DateTime, String, func

from app.database import Base


class TradeType(Base):
    __tablename__ = "trade_types"

    trade_type_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
