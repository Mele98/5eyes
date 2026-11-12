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

from sqlalchemy import text

from config import settings
from database import new_uuid
from models.privacy import PrivacyEgressEvent
from services import egress_manifest
from services import privacy_case_events as case_events
from services import privacy_versions as versions
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


def channel_states(db: Any) -> dict[str, dict[str, Any]]:
    return versions.runtime_channel_states(db, INSTALLATION_TENANT, owner_values(db, INSTALLATION_TENANT))


def _event_sink(session_factory: Callable[[], Any]) -> Callable[[list[dict[str, Any]]], None]:
    def sink(batch: list[dict[str, Any]]) -> None:
        with session_factory() as db:
            for item in batch:
                db.add(PrivacyEgressEvent(
                    id=new_uuid(), tenant_id=INSTALLATION_TENANT, occurred_at=item["at"],
                    channel_id=item.get("channel"), channel_class=item.get("channel_class"),
                    destination_host=item["host"] or "", reason_code=str(item["reason_code"]), result="BLOCKED",
                    manifest_version=item.get("manifest_version"), channel_sha256=item.get("channel_sha256"),
                ))
            db.commit()
    return sink


def _client_names(session_factory: Callable[[], Any]) -> Callable[[], list[str]]:
    def provider() -> list[str]:
        with session_factory() as db:
            rows = db.execute(text(
                "SELECT first_name, last_name, partner_first_name, partner_last_name FROM clients "
                "WHERE erased_at IS NULL"
            )).all()
        names = []
        for first, last, partner_first, partner_last in rows:
            names.append(f"{first or ''} {last or ''}")
            if partner_first or partner_last:
                names.append(f"{partner_first or ''} {partner_last or ''}")
        return names
    return provider


def activate_egress_guard(session_factory: Callable[[], Any]) -> None:
    """Laufzeitschutz beim Start einschalten. Bestand als
    INVENTORY_REQUIRED erfassen (nie automatisch freigegeben), Freigaben und
    Owner-Angaben lesen, persistentes Protokoll und Kundennamen-Pruefung
    anschliessen. Ist die Datenbank nicht lesbar, bleibt jeder externe Kanal
    gesperrt (die App startet trotzdem)."""
    states = None
    try:
        with session_factory() as db:
            versions.ensure_inventory_rows(db, INSTALLATION_TENANT, owner_values(db, INSTALLATION_TENANT),
                                           actor_id="system")
            db.commit()
            states = channel_states(db)
    except Exception:  # noqa: BLE001 - Start nie wegen der Freigaben abbrechen
        logger.exception("Egress-Freigaben nicht lesbar; alle externen Kanaele bleiben gesperrt")
    egress_manifest.activate(settings, channel_states=states, event_sink=_event_sink(session_factory),
                             client_name_provider=_client_names(session_factory))


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


EGRESS_BLOCKED_MESSAGE = (
    "Datenübermittlung gesperrt – Marktdaten, Updates und E-Mail funktionieren erst nach Freigabe"
)
MARKET_DATA_NOT_UPDATED = "nicht aktualisiert – Datenübermittlung nicht freigegeben"


def egress_status(db: Any) -> dict[str, Any]:
    """H10 Nachtrag 2: kein stiller Ausfall. Welche konfigurierten Kanaele
    mangels gueltiger Freigabe gesperrt sind, und der Datenstand der Kurse.
    Bewertungen bleiben auf dem letzten Stand; es wird nie ein Ersatzkurs
    geschrieben."""
    manifest = egress_manifest.load_manifest()
    states = channel_states(db)
    blocked = []
    for channel in egress_manifest.channels(manifest):
        if channel.get("enforcement") != "python_runtime_guard" or not egress_manifest.channel_enabled(channel, settings):
            continue
        state = states.get(channel["id"]) or {}
        if state.get("approval_exempt"):
            continue
        if not state.get("approved_sha256") or state.get("approved_sha256") != state.get("current_sha256"):
            blocked.append({"channel_id": channel["id"], "class": channel["class"]})
    market_blocked = any(b["class"] == "market_data" for b in blocked)
    data_as_of = {
        "product_prices": db.execute(text("SELECT MAX(price_date) FROM price_history")).scalar(),
        "asset_class_prices": db.execute(text("SELECT MAX(price_date) FROM asset_class_price_history")).scalar(),
    }
    return {
        "approved": not blocked,
        "blocked_channels": blocked,
        "blocked_classes": sorted({b["class"] for b in blocked}),
        "message": EGRESS_BLOCKED_MESSAGE if blocked else None,
        "market_data_status": "NOT_UPDATED_EGRESS_BLOCKED" if market_blocked else "EGRESS_APPROVED",
        "market_data_message": MARKET_DATA_NOT_UPDATED if market_blocked else None,
        "data_as_of": data_as_of,
        "approval_path": "Administration > Compliance > Datenschutz > Manifest freigeben",
    }


def refresh_egress_confirmations(db: Any, tenant_id: str) -> None:
    if tenant_id == INSTALLATION_TENANT and egress_manifest.is_active():
        egress_manifest.update_channel_states(channel_states(db))

__all__ = [
    "ERASURE_INVENTORY_VERSION",
    "EVIDENCE_TYPES",
    "INSTALLATION_TENANT",
    "OWNER_VALUE_MAX_LENGTH",
    "activate_egress_guard",
    "case_events",
    "channel_states",
    "confirmed_egress_channels",
    "deactivate_egress_guard",
    "egress_status",
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
    "versions",
]
