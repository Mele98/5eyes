from contextlib import asynccontextmanager
import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from core.logging_setup import configure_logging
from core.middleware import RequestContextMiddleware
from database import init_db
from price_updater import start_price_scheduler, stop_price_scheduler

# Import all models so SQLAlchemy registers them
import models.allocation  # noqa
import models.clients  # noqa
import models.fx_rate  # noqa
import models.mandates  # noqa
import models.profiling  # noqa
import models.review  # noqa
import models.users  # noqa
import models.snapshots  # noqa
import models.wealth  # noqa
from routers.allocation import router as allocation_router
from routers.auth import router as auth_router, users_router
from routers.clients import router as clients_router
from routers.health import router as health_router
from routers.mandates import router as mandates_router
from routers.market_data import router as market_data_router
from routers.prices import router as prices_router
from routers.profiling import router as profiling_router
from routers.review import (
    dashboard_router,
    products_router,
    recommendations_router,
    router as review_router,
)
from routers.fx_rates import router as fx_rates_router
from routers.pdf_reports import router as pdf_reports_router
from routers.snapshots import router as snapshots_router
from routers.system import router as system_router
from routers.wealth import router as wealth_router


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and background services on startup."""
    configure_logging()
    logger.info(
        'Starting application | app=%s version=%s env=%s host=%s port=%s scheduler_enabled=%s sqlcipher_enabled=%s',
        settings.app_name,
        settings.app_version,
        settings.app_env,
        settings.app_host,
        settings.app_port,
        settings.price_scheduler_enabled,
        settings.db_use_sqlcipher,
    )
    init_db()
    start_price_scheduler()
    try:
        yield
    finally:
        stop_price_scheduler()
        logger.info('Application shutdown completed')


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="5Eyes WealthArchitekten — Lokale Beratungssoftware API",
    lifespan=lifespan,
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(clients_router)
app.include_router(mandates_router)
app.include_router(profiling_router)
app.include_router(wealth_router)
app.include_router(allocation_router)
app.include_router(review_router)
app.include_router(products_router)
app.include_router(recommendations_router)
app.include_router(dashboard_router)
app.include_router(prices_router)
app.include_router(snapshots_router)
app.include_router(market_data_router)
app.include_router(fx_rates_router)
app.include_router(pdf_reports_router)
app.include_router(system_router)


@app.get("/", tags=["Health"])
def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "host": settings.app_host,
        "port": settings.app_port,
    }


def run() -> None:
    """Entry point for both local Python runs and the PyInstaller EXE."""
    uvicorn.run(
        app,
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )


if __name__ == '__main__':
    run()
