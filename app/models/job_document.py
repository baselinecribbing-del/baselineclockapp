import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base


class JobDocument(Base):
    __tablename__ = "job_documents"

    __table_args__ = (
        CheckConstraint(
            "document_type IN ('BLUEPRINT','GRADE_SLIP','SITE_PLAN','STAKE_DATE','OTHER','ISSUE_PHOTO')",
            name="ck_job_documents_document_type_valid",
        ),
    )

    job_document_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=True, index=True)
    scope_id = Column(Integer, ForeignKey("scopes.id", ondelete="RESTRICT"), nullable=True, index=True)
    job_start_intake_id = Column(
        String,
        ForeignKey("job_start_intakes.job_start_intake_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    hazard_assessment_id = Column(
        String,
        ForeignKey("hazard_assessments.hazard_assessment_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    email_ingestion_event_id = Column(
        String,
        ForeignKey("email_ingestion_events.email_ingestion_event_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    document_type = Column(String, nullable=False, index=True)
    file_name = Column(String, nullable=False)
    storage_key = Column(String, nullable=True)
    parsed_text = Column(String, nullable=True)
    caption = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
