"""WP3 (Backend-Router fuer Jurisdiktions-Verwaltung + CMA-Freigabe, 2026-07-31):
Pydantic-Schemas fuer routers/jurisdiction.py.

Baut auf dem additiven Schema aus WP1 auf (models/jurisdiction.py::
JurisdictionProfile/JurisdictionHomeBiasDefault). Diese Schemas betreffen
NUR die Verwaltung der Jurisdiktions-Stammdaten/Home-Bias-Defaults -- keine
Aenderung an bestehenden CMA-Schemas ausser der additiven Erweiterung von
CapitalMarketAssumptionResponse in schemas/allocation.py (dort, nicht hier).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator

from schemas.common import BaseResponse

# Erlaubte Werte fuer JurisdictionProfile.status, siehe models/jurisdiction.py
# Docstring ("draft" | "pending_ic_review" | "approved" | "retired").
_ALLOWED_JURISDICTION_PROFILE_STATUS = ("draft", "pending_ic_review", "approved", "retired")


class JurisdictionProfileResponse(BaseResponse):
    id: str
    code: str
    display_name: str
    home_currency: str
    is_active: int
    is_provisional: int
    status: str
    notes: Optional[str] = None
    created_at: str
    updated_at: str


class JurisdictionProfileUpdate(BaseModel):
    """Partial-Update-Body fuer PUT /jurisdictions/{code}. Nicht gesetzte
    Felder (exclude_unset) bleiben unveraendert -- code/home_currency/
    created_by/created_at sind hier bewusst NICHT editierbar (Stammdaten-
    Identitaet einer Jurisdiktion aendert sich nicht ueber dieses Update)."""

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    is_active: Optional[int] = Field(default=None, ge=0, le=1)
    status: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _validate_status(self):
        if self.status is not None and self.status not in _ALLOWED_JURISDICTION_PROFILE_STATUS:
            allowed = ", ".join(_ALLOWED_JURISDICTION_PROFILE_STATUS)
            raise ValueError(f"status muss einer von [{allowed}] sein (erhalten: {self.status!r})")
        return self


class JurisdictionHomeBiasDefaultResponse(BaseResponse):
    id: str
    jurisdiction_code: str
    preference_key: str
    preference_value: str
    sub_asset_class: str
    split_bps: int
    rationale_text: Optional[str] = None
    is_provisional: int
    sort_order: Optional[int] = None
    created_at: str
    updated_at: str


class JurisdictionHomeBiasDefaultCreate(BaseModel):
    preference_key: str = Field(..., min_length=1, max_length=80)
    preference_value: str = Field(..., min_length=1, max_length=120)
    sub_asset_class: str = Field(..., min_length=1, max_length=120)
    split_bps: int = Field(..., ge=0, le=10000)
    rationale_text: Optional[str] = None
    # Default 1 (noch nicht IC-geprueft) -- Home-Bias-Zeilen fuer eine neue
    # Jurisdiktion sind bis zur expliziten IC-Freigabe immer als provisorisch
    # zu behandeln (siehe models/jurisdiction.py Docstring).
    is_provisional: int = Field(default=1, ge=0, le=1)
    sort_order: Optional[int] = None


class JurisdictionHomeBiasDefaultUpdate(BaseModel):
    preference_key: Optional[str] = Field(default=None, min_length=1, max_length=80)
    preference_value: Optional[str] = Field(default=None, min_length=1, max_length=120)
    sub_asset_class: Optional[str] = Field(default=None, min_length=1, max_length=120)
    split_bps: Optional[int] = Field(default=None, ge=0, le=10000)
    rationale_text: Optional[str] = None
    is_provisional: Optional[int] = Field(default=None, ge=0, le=1)
    sort_order: Optional[int] = None
