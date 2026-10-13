import asyncio
import logging
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.core.exceptions import ChorantaException
from app.db.init_db import init_db
from app.api.routes import (
    auth, clients, agents, dashboard,
    agent_configuration, catalogs, runtime,
    websocket_audio, webrtc_audio, telephony, mock_environment, test_scenarios, pricing, inventory, billing, portal, plans
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("choranta")


INVENTORY_SYNC_CHECK_S = 60


async def _inventory_sync_loop() -> None:
    """Keeps client property inventories in sync with their Google Sheets / APIs."""
    from app.db.session import SessionLocal
    from app.services.inventory_sync import run_due_syncs
    while True:
        try:
            await asyncio.to_thread(run_due_syncs, SessionLocal)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Inventory sync loop error: {type(e).__name__}: {e}")
        await asyncio.sleep(INVENTORY_SYNC_CHECK_S)


async def _number_rental_loop() -> None:
    """Renews phone number rent from client wallets each month and releases unpaid numbers."""
    from app.db.session import SessionLocal
    from app.services.phone_numbers import run_rental_cycle_job
    while True:
        try:
            await asyncio.to_thread(run_rental_cycle_job, SessionLocal)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Number rental loop error: {type(e).__name__}: {e}")
        await asyncio.sleep(settings.NUMBER_RENTAL_CHECK_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup validation and seeding
    logger.info("Initializing Choranta Internal Agent Studio backend...")
    init_db()
    background = (
        [asyncio.create_task(_inventory_sync_loop()), asyncio.create_task(_number_rental_loop())]
        if settings.ENVIRONMENT != "test" else []
    )
    yield
    # Shutdown
    for task in background:
        task.cancel()
    logger.info("Shutting down Choranta backend...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Internal operating system for configuring, testing, and managing AI voice employees.",
    lifespan=lifespan
)

# CORS Middleware (Origin-validated)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


# Exception handler for domain/application exceptions
@app.exception_handler(ChorantaException)
async def choranta_exception_handler(request: Request, exc: ChorantaException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.message,
            "details": exc.details,
            "type": exc.__class__.__name__
        }
    )


# Global fallback exception handler (prevents stack trace leakage in production)
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled system error on {request.method} {request.url.path}: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "An internal system error occurred. Operations staff have been notified.",
            "type": "InternalServerError"
        }
    )


# Health check
@app.get("/health", tags=["System"])
def health_check():
    return {
        "status": "healthy",
        "service": "choranta-backend",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "runtime_mode": settings.RUNTIME_MODE,
        "external_provider_calls_enabled": settings.RUNTIME_MODE == "real"
    }


# Include API routes
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(clients.router, prefix=settings.API_V1_PREFIX)
app.include_router(agents.router, prefix=settings.API_V1_PREFIX)
app.include_router(agent_configuration.router, prefix=settings.API_V1_PREFIX)
app.include_router(catalogs.router, prefix=settings.API_V1_PREFIX)
app.include_router(dashboard.router, prefix=settings.API_V1_PREFIX)
app.include_router(runtime.router, prefix=settings.API_V1_PREFIX)
app.include_router(mock_environment.router, prefix=settings.API_V1_PREFIX)
app.include_router(test_scenarios.router, prefix=settings.API_V1_PREFIX)
app.include_router(telephony.router, prefix=settings.API_V1_PREFIX)
app.include_router(pricing.router, prefix=settings.API_V1_PREFIX)
app.include_router(inventory.router, prefix=settings.API_V1_PREFIX)
app.include_router(billing.router, prefix=settings.API_V1_PREFIX)
app.include_router(portal.router, prefix=settings.API_V1_PREFIX)
app.include_router(plans.router, prefix=settings.API_V1_PREFIX)
app.include_router(telephony.router)
app.include_router(telephony.ws_router)
app.include_router(websocket_audio.router)
app.include_router(webrtc_audio.router)
