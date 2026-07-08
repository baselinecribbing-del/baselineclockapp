from sqlalchemy import CheckConstraint, Column, DateTime, Integer, Numeric, String, Text

from app.database import Base


class TimeEntry(Base):
    __tablename__ = "time_entries"

    __table_args__ = (
        # A time entry may never end before it started (negative-duration guard).
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_time_entries_ended_at_after_started_at",
        ),
    )

    time_entry_id = Column(String, primary_key=True, index=True)

    company_id = Column(Integer, nullable=False, index=True)
    employee_id = Column(Integer, nullable=False, index=True)

    job_id = Column(Integer, nullable=False, index=True)
    scope_id = Column(Integer, nullable=False, index=True)

    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    clock_in_lat = Column(Numeric(9, 6), nullable=True)
    clock_in_lng = Column(Numeric(9, 6), nullable=True)
    clock_in_accuracy_m = Column(Integer, nullable=True)
    clock_in_distance_m = Column(Integer, nullable=True)
    clock_in_address = Column(Text, nullable=True)
    clock_in_address_source = Column(Text, nullable=True)

    status = Column(String, nullable=False, index=True)
    approval_status = Column(String, nullable=False, index=True, default="pending")
    approved_at = Column(DateTime, nullable=True)
    approved_by_user_id = Column(String, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejected_by_user_id = Column(String, nullable=True)
    approval_note = Column(Text, nullable=True)
