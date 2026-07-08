import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class JobDocumentDelivery(Base):
    __tablename__ = "job_document_deliveries"

    job_document_delivery_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    job_document_id = Column(
        String,
        ForeignKey("job_documents.job_document_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False, index=True)
    delivered_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    viewed_at = Column(DateTime(timezone=True), nullable=True)
