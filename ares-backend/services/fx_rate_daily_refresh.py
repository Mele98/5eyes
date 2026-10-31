"""Sprint U-99 (2026-06-05): Dedicated FX-Rate-Refresh-Trigger.

Pre-U-99 war der FX-Refresh in services/market_data_daily_refresh.py
zusammen mit Product-Prices + Asset-Class-Proxy-Prices gebuendelt — wenn
ein Berater nur die FX-Reihen aktualisieren wollte (z.B. nach Wochenend-
Pflege ohne den vollen Marktdaten-Sweep), musste er den vollen
Daily-Refresh anstoesen (langsamer + mehr API-Calls).

Dieses Modul exposed ausschliesslich den FX-Pfad als eigenstaendige
Operation. Wiederverwendet die existierende _refresh_fx_rates-Logik
(asset_class_fx_history Upsert, yfinance "CHF=X"-Symbol-Konvention),
damit kein Drift zwischen den beiden Pfaden entsteht.

Genutzt von:
  - POST /admin/system/fx-rates/refresh-now (Berater-Recovery-Trigger)
  - Eigener APScheduler-Job moeglich (Future-Sprint)
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def run_daily_fx_refresh(db: Session) -> dict[str, Any]:
    """FX-only Refresh — nur asset_class_fx_history wird aktualisiert.

    Returns dict im selben Schema wie run_daily_market_data_refresh, aber
    nur mit FX-bezogenen Feldern + status. Berater-relevante Logs landen
    automatisch im selben Audit-Pfad via Admin-Endpoint (U-102).
    """
    from services.market_data.factory import build_default_aggregator
    from services.market_data_daily_refresh import _refresh_fx_rates

    started_at = _utc_now_iso()
    started_perf = time.perf_counter()
    errors: list[dict] = []

    aggregator = build_default_aggregator()
    fx_added = _refresh_fx_rates(db, aggregator, errors)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    finished_at = _utc_now_iso()
    duration_seconds = max(time.perf_counter() - started_perf, 0.000001)
    return {
        "status": "ok" if not errors else "degraded",
        "scope": "fx_only",
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(duration_seconds, 6),
        "fx_added": fx_added,
        "errors": errors,
    }
