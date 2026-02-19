from fastapi import FastAPI

from app.database import Base, engine
from app.models.job_cost_ledger import JobCostLedger  # noqa: F401
from app.models import time_entry, workflow_execution  # noqa: F401
from app.routers.auth import router as auth_router
from app.routers.costing import router as costing_router
from app.routers.time_entries import router as time_entries_router
from app.routers.workflow_preview import router as preview_router
from app.services.ledger_immutability import install_job_cost_ledger_immutability

app = FastAPI(title="Frontier Operational Systems")


@app.on_event("startup")
def _startup() -> None:
    Base.metadata.create_all(bind=engine)
    install_job_cost_ledger_immutability(engine)


app.include_router(auth_router)
app.include_router(preview_router)
app.include_router(time_entries_router)
app.include_router(costing_router)


@app.get("/")
def root():
    return {"status": "Frontier Operational Systems running"}
