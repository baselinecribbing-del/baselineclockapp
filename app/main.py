from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import inspect
from sqlalchemy.exc import ProgrammingError

from app.core.logging import configure_logging
from app.database import engine
from app.models.job_cost_ledger import JobCostLedger  # noqa: F401
from app.models import time_entry, workflow_execution  # noqa: F401
from app.routers.auth import router as auth_router
from app.routers.costing import router as costing_router
from app.routers.time_entries import router as time_entries_router
from app.routers.workflow_preview import router as preview_router
from app.services.ledger_immutability import install_job_cost_ledger_immutability

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    try:
        if inspect(engine).has_table("job_cost_ledger"):
            pass
    except ProgrammingError:
        logger.warning("Skipping ledger immutability install (table missing)")
    yield


app = FastAPI(
    title="Frontier Operational Systems",
    lifespan=lifespan,
)


@app.middleware("http")
async def catch_unhandled_exceptions(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        logger.exception("Unhandled exception")
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


app.include_router(auth_router)
app.include_router(preview_router)
app.include_router(time_entries_router)
app.include_router(costing_router)


@app.get("/")
def root():
    return {"status": "Frontier Operational Systems running"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "1.0.0",
    }
