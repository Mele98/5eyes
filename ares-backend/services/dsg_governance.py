"""H10 (DSG-Technikaudit 2026-11-11): Fassade der Datenschutz-Governance fuer
``routers/privacy.py``.

Der Router importiert nur dieses Modul (eine Kante statt je Fachmodul eine):

* Bearbeitungsverzeichnis und Angaben des Verantwortlichen (C-DSG-01,
  services/privacy_owner_values.py, services/processing_activity_register.py).
* Betroffenenanfragen (C-DSG-02, services/privacy_subject_requests.py).
* Egress-Manifest und Laufzeitschutz (C-DSG-03, services/egress_manifest.py).
* Register der Sicherheitsvorfaelle (C-DSG-04,
  services/security_incident_register.py).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from config import settings
from services import egress_manifest
from services import privacy_erasure_inventory as erasure_inventory
from services import privacy_subject_requests as subject_requests
from services import processing_activity_register as register_module
from services import security_incident_register as incidents
from services.privacy_owner_values import (
    OWNER_VALUE_MAX_LENGTH,
    confirmed_egress_channels,
    egress_view,
    open_blocking_fields,
    owner_field_definitions,
    owner_field_status,
    owner_values,
    register_export,
    register_view,
    set_owner_value,
)

EVIDENCE_TYPES = erasure_inventory.EVIDENCE_TYPES
ERASURE_INVENTORY_VERSION = erasure_inventory.INVENTORY_VERSION
# Egress ist eine Installationseinstellung: massgebend sind die Angaben des
# Betreiber-Mandanten (Tier 1: die eine Firma, Mandant "main").
INSTALLATION_TENANT = "main"

logger = logging.getLogger(__name__)


def activate_egress_guard(session_factory: Callable[[], Any]) -> None:
    """Laufzeitschutz beim Start einschalten. Bestaetigungen fuer Kanaele mit
    Personendaten aus der Datenbank; ist sie nicht lesbar, bleiben diese
    Kanaele gesperrt (die App startet trotzdem)."""
    confirmed: set[str] = set()
    try:
        with session_factory() as db:
            confirmed = confirmed_egress_channels(db, INSTALLATION_TENANT)
    except Exception:  # noqa: BLE001 - Start nie wegen Bestaetigungen abbrechen
        logger.exception("Egress-Bestaetigungen nicht lesbar; Kanaele mit Personendaten bleiben gesperrt")
    egress_manifest.activate(settings, confirmed_channels=confirmed)


def deactivate_egress_guard() -> None:
    egress_manifest.deactivate()


def incident_data_categories() -> set[str]:
    """Datenkategorien, die ein Vorfall betreffen kann (Register)."""
    register = register_module.load_register()
    return set(EVIDENCE_TYPES) | set(register.get("additional_data_categories") or {})


def incident_gate(db: Any, tenant_id: str) -> dict[str, Any]:
    """Gate des Incident-Registers mit den Owner-Angaben (Eskalationskontakt,
    interne Zielfrist); fehlen sie, steht das Feld als OPEN im Ergebnis."""
    values = owner_values(db, tenant_id)
    gate = incidents.gate_findings(db, tenant_id, target_hours=values.get(incidents.TARGET_HOURS_FIELD))
    contact = values.get(incidents.ESCALATION_CONTACT_FIELD)
    gate["escalation_contact"] = {
        "owner_field": incidents.ESCALATION_CONTACT_FIELD,
        "status": "CONFIRMED" if contact else "OPEN", "value": contact,
    }
    return gate


def refresh_egress_confirmations(db: Any, tenant_id: str) -> None:
    if tenant_id == INSTALLATION_TENANT:
        egress_manifest.update_confirmed_channels(confirmed_egress_channels(db, INSTALLATION_TENANT))

__all__ = [
    "ERASURE_INVENTORY_VERSION",
    "EVIDENCE_TYPES",
    "INSTALLATION_TENANT",
    "OWNER_VALUE_MAX_LENGTH",
    "activate_egress_guard",
    "confirmed_egress_channels",
    "deactivate_egress_guard",
    "egress_view",
    "incident_data_categories",
    "incident_gate",
    "incidents",
    "open_blocking_fields",
    "owner_field_definitions",
    "owner_field_status",
    "owner_values",
    "register_export",
    "refresh_egress_confirmations",
    "register_view",
    "set_owner_value",
    "subject_requests",
]
