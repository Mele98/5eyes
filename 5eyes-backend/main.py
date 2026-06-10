from contextlib import asynccontextmanager
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from core.logging_setup import configure_logging
from core.middleware import RequestContextMiddleware
from database import init_db
from price_updater import start_price_scheduler, stop_price_scheduler
from backup_scheduler import start_backup_scheduler, stop_backup_scheduler

# Import all models so SQLAlchemy registers them
import models.allocation  # noqa
import models.clients  # noqa
import models.client_login  # noqa  Sprint U-36 (2026-06-06)
import models.fx_rate  # noqa
import models.mandates  # noqa
import models.profiling  # noqa
import models.review  # noqa
import models.users  # noqa
import models.snapshots  # noqa
import models.protocol_bausteine  # noqa  Bug-#13a (2026-06-07) — Beratungsprotokoll-Bausteine
import models.tenant  # noqa  Sprint T1 (2026-06-08) — 3-Tier-Foundation
import models.wealth  # noqa
from routers.allocation import router as allocation_router
from routers.auth import router as auth_router, users_router
from routers.client_portal import router as client_portal_router
from routers.cost_disclosure import router as cost_disclosure_router  # FIDLEG Art. 8/9 (2026-06-08)
from routers.clients import router as clients_router
from routers.health import router as health_router
from routers.mandates import router as mandates_router
from routers.market_data import router as market_data_router
from routers.prices import router as prices_router
from routers.profiling import router as profiling_router
from routers.protocol_bausteine import router as protocol_bausteine_router  # Bug-#13a (2026-06-07)
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
from routers.tenants import router as tenants_router  # Sprint T4 (2026-06-08)
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
    # U-32: Discover externe Tax-Regime-Plugins (Entry-Point group
    # '5eyes.tax_regime'). Boot bricht NICHT ab wenn ein Plugin kaputt
    # ist — failed_plugins werden geloggt + ueber den DiscoveryResult
    # auditierbar.
    try:
        from services.tax.discovery import discover_external_regimes
        tax_discovery = discover_external_regimes()
        if tax_discovery.discovered_count:
            logger.info(
                'Tax-Plugin-Discovery | discovered=%d loaded=%d failed=%d skipped=%d',
                tax_discovery.discovered_count,
                len(tax_discovery.loaded_plugins),
                len(tax_discovery.failed_plugins),
                len(tax_discovery.skipped_plugins),
            )
    except Exception as exc:  # noqa: BLE001 — Discovery darf Boot nicht stoppen
        logger.warning('Tax-Plugin-Discovery skipped due to error: %s', exc)
    start_price_scheduler()
    start_backup_scheduler()
    try:
        yield
    finally:
        stop_backup_scheduler()
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
app.include_router(tenants_router)  # Sprint T4 (2026-06-08)
app.include_router(client_portal_router)  # Sprint U-36 (2026-06-06)
app.include_router(protocol_bausteine_router)  # Bug-#13a (2026-06-07)
app.include_router(cost_disclosure_router)  # FIDLEG Art. 8/9 Ex-ante (2026-06-08)


# ---------------------------------------------------------------------------
# Bug-#6 (2026-06-07): Reporting-Sub-App vom Backend servieren
# ---------------------------------------------------------------------------
# Vorher: openReportingApp() oeffnete http://localhost:5173 — ein Vite-
# Dev-Server, der in der Demo/Produktion nicht laeuft. Resultat:
# ERR_CONNECTION_REFUSED. Fix: gebauter Reporting-Bundle wird unter
# /reporting/ als Static-Mount serviert, inkl. SPA-Fallback fuer
# react-router-Pfade (z.B. /reporting/mandates/<id>/report).
_REPORTING_DIST = (
    Path(__file__).resolve().parent.parent
    / "5eyes-electron" / "frontend" / "reporting" / "dist"
)
if _REPORTING_DIST.is_dir() and (_REPORTING_DIST / "index.html").is_file():
    # Assets unter /reporting/assets/ statisch — sonst SPA-Fallback.
    app.mount(
        "/reporting/assets",
        StaticFiles(directory=str(_REPORTING_DIST / "assets")),
        name="reporting_assets",
    )

    @app.get("/reporting", include_in_schema=False)
    @app.get("/reporting/{full_path:path}", include_in_schema=False)
    def reporting_spa_fallback(full_path: str = "") -> FileResponse:
        # react-router uebernimmt die Pfad-Aufloesung; wir liefern stets
        # die index.html. Asset-Pfade (.js/.css) sind oben gemountet und
        # werden nie hier landen.
        if full_path.startswith("assets/"):
            raise HTTPException(status_code=404)
        return FileResponse(_REPORTING_DIST / "index.html")
else:
    logger.warning(
        'Reporting-Dist nicht gefunden (%s) — Advisory-Report-Button '
        'wird ERR_CONNECTION_REFUSED zeigen. Build via: '
        '`cd 5eyes-electron/frontend/reporting && npm run build`.',
        _REPORTING_DIST,
    )


# ---------------------------------------------------------------------------
# Browser-Hosting (2026-06-10): Haupt-App 5eyes_v2.html ueber das Backend
# ausliefern (gated via settings.serve_main_frontend). Ein einzelner Host/
# Tunnel stellt so die komplette App im Browser bereit (Remote-Demo). Default
# AUS: Tier-1/Electron laedt die HTML weiterhin lokal via file://.
# Eintritts-URL: /app/5eyes_v2.html  (relative Assets desktop-api.js /
# vendor/chart.min.js liegen daneben; das Frontend ruft die API same-origin).
# ---------------------------------------------------------------------------
_MAIN_FRONTEND_DIR = (
    Path(__file__).resolve().parent.parent / "5eyes-electron" / "frontend"
)
if settings.serve_main_frontend and (_MAIN_FRONTEND_DIR / "5eyes_v2.html").is_file():
    from fastapi.responses import RedirectResponse

    @app.get("/app", include_in_schema=False)
    def _main_app_entry() -> RedirectResponse:
        return RedirectResponse(url="/app/5eyes_v2.html")

    app.mount(
        "/app",
        StaticFiles(directory=str(_MAIN_FRONTEND_DIR), html=False),
        name="main_frontend",
    )
    logger.info("Browser-Hosting aktiv: Haupt-App unter /app/5eyes_v2.html")


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
