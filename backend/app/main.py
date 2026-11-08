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
from app.db.mongo import KnowledgeStoreUnavailable
from app.api.routes import (
    auth, clients, agents, dashboard,
    agent_configuration, catalogs, client_knowledge, runtime,
    websocket_audio, webrtc_audio, telephony, mock_environment, test_scenarios, pricing, inventory, billing, portal, plans,
    campaigns, api_keys, public_leads, agent_requests, verifications, demo_leads, courses, call_scripts, whatsapp, qualification, numbers, finance
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("choranta")


INVENTORY_SYNC_CHECK_S = 60
CAPACITY_STATS_FLUSH_S = 60


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


async def _campaign_loop() -> None:
    """Places outbound campaign calls inside their calling windows and records outcomes."""
    from app.db.session import SessionLocal
    from app.services.campaigns import run_campaign_job
    from app.runtime import draining
    while True:
        try:
            if draining.is_draining():
                return  # shutting down: let live calls finish, place no new ones
            await asyncio.to_thread(run_campaign_job, SessionLocal)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Campaign loop error: {type(e).__name__}: {e}")
        await asyncio.sleep(settings.CAMPAIGN_TICK_S)


async def _billing_sweep_loop() -> None:
    """Charges finished calls that were never billed (e.g. the server restarted mid-call)."""
    from app.db.session import SessionLocal
    from app.services.billing import run_billing_sweep_job
    while True:
        try:
            await asyncio.to_thread(run_billing_sweep_job, SessionLocal)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Billing sweep error: {type(e).__name__}: {e}")
        await asyncio.sleep(settings.BILLING_SWEEP_S)


async def _capacity_stats_loop() -> None:
    """Saves the capacity counters (peak calls, refusals, Sarvam rejections) for the Finance page."""
    from app.db.session import SessionLocal
    from app.services.capacity_stats import run_capacity_stats_job
    while True:
        await asyncio.sleep(CAPACITY_STATS_FLUSH_S)
        try:
            await asyncio.to_thread(run_capacity_stats_job, SessionLocal)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Capacity stats error: {type(e).__name__}: {e}")


async def _whatsapp_loop() -> None:
    """Sends queued WhatsApp follow-ups and checks follow-up messages waiting for WhatsApp's approval."""
    from app.db.session import SessionLocal
    from app.services.whatsapp_followups import run_whatsapp_job
    while True:
        try:
            await asyncio.to_thread(run_whatsapp_job, SessionLocal)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"WhatsApp loop error: {type(e).__name__}: {e}")
        await asyncio.sleep(settings.WHATSAPP_TICK_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup validation and seeding
    logger.info("Initializing Choranta Internal Agent Studio backend...")
    init_db()
    background = (
        [
            asyncio.create_task(_inventory_sync_loop()),
            asyncio.create_task(_number_rental_loop()),
            asyncio.create_task(_campaign_loop()),
            asyncio.create_task(_billing_sweep_loop()),
            asyncio.create_task(_capacity_stats_loop()),
            asyncio.create_task(_whatsapp_loop()),
        ]
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


# MongoDB being unreachable is an outage, not a bug: say so plainly (the message holds no server details)
@app.exception_handler(KnowledgeStoreUnavailable)
async def knowledge_store_unavailable_handler(request: Request, exc: KnowledgeStoreUnavailable):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"error": str(exc), "details": None, "type": "KnowledgeStoreUnavailable"}
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
    from app.runtime import draining
    if draining.is_draining():
        # Shutting down after live calls end: tell load balancers to send new traffic elsewhere
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            content={"status": "draining", "live_calls": draining.live_calls()})
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
app.include_router(client_knowledge.router, prefix=settings.API_V1_PREFIX)
app.include_router(numbers.router, prefix=settings.API_V1_PREFIX)
app.include_router(client_knowledge.portal_router, prefix=settings.API_V1_PREFIX)
app.include_router(call_scripts.router, prefix=settings.API_V1_PREFIX)
app.include_router(dashboard.router, prefix=settings.API_V1_PREFIX)
app.include_router(runtime.router, prefix=settings.API_V1_PREFIX)
app.include_router(mock_environment.router, prefix=settings.API_V1_PREFIX)
app.include_router(test_scenarios.router, prefix=settings.API_V1_PREFIX)
app.include_router(telephony.router, prefix=settings.API_V1_PREFIX)
app.include_router(pricing.router, prefix=settings.API_V1_PREFIX)
app.include_router(pricing.public_router, prefix=settings.API_V1_PREFIX)
app.include_router(inventory.router, prefix=settings.API_V1_PREFIX)
app.include_router(billing.router, prefix=settings.API_V1_PREFIX)
app.include_router(finance.router, prefix=settings.API_V1_PREFIX)
app.include_router(portal.router, prefix=settings.API_V1_PREFIX)
app.include_router(plans.router, prefix=settings.API_V1_PREFIX)
app.include_router(campaigns.router, prefix=settings.API_V1_PREFIX)
app.include_router(campaigns.portal_router, prefix=settings.API_V1_PREFIX)
app.include_router(api_keys.portal_router, prefix=settings.API_V1_PREFIX)
app.include_router(api_keys.admin_router, prefix=settings.API_V1_PREFIX)
app.include_router(public_leads.router, prefix=settings.API_V1_PREFIX)
app.include_router(agent_requests.portal_router, prefix=settings.API_V1_PREFIX)
app.include_router(agent_requests.admin_router, prefix=settings.API_V1_PREFIX)
app.include_router(verifications.router, prefix=settings.API_V1_PREFIX)
app.include_router(courses.portal_router, prefix=settings.API_V1_PREFIX)
app.include_router(courses.admin_router, prefix=settings.API_V1_PREFIX)
app.include_router(whatsapp.router, prefix=settings.API_V1_PREFIX)
app.include_router(whatsapp.portal_router, prefix=settings.API_V1_PREFIX)
app.include_router(qualification.portal_router, prefix=settings.API_V1_PREFIX)
app.include_router(telephony.router)
app.include_router(telephony.ws_router)
app.include_router(websocket_audio.router)
app.include_router(webrtc_audio.router, prefix=settings.API_V1_PREFIX)
app.include_router(webrtc_audio.portal_router, prefix=settings.API_V1_PREFIX)
if settings.ENVIRONMENT != "production":
    app.include_router(demo_leads.router)  # dev-only demo website form at /demo/lead-form
