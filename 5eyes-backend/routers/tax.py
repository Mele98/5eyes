"""Read-only tax estimate API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.users import User
from schemas.tax import TaxEstimateResult, TaxJurisdictionListItem, TaxProfileInput
from services.auth import get_current_user
from services.tax.parameters import get_country_parameter_sets, list_current_regions
from services.tax.registry import (
    TaxJurisdictionNotFound,
    discover_builtin_jurisdictions,
    get_jurisdiction,
    list_jurisdictions,
)


router = APIRouter(prefix="/tax", tags=["Tax"])


def _ensure_builtin_jurisdictions() -> None:
    discover_builtin_jurisdictions()


def _bind_parameter_sets(plugin, db: Session, profile: TaxProfileInput):
    parameter_sets = get_country_parameter_sets(db, profile.country_code, profile.year)
    if parameter_sets and hasattr(plugin, "with_parameter_sets"):
        return plugin.with_parameter_sets(parameter_sets)
    return plugin


@router.get("/jurisdictions", response_model=list[TaxJurisdictionListItem])
def get_tax_jurisdictions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TaxJurisdictionListItem]:
    _ = current_user
    _ensure_builtin_jurisdictions()
    items: list[TaxJurisdictionListItem] = []
    for plugin in list_jurisdictions():
        meta = plugin.metadata
        regions = list_current_regions(db, meta.country_code) or meta.supported_regions
        items.append(
            TaxJurisdictionListItem(
                country_code=meta.country_code,
                display_name=meta.display_name,
                currency=meta.currency,
                version=meta.version,
                supported_regions=regions,
            )
        )
    return items


@router.post("/estimate", response_model=TaxEstimateResult)
def estimate_tax(
    profile: TaxProfileInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaxEstimateResult:
    _ = current_user
    _ensure_builtin_jurisdictions()
    try:
        plugin = get_jurisdiction(profile.country_code)
    except TaxJurisdictionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    plugin = _bind_parameter_sets(plugin, db, profile)
    return plugin.estimate(profile)

