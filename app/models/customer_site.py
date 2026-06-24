import uuid

from sqlalchemy import Column, DateTime, Integer, String, func

from app.database import Base


class CustomerSite(Base):
    __tablename__ = "customer_sites"

    customer_site_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, nullable=False, index=True)
    customer_name = Column(String, nullable=False)
    site_name = Column(String, nullable=True)
    address_line_1 = Column(String, nullable=False, index=True)
    city = Column(String, nullable=False)
    province = Column(String, nullable=False)
    postal_code = Column(String, nullable=False)
    contact_name = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
