"""Sprint T4 (2026-06-08): Tenant-API-Schemas.

Pydantic-Schemas fuer Tenant-Admin-Endpoints. Verwendet von:
- routers/tenants.py
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.tenant import (
    ALLOWED_LICENSE_STATUS,
    ALLOWED_PRESENTATION_MODES,
    ALLOWED_TIERS,
    LICENSE_STATUS_TRIAL,
    TIER_1_SELF_HOSTED,
)


class TenantCreate(BaseModel):
    """Request-Body fuer POST /tenants (super_admin only)."""

    display_name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=2, max_length=80,
                       pattern=r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$")
    hosting_tier: str = Field(default=TIER_1_SELF_HOSTED)
    license_status: str = Field(default=LICENSE_STATUS_TRIAL)
    license_valid_until: Optional[str] = None
    max_users: Optional[int] = Field(default=1, ge=0)
    max_mandates: Optional[int] = Field(default=None, ge=0)
    storage_quota_mb: Optional[int] = Field(default=None, ge=1)
    # 2026-07-27 (Retrozessions-Feature): firmenweite Vorbelegung fuer neue
    # Interessenkonflikt-Offenlegungen, siehe models/tenant.py.
    default_retrocession_reimbursement: bool = False
    # 2026-08-01 (Onboarding): Land der lizenznehmenden Firma, siehe
    # models/tenant.py. None = "CH" (Default fuer bestehende/neue Firmen
    # ohne explizite Angabe).
    home_jurisdiction: Optional[str] = None
    # 2026-08-02 (HUD-Polish): firmenweiter Default fuer die UI-"Maske",
    # siehe models/tenant.py. None = "wealthmanagement".
    default_presentation_mode: Optional[str] = None
    # 2026-08-09 (FINIG-Gate): siehe models/tenant.py +
    # services/tenant_licensing.py. Default False -- neue Firmen muessen die
    # FINIG-Bewilligung/AO-Anschluss explizit bestaetigen, bevor sie
    # mandate_type="Vermögensverwaltung" ueberhaupt waehlen duerfen (Opt-in,
    # kein Opt-out). Bestandsfirmen sind ueber die DB-Migration bereits auf
    # True gesetzt -- betrifft nur Firmen, die AB JETZT neu angelegt werden.
    discretionary_management_licensed: bool = False

    @field_validator("hosting_tier")
    @classmethod
    def _validate_tier(cls, v: str) -> str:
        if v not in ALLOWED_TIERS:
            raise ValueError(
                f"hosting_tier muss eines von {ALLOWED_TIERS} sein, war: {v!r}"
            )
        return v

    @field_validator("license_status")
    @classmethod
    def _validate_license_status(cls, v: str) -> str:
        if v not in ALLOWED_LICENSE_STATUS:
            raise ValueError(
                f"license_status muss eines von {ALLOWED_LICENSE_STATUS} sein, war: {v!r}"
            )
        return v

    @field_validator("default_presentation_mode")
    @classmethod
    def _validate_presentation_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if v not in ALLOWED_PRESENTATION_MODES:
            raise ValueError(
                f"default_presentation_mode muss eines von {ALLOWED_PRESENTATION_MODES} sein, war: {v!r}"
            )
        return v


class TenantUpdate(BaseModel):
    """Request-Body fuer PUT /tenants/{id} (Partial-Update)."""

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    hosting_tier: Optional[str] = None
    license_status: Optional[str] = None
    license_valid_until: Optional[str] = None
    finma_outsourcing_notified_at: Optional[str] = None
    avv_signed_at: Optional[str] = None
    max_users: Optional[int] = Field(default=None, ge=0)
    max_mandates: Optional[int] = Field(default=None, ge=0)
    storage_quota_mb: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[int] = Field(default=None, ge=0, le=1)
    default_retrocession_reimbursement: Optional[bool] = None
    home_jurisdiction: Optional[str] = None
    default_presentation_mode: Optional[str] = None
    # 2026-08-09 (FINIG-Gate): nur super_admin darf das setzen (PUT /tenants/{id},
    # nicht Teil von TenantSelfServiceUpdate -- eine Firma kann sich die
    # Bewilligung nicht selbst attestieren).
    discretionary_management_licensed: Optional[bool] = None

    @field_validator("hosting_tier")
    @classmethod
    def _validate_tier(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if v not in ALLOWED_TIERS:
            raise ValueError(f"hosting_tier ungueltig: {v!r}")
        return v

    @field_validator("license_status")
    @classmethod
    def _validate_license_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if v not in ALLOWED_LICENSE_STATUS:
            raise ValueError(f"license_status ungueltig: {v!r}")
        return v

    @field_validator("default_presentation_mode")
    @classmethod
    def _validate_presentation_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if v not in ALLOWED_PRESENTATION_MODES:
            raise ValueError(f"default_presentation_mode ungueltig: {v!r}")
        return v


class TenantResponse(BaseModel):
    """Public Tenant-Response fuer API-Endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    slug: str
    hosting_tier: str
    license_status: str
    license_valid_until: Optional[str] = None
    finma_outsourcing_notified_at: Optional[str] = None
    avv_signed_at: Optional[str] = None
    max_users: Optional[int] = None
    max_mandates: Optional[int] = None
    storage_quota_mb: Optional[int] = None
    default_retrocession_reimbursement: int = 0
    home_jurisdiction: Optional[str] = None
    default_presentation_mode: Optional[str] = None
    discretionary_management_licensed: int = 1
    is_active: int
    created_at: str
    updated_at: str


class UserAssignTenantRequest(BaseModel):
    """Request-Body fuer PUT /users/{user_id}/tenant."""

    tenant_id: str = Field(..., min_length=1, max_length=100)


class TenantSelfServiceUpdate(BaseModel):
    """2026-08-01 (Onboarding): Request-Body fuer PUT /tenants/me.

    Bewusst SCHMALER als TenantUpdate (kein hosting_tier/license_status/
    max_users etc.) -- ein normaler Firmen-Admin (nicht super_admin) darf
    NUR die eigene Firmenidentitaet/den eigenen Standort pflegen, keine
    Lizenz-/Kapazitaets-Parameter. Funktioniert TIER-UNABHAENGIG (im
    Gegensatz zu PUT /tenants/{id}, das in Tier 1/3 per
    settings.tenant_admin_ui_enabled deaktiviert ist)."""

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    home_jurisdiction: Optional[str] = None
    default_presentation_mode: Optional[str] = None

    @field_validator("default_presentation_mode")
    @classmethod
    def _validate_presentation_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if v not in ALLOWED_PRESENTATION_MODES:
            raise ValueError(f"default_presentation_mode ungueltig: {v!r}")
        return v
