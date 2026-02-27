from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import configure_logging
from app.services.outbox_worker import start_outbox_worker_task
from app.models import employee, job, job_cost_ledger, scope, time_entry, workflow_execution  # noqa: F401
from app.routers.auth import router as auth_router
from app.routers.costing import router as costing_router
from app.routers.employees import router as employees_router
from app.routers.jobs import router as jobs_router
from app.routers.scopes import router as scopes_router
from app.routers.time_entries import router as time_entries_router
from app.routers.payroll import router as payroll_router
from app.routers.outbox import router as outbox_router
from app.routers.workflow_preview import router as preview_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()

    task = start_outbox_worker_task()
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                # worker crash during shutdown; already logged.
                pass


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
app.include_router(payroll_router)
app.include_router(outbox_router)
app.include_router(costing_router)
app.include_router(employees_router)
app.include_router(jobs_router)
app.include_router(scopes_router)


@app.get("/")
def root():
    return {"status": "Frontier Operational Systems running"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "1.0.0",
    }
