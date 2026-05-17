"""FX-Rates-Endpoints — Berater pflegt Wechselkurse zu CHF.

Spec: docs/planning/2026-05-17-sprint-9-multi-currency.md Phase 2
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, new_uuid
from models.fx_rate import FXRate
from models.users import User
from services.auth import get_current_user, require_advisor
from services.currency.fx_rates import DEFAULT_FX_RATES, FXRateSource

router = APIRouter(tags=["FX Rates"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class FXRateEntry(BaseModel):
    currency: str
    rate: float  # rate-to-CHF (1 unit currency = rate CHF)
    source: Optional[str] = "Manual"
    notes: Optional[str] = None


class FXRatesPayload(BaseModel):
    rates: list[FXRateEntry]


class FXRateResponse(BaseModel):
    currency: str
    rate: float
    source: str
    valid_from: str
    updated_at: str


@router.get("/fx-rates/current", response_model=list[FXRateResponse])
def list_current_fx_rates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Listet alle aktuellen FX-Rates (is_current=1). Fallback auf Default
    wenn DB leer."""
    rows = (
        db.query(FXRate)
        .filter(FXRate.is_current == 1, FXRate.valid_until.is_(None))
        .order_by(FXRate.currency)
        .all()
    )
    if rows:
        return [
            FXRateResponse(
                currency=str(r.currency),
                rate=float(r.rate_x10000) / 10000.0,
                source=str(r.source or "Manual"),
                valid_from=str(r.valid_from),
                updated_at=str(r.updated_at),
            )
            for r in rows
        ]
    # DB leer → Defaults zurueckgeben (Berater sieht was er pflegen koennte)
    now = _now_iso()
    return [
        FXRateResponse(
            currency=ccy,
            rate=rate,
            source="Default",
            valid_from=now,
            updated_at=now,
        )
        for ccy, rate in sorted(DEFAULT_FX_RATES.items())
    ]


@router.put("/fx-rates", response_model=list[FXRateResponse])
def upsert_fx_rates(
    payload: FXRatesPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    """Upsert mehrere FX-Rates. Alte is_current=1 Werte werden auf
    is_current=0 + valid_until=now gesetzt (Versionierung)."""
    if not payload.rates:
        raise HTTPException(status_code=400, detail="No rates provided")

    now = _now_iso()
    affected_currencies: set[str] = set()

    for entry in payload.rates:
        ccy = entry.currency.upper().strip()
        if len(ccy) != 3:
            raise HTTPException(
                status_code=422, detail=f"Invalid currency '{entry.currency}'"
            )
        if entry.rate <= 0:
            raise HTTPException(
                status_code=422, detail=f"Rate for '{ccy}' must be > 0"
            )
        if ccy == "CHF" and abs(entry.rate - 1.0) > 1e-6:
            raise HTTPException(
                status_code=422, detail="CHF rate must be 1.0 (base currency)"
            )

        # Alte is_current=1 invalidieren
        old_rows = db.query(FXRate).filter(
            FXRate.currency == ccy,
            FXRate.is_current == 1,
        ).all()
        for old in old_rows:
            old.is_current = 0
            old.valid_until = now
            old.updated_at = now

        # Neue Zeile
        row = FXRate(
            id=new_uuid(),
            currency=ccy,
            rate_x10000=int(round(float(entry.rate) * 10000)),
            valid_from=now,
            valid_until=None,
            is_current=1,
            source=str(entry.source or "Manual"),
            notes=entry.notes,
            created_at=now,
            updated_at=now,
            created_by=str(getattr(current_user, "id", None) or ""),
        )
        db.add(row)
        affected_currencies.add(ccy)

    db.commit()
    return list_current_fx_rates(db=db, current_user=current_user)
