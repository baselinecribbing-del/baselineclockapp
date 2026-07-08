import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.schema import UniqueConstraint

from app.database import Base


class JobStartIntake(Base):
    __tablename__ = "job_start_intakes"

    __table_args__ = (
        CheckConstraint(
            "intake_status IN ('QUEUED','FLAGGED','DUPLICATE')",
            name="ck_job_start_intakes_status_valid",
        ),
        CheckConstraint(
            "promotion_status IN ('NOT_PROMOTED','PROMOTED')",
            name="ck_job_start_intakes_promotion_status_valid",
        ),
        UniqueConstraint(
            "company_id",
            "email_ingestion_event_id",
            name="uq_job_start_intakes_company_email_event",
        ),
    )

    job_start_intake_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    email_ingestion_event_id = Column(
        String,
        ForeignKey("email_ingestion_events.email_ingestion_event_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    duplicate_of_job_start_intake_id = Column(
        String,
        ForeignKey("job_start_intakes.job_start_intake_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    builder_name = Column(String, nullable=True, index=True)
    source_email = Column(String, nullable=False)
    project_address = Column(String, nullable=True, index=True)
    lot_number = Column(String, nullable=True)
    block_number = Column(String, nullable=True)
    stake_date = Column(Date, nullable=True, index=True)
    queue_trigger_date = Column(Date, nullable=True, index=True)
    intake_status = Column(String, nullable=False, default="FLAGGED", server_default="FLAGGED", index=True)
    has_blueprint = Column(Boolean, nullable=False, default=False, server_default="false")
    has_grade_slip = Column(Boolean, nullable=False, default=False, server_default="false")
    has_site_plan = Column(Boolean, nullable=False, default=False, server_default="false")
    has_stake_date_document = Column(Boolean, nullable=False, default=False, server_default="false")
    promotion_status = Column(
        String,
        nullable=False,
        default="NOT_PROMOTED",
        server_default="NOT_PROMOTED",
        index=True,
    )
    promoted_at = Column(DateTime(timezone=True), nullable=True)
    parse_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
