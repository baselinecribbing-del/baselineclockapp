from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint

from app.database import Base


class BinRouteRunStop(Base):
    __tablename__ = "bin_route_run_stops"

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "route_run_id",
            "bin_service_ticket_id",
            name="uq_bin_route_run_stops_route_ticket",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, nullable=False, index=True)
    route_run_id = Column(
        String,
        ForeignKey("bin_route_runs.route_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bin_service_ticket_id = Column(
        String,
        ForeignKey("bin_service_tickets.bin_service_ticket_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_index = Column(Integer, nullable=True, index=True)
    bin_asset_id = Column(
        String,
        ForeignKey("bin_assets.bin_asset_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
