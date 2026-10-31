from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models.users import User
from price_updater import (
    get_price_runtime_status,
    list_price_mapping_gaps,
    refresh_all_prices,
)
from services.auth import require_admin

router = APIRouter(prefix="/admin/prices", tags=["Preise"])


@router.get("/status")
def get_price_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return get_price_runtime_status(db)


@router.get("/mapping-gaps")
def get_mapping_gaps(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    gaps = list_price_mapping_gaps(db)
    return {
        "count": len(gaps),
        "items": gaps,
    }


@router.post("/refresh")
def refresh_prices(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return refresh_all_prices(db)
