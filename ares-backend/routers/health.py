"""Sprint U-63 (2026-06-01): Health-Endpoints mit Readiness/Liveness-Split.

Pattern (k8s / docker / oncall-Standard):
- /health            -> root summary (backwards-compat, alle Felder)
- /health/live       -> liveness probe: Prozess laeuft, KEINE DB-Abhaengigkeit
                        (nur fuer Process-Restart-Entscheidung)
- /health/ready      -> readiness probe: DB erreichbar + dependent services
                        (entscheidet ob Traffic geroutet wird), 503 bei Fehler
- /health/db         -> DB-spezifischer Detail-Check

Warum Split:
- Liveness ohne DB-Abhaengigkeit verhindert Restart-Cascade bei
  DB-Outage. Prozess lebt, soll nicht gekillt werden.
- Readiness MIT DB-Check entzieht Traffic bei DB-Outage, Prozess
  bleibt aber laufen.
- /health (root) bleibt als Backwards-Compat fuer existierende
  Electron-Probes (siehe main.js EXPECTED_BACKEND_APP-Check).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from config import settings
from database import SchemaNotReadyError, database_healthcheck, get_db
from price_updater import get_price_runtime_status

router = APIRouter(prefix="/health", tags=["Health"])


def _base_payload() -> dict:
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "host": settings.app_host,
        "port": settings.app_port,
    }


@router.get("")
def health_root() -> dict:
    """Backwards-compat Root-Endpoint. Antwortet immer 200 wenn der
    Prozess Requests entgegennimmt — kein DB-Hit."""
    return {"status": "ok", **_base_payload()}


@router.get("/live")
def health_live() -> dict:
    """U-63 (2026-06-01): Liveness-Probe.

    Entscheidet ob der Prozess RESTARTET werden muss. Soll NICHT
    von DB/External-Services abhaengen — sonst wuerden DB-Outages
    einen Process-Restart triggern und die Recovery noch verzoegern.
    """
    return {"status": "alive", **_base_payload()}


@router.get("/ready")
def health_ready(db: Session = Depends(get_db)) -> dict:
    """U-63 (2026-06-01): Readiness-Probe.

    Entscheidet ob TRAFFIC zum Prozess gerouted wird. Prueft DB-
    Verbindung — bei DB-Outage 503 (Traffic stoppen), Prozess bleibt
    aber laufen (Liveness intakt). price_runtime_status ist
    informational (non-blocking).
    """
    payload = {"status": "ready", **_base_payload()}
    try:
        payload["database"] = database_healthcheck(db).get("database", "ok")
    except SchemaNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "not_ready",
                "reason": "schema_not_ready",
                "error": str(exc).split("\n", 1)[0][:200],
                **_base_payload(),
            },
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "not_ready",
                "reason": "database_unreachable",
                "error": str(exc).split("\n", 1)[0][:200],
                **_base_payload(),
            },
        ) from exc
    # Preise: informational, KEIN 503-Auslöser (Markdaten-Provider
    # koennen vorübergehend down sein ohne dass Beratung blockiert).
    try:
        payload["prices"] = get_price_runtime_status(db)
    except Exception as exc:  # noqa: BLE001
        payload["prices"] = {"status": "unknown", "error": str(exc)[:200]}
    return payload


@router.get("/db")
def health_db(db: Session = Depends(get_db)) -> dict:
    payload = {"status": "ok"}
    payload.update(database_healthcheck(db))
    return payload
