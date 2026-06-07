"""Sprint T5 (2026-06-08): Tier-Specific-Configuration-Layer.

Liefert ein konsistentes Bundle aus tier-abhaengigen Settings basierend
auf settings.deployment_tier. Vereinfacht das Setup fuer Lizenz-Nehmer —
sie setzen NUR deployment_tier, alles andere wird abgeleitet.

# Architektur
get_effective_tenancy_config(settings) -> EffectiveTenancyConfig

Diese Funktion ist die Single-Source-of-Truth fuer alle Tier-abgeleiteten
Einstellungen. Routers/Services nutzen die effective_*-Felder statt direkt
auf settings.tenancy_mode etc. zuzugreifen.

# Override-Pfad
Lizenz-Nehmer kann via .env explizite Werte setzen die das Default-
Mapping ueberschreiben. Beispiel: Tier 1 + tenancy_mode=multi (Multi-User
Familienberatungs-Test-Setup).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EffectiveTenancyConfig:
    """Auswertung der tier-abgeleiteten Konfiguration.

    Felder:
    - deployment_tier: 'tier1' | 'tier2' | 'tier3'
    - tenancy_mode: 'single' | 'multi' (effective, ggf. user-override)
    - tenant_admin_ui_enabled: bool (effective)
    - recommended_db_engine: 'sqlite' | 'postgres' (Empfehlung, keine Hard-Constraint)
    - external_backup_required: bool (Compliance-Hint)
    - audit_log_streaming_required: bool (Compliance-Hint)
    - finma_outsourcing_notification_required: bool (Tier 2/3)
    """
    deployment_tier: str
    tenancy_mode: str
    tenant_admin_ui_enabled: bool
    recommended_db_engine: str
    external_backup_required: bool
    audit_log_streaming_required: bool
    finma_outsourcing_notification_required: bool


# Tier-Defaults — diese Mappings sind die Single-Source-of-Truth fuer
# das auto-derived Verhalten. Lizenz-Nehmer kann via .env ueberschreiben.
_TIER_DEFAULTS = {
    "tier1": {
        "tenancy_mode": "single",
        "tenant_admin_ui_enabled": False,
        "recommended_db_engine": "sqlite",
        "external_backup_required": False,
        "audit_log_streaming_required": False,
        "finma_outsourcing_notification_required": False,
    },
    "tier2": {
        "tenancy_mode": "multi",
        "tenant_admin_ui_enabled": True,
        "recommended_db_engine": "postgres",
        "external_backup_required": True,
        "audit_log_streaming_required": True,
        "finma_outsourcing_notification_required": True,
    },
    "tier3": {
        "tenancy_mode": "single",
        "tenant_admin_ui_enabled": False,
        "recommended_db_engine": "postgres",
        "external_backup_required": True,
        "audit_log_streaming_required": True,
        "finma_outsourcing_notification_required": True,
    },
}


def get_effective_tenancy_config(settings_obj: Any) -> EffectiveTenancyConfig:
    """Sprint T5: Liefert die effektive tier-abgeleitete Konfiguration.

    Reihenfolge der Auswertung pro Feld:
    1. Wenn settings_obj das Feld explizit gesetzt hat (default = False/None
       wird als "nicht gesetzt" betrachtet) → user-override
    2. Sonst → Tier-Default aus _TIER_DEFAULTS

    Wenn deployment_tier unbekannt: Fallback auf 'tier1' (defensive).
    """
    tier = str(getattr(settings_obj, "deployment_tier", "tier1") or "tier1")
    if tier not in _TIER_DEFAULTS:
        tier = "tier1"
    defaults = _TIER_DEFAULTS[tier]

    # tenancy_mode: respect user-override wenn explizit != "single" gesetzt
    # (oder vice versa). Hier nutzen wir die Convention: wenn settings ein
    # explizites tenancy_mode hat das NICHT dem Tier-Default entspricht,
    # ist es als Override gemeint.
    user_tenancy = getattr(settings_obj, "tenancy_mode", None)
    if user_tenancy in ("single", "multi"):
        tenancy_mode = user_tenancy
    else:
        tenancy_mode = defaults["tenancy_mode"]

    # tenant_admin_ui_enabled: settings hat default False — wenn der User
    # explizit True setzt, respektieren wir das (z.B. Tier 1 mit aktiviertem
    # Admin-UI fuer Test/Migration). Sonst Tier-Default.
    user_admin_ui = getattr(settings_obj, "tenant_admin_ui_enabled", None)
    if user_admin_ui is True:
        tenant_admin_ui_enabled = True
    elif user_admin_ui is False and tier in ("tier1", "tier3"):
        tenant_admin_ui_enabled = False
    else:
        tenant_admin_ui_enabled = defaults["tenant_admin_ui_enabled"]

    return EffectiveTenancyConfig(
        deployment_tier=tier,
        tenancy_mode=tenancy_mode,
        tenant_admin_ui_enabled=tenant_admin_ui_enabled,
        recommended_db_engine=str(defaults["recommended_db_engine"]),
        external_backup_required=bool(defaults["external_backup_required"]),
        audit_log_streaming_required=bool(defaults["audit_log_streaming_required"]),
        finma_outsourcing_notification_required=bool(
            defaults["finma_outsourcing_notification_required"]
        ),
    )


def list_compliance_requirements(config: EffectiveTenancyConfig) -> list[str]:
    """Sprint T5: Liefert eine menschen-lesbare Liste der Compliance-Pflichten
    fuer den aktuellen Tier.

    Wird vom System-Endpoint (oder Frontend) als Berater-Hinweis-Liste
    angezeigt.
    """
    items: list[str] = []
    if config.external_backup_required:
        items.append("Off-Site-Backup empfohlen (Tier-Compliance)")
    if config.audit_log_streaming_required:
        items.append("Audit-Log-Streaming zu externem System empfohlen")
    if config.finma_outsourcing_notification_required:
        items.append(
            "FINMA-Outsourcing-Anzeige pflichtig (Tier 2/3, RS 2018/3)"
        )
    if config.tenant_admin_ui_enabled:
        items.append("Tenant-Admin-UI aktiv — AVV-Template pflichtig (revDSG)")
    if config.deployment_tier == "tier1":
        items.append(
            "Self-Hosted: Berater ist Datenherr — Backup-Verantwortung beim Berater"
        )
    return items
