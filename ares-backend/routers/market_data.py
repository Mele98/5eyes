"""P16 — Admin-Router fuer Multi-Source-Aggregator-Diagnose.

Endpoint: GET /admin/market-data/status (admin-only).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models.users import User
from services.auth import require_admin
from services.market_data.admin import build_market_data_status

router = APIRouter(prefix="/admin/market-data", tags=["MarketData"])


@router.get("/status")
def get_market_data_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return build_market_data_status(db)
