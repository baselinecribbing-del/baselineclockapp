from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import Index, UniqueConstraint

from app.database import Base


class EventOutbox(Base):
    __tablename__ = "event_outbox"

    id = Column(Integer, primary_key=True)

    company_id = Column(Integer, nullable=False, index=True)

    event_type = Column(String, nullable=False, index=True)
    idempotency_key = Column(String, nullable=False)

    payload = Column(JSONB, nullable=False)

    processed = Column(Boolean, nullable=False, server_default="false")
    processed_at = Column(DateTime(timezone=True), nullable=True)

    retry_count = Column(Integer, nullable=False, server_default="0")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "event_type",
            "idempotency_key",
            name="uq_event_outbox_idempotency",
        ),
        Index("ix_event_outbox_company_event", "company_id", "event_type"),
        Index("ix_event_outbox_processed", "processed", "created_at"),
    )
