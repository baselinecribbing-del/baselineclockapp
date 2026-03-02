from contextlib import asynccontextmanager
import asyncio
import logging
import os
import pathlib

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.logging import configure_logging
from app.models import employee, job, job_cost_ledger, scope, schedule, time_entry, workflow_execution  # noqa: F401
from app.routers.auth import router as auth_router
from app.routers.costing import router as costing_router
from app.routers.employees import router as employees_router
from app.routers.jobs import router as jobs_router
from app.routers.outbox import router as outbox_router
from app.routers.payroll import router as payroll_router
from app.routers.scopes import router as scopes_router
from app.routers.schedules import router as schedules_router
from app.routers.time_entries import router as time_entries_router
from app.routers.workflow_preview import router as preview_router
from app.services.outbox_worker import start_outbox_worker_task

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


# ---- CORS (dev) ----
allowed_origins = os.getenv(
    "CORS_ALLOW_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(preview_router)
app.include_router(time_entries_router)
app.include_router(payroll_router)
app.include_router(outbox_router)
app.include_router(costing_router)
app.include_router(employees_router)
app.include_router(jobs_router)
app.include_router(scopes_router)
app.include_router(schedules_router)

# ---- Debug (dev only, hardened) ----
# Enable ONLY in local dev. Requirements:
# - ENABLE_DEBUG_ENDPOINTS=1
# - DEBUG_ENDPOINT_TOKEN must be set and must match request header X-Debug-Token
# - Requests must originate from localhost (127.0.0.1 / ::1)
_debug_enabled = os.getenv("ENABLE_DEBUG_ENDPOINTS", "0") == "1"
_debug_token = os.getenv("DEBUG_ENDPOINT_TOKEN", "")

if _debug_enabled and _debug_token:

    @app.get("/__debug/app", include_in_schema=False)
    def debug_app(request: Request):
        client_host = getattr(getattr(request, "client", None), "host", None)
        if client_host not in {"127.0.0.1", "::1"}:
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        provided = request.headers.get("X-Debug-Token", "")
        if provided != _debug_token:
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        return {
            "cwd": str(pathlib.Path().resolve()),
            "module_file": __file__,
            "cors_enabled": any(
                getattr(m, "cls", None).__name__ == "CORSMiddleware"
                for m in getattr(app, "user_middleware", [])
            ),
            "middleware": [
                {
                    "class": getattr(m, "cls", None).__name__,
                    "options": getattr(m, "options", None),
                }
                for m in getattr(app, "user_middleware", [])
            ],
        }


@app.get("/")
def root():
    return {"status": "Frontier Operational Systems running"}


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}
