from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config import settings
from database import database_healthcheck, get_db
from price_updater import get_price_runtime_status

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
def health_root() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "host": settings.app_host,
        "port": settings.app_port,
    }


@router.get("/ready")
def health_ready(db: Session = Depends(get_db)) -> dict:
    return {
        "status": "ready",
        "app": settings.app_name,
        "version": settings.app_version,
        "host": settings.app_host,
        "port": settings.app_port,
        "prices": get_price_runtime_status(db),
    }


@router.get("/db")
def health_db(db: Session = Depends(get_db)) -> dict:
    payload = {
        "status": "ok",
    }
    payload.update(database_healthcheck(db))
    return payload
