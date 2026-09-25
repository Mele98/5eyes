"""FINIG-Gate fuer diskretionaere Vermoegensverwaltung (2026-08-09).

Seit Inkrafttreten des FINIG (Uebergangsfrist Ende 2022 abgelaufen) braucht
in der Schweiz jede Firma, die diskretionaere Vermoegensverwaltung anbietet,
eine FINMA-Bewilligung + Anschluss an eine Aufsichtsorganisation (AO). Reine
Anlageberatung (mandate_type="Anlageberatung") braucht nur den leichteren
Eintrag im Beraterregister (Art. 28 FIDLEG). Diese Software kann eine echte
Bewilligung nicht verifizieren -- sie kann nur erzwingen, dass ein Operator
sie fuer die lizenznehmende Firma EXPLIZIT bestaetigt (Tenant.
discretionary_management_licensed), bevor irgendein Mandat dieser Firma
mandate_type="Vermögensverwaltung" waehlen darf.

Identisches Enforcement-Muster wie services.data_classification.
enforce_data_classification() (403, kein Fail-Closed auf Kosten des
Bestandsbetriebs): Tenant.discretionary_management_licensed startet per DB-
Migration bei ALLEN Bestandsmandanten auf 1 (siehe database.py::
ensure_runtime_columns(), 'tenants') -- keine bestehende Firma wird
rueckwirkend blockiert. Nur NEUE Tenants (schemas/tenants.py::TenantCreate)
starten bewusst mit False (Opt-in fuer die hoehere Bewilligungsstufe).
"""
from __future__ import annotations

from fastapi import HTTPException

from models.tenant import Tenant

DISCRETIONARY_MANDATE_TYPE = "Vermögensverwaltung"

DISCRETIONARY_LICENSE_MISSING_DETAIL = (
    "Diese Firma ist fuer diskretionaere Vermoegensverwaltung (FINIG-"
    "Bewilligung/Anschluss an eine Aufsichtsorganisation) nicht "
    "freigeschaltet. Bitte den Operator kontaktieren."
)


def enforce_discretionary_management_license(tenant: Tenant | None, mandate_type: str | None) -> None:
    """Wirft HTTPException(403), wenn mandate_type eine diskretionaere
    Vermoegensverwaltung waehlt, die lizenznehmende Firma dafuer aber nicht
    freigeschaltet ist. Kein Tenant-Kontext (None) -> fail-open (identisches
    Backwards-Compat-Muster wie ueberall bei nullable tenant_id in dieser
    Codebase, z.B. Tenant.home_jurisdiction-Fallback).

    Kontrollrunde 2026-09-23 (FINIG-Gate-Audit): `tenant=None` bedeutete
    KEINESWEGS nur "sehr alte Datensaetze" -- jeder Bootstrap-Admin einer
    frischen Installation UND jeder von einem super_admin ohne explizites
    tenant_id angelegte User hatten tenant_id=None, wodurch jedes Mandat, das
    dieser Kette entstammt, den Gate komplett umging. Die Aufrufer
    (routers/mandates.py) loesen `tenant` jetzt IMMER via DEFAULT_TENANT_ID-
    Fallback auf einen echten Tenant auf, bevor sie hierher kommen -- `tenant
    is None` sollte praktisch nie mehr eintreten, bleibt hier aber als
    defensiver Fail-Open-Fallback (kein 500 bei unerwartet fehlendem
    DEFAULT_TENANT_ID-Datensatz), nicht als beabsichtigter Bypass-Pfad."""
    if mandate_type != DISCRETIONARY_MANDATE_TYPE:
        return
    if tenant is None:
        return
    licensed = bool(getattr(tenant, "discretionary_management_licensed", 1))
    if not licensed:
        raise HTTPException(status_code=403, detail=DISCRETIONARY_LICENSE_MISSING_DETAIL)
