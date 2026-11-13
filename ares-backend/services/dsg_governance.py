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
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import text

from config import settings
from database import new_uuid
from models.privacy import OutboundProcessingEvent, OutboundTransferDailyCount
from core.reason_codes import ReasonCode
from services import egress_manifest
from services.currency.fx_rates import DEFAULT_FX_RATES
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
                db.add(OutboundProcessingEvent(
                    id=new_uuid(), tenant_id=INSTALLATION_TENANT, occurred_at=item["at"],
                    channel_id=item.get("channel"), channel_class=item.get("channel_class"),
                    destination_host=item["host"] or "", reason_code=str(item["reason_code"]), result="BLOCKED",
                    manifest_version=item.get("manifest_version"), channel_sha256=item.get("channel_sha256"),
                    manifest_sha256=item.get("manifest_sha256"), payload_schema_hash=item.get("payload_schema_hash"),
                ))
            db.commit()
    return sink


def _counter_sink(session_factory: Callable[[], Any]) -> Callable[[dict], None]:
    def sink(counts: dict) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with session_factory() as db:
            for (day, channel_id), value in counts.items():
                row = db.query(OutboundTransferDailyCount).filter(
                    OutboundTransferDailyCount.tenant_id == INSTALLATION_TENANT,
                    OutboundTransferDailyCount.day == day, OutboundTransferDailyCount.channel_id == channel_id,
                ).first()
                if row is None:
                    db.add(OutboundTransferDailyCount(id=new_uuid(), tenant_id=INSTALLATION_TENANT, day=day,
                                                      channel_id=channel_id, allowed_count=value, updated_at=stamp))
                else:
                    row.allowed_count += value
                    row.updated_at = stamp
            db.commit()
    return sink


def _client_names(session_factory: Callable[[], Any]) -> Callable[[], list[tuple[str, str]]]:
    """Erfasste Kundennamen als (Vorname, Nachname) -- Nachnamen-Teile
    (Doppelnamen) werden einzeln geprueft (N-899-12)."""
    def provider() -> list[tuple[str, str]]:
        with session_factory() as db:
            rows = db.execute(text(
                "SELECT first_name, last_name, partner_first_name, partner_last_name FROM clients "
                "WHERE erased_at IS NULL"
            )).all()
        names = []
        for first, last, partner_first, partner_last in rows:
            names.append((first or "", last or ""))
            if partner_first or partner_last:
                names.append((partner_first or "", partner_last or ""))
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
                             client_name_provider=_client_names(session_factory),
                             counter_sink=_counter_sink(session_factory))


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


REASON_LABELS = {
    "EGRESS_MANIFEST_MISSING": "keine freigegebene Fassung",
    "EGRESS_HASH_MISMATCH": "Fassung veraltet (neu freigeben)",
    "EGRESS_GUARANTEE_MISSING": "Staat/Garantie/Verschluesselung fehlt",
    "EGRESS_CONSENT_OR_BASIS_MISSING": "Grundlage der Bekanntgabe fehlt",
    "EGRESS_DESTINATION_DENIED": "Zielhost nicht bestaetigt",
}
FX_DEFAULT_MESSAGE = "Ersatzkurs – nicht aktuell"

# N-899-16: Klartext fuer Owner und Berater (Kanal-IDs/Reason-Codes nur in der Detailansicht).
PLAIN_CLASS_LABELS = {
    "market_data": "Marktdaten", "reference_data": "Produktdaten", "macro_data": "Zins- und Wirtschaftsdaten",
    "alerting": "Warnmeldungen", "mail": "E-Mail", "telemetry": "Fehlerberichte", "updates": "Updates",
}
PLAIN_CHANNEL_LABELS = {"operator.backup_offsite": "externe Datensicherung",
                        "operator.database": "Datenbank-Server"}
PLAIN_OWNER_GAPS = {
    "EGRESS_GUARANTEE_MISSING": "fehlen noch Angaben (Land/Garantie des Anbieters)",
    "EGRESS_CONSENT_OR_BASIS_MISSING": "fehlt noch die Grundlage der Datenweitergabe",
    "EGRESS_DESTINATION_DENIED": "ist der Zielserver noch nicht bestätigt",
}
ADVISOR_HINT = "Bitte Administrator informieren."


# Bereichsnamen in Einzahl (alle anderen sind Mehrzahl: "Marktdaten sind").
PLAIN_SINGULAR = frozenset({"E-Mail", "externe Datensicherung", "Datenbank-Server"})


def _plain_label(channel_id: str, channel_class: str) -> str:
    return PLAIN_CHANNEL_LABELS.get(channel_id) or PLAIN_CLASS_LABELS.get(channel_class, channel_class)


def _plain_list(labels: list[str]) -> str:
    unique = list(dict.fromkeys(labels))
    return unique[0] if len(unique) == 1 else ", ".join(unique[:-1]) + " und " + unique[-1]


def _plain_subject(labels: list[str]) -> str:
    """Aufzaehlung mit passendem Verb: "E-Mail ist", "Marktdaten sind",
    "E-Mail und Updates sind"."""
    unique = list(dict.fromkeys(labels))
    verb = "ist" if len(unique) == 1 and unique[0] in PLAIN_SINGULAR else "sind"
    return f"{_plain_list(unique)} {verb}"


def plain_summary(blocked: list[dict[str, Any]]) -> list[str]:
    """N-899-16/-17: Saetze in Alltagssprache. "Nach dem Update" nur bei
    echtem Wechsel der Manifest-Version; geaenderte Angaben/Ziele eigener
    Satz; fehlende Freigabe; fehlende Owner-Angaben je Bereich."""
    def labels(change):
        return [_plain_label(b["channel_id"], b["class"]) for b in blocked if b.get("change") == change]

    lines = []
    if labels("manifest_update"):
        lines.append("Nach dem Update muss die Datenübermittlung einmal neu freigegeben werden – "
                     f"{_plain_subject(labels('manifest_update'))} bis dahin pausiert.")
    if labels("changed"):
        lines.append("Angaben zur Datenübermittlung wurden geändert – bitte einmal neu freigeben "
                     f"({_plain_subject(labels('changed'))} bis dahin pausiert).")
    if labels("unapproved"):
        lines.append("Die Datenübermittlung muss einmal freigegeben werden – "
                     f"{_plain_subject(labels('unapproved'))} bis dahin pausiert.")
    gaps: dict[str, list[str]] = {}
    for b in blocked:
        gap = b.get("owner_block") or b["reason_code"]
        if gap in PLAIN_OWNER_GAPS:
            gaps.setdefault(gap, []).append(_plain_label(b["channel_id"], b["class"]))
    for code, names in gaps.items():
        lines.append(f"Für {_plain_list(names)} {PLAIN_OWNER_GAPS[code]}.")
    return lines


def banner_action(blocked: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Knopf je Fall: fehlende Angaben zuerst (sie gehen in den Fassungs-Hash
    ein), sonst Freigabe."""
    if not blocked:
        return None
    gap = next((b for b in blocked if b.get("owner_field")), None)
    if gap:
        return {"label": "Angaben ergänzen", "field": gap["owner_field"]}
    return {"label": "Jetzt freigeben", "field": None}


def _channel_configured(channel: dict[str, Any]) -> bool:
    if channel.get("enforcement") == "desktop_update_gate":
        return bool(versions.configured_hosts(channel))
    if channel.get("enforcement") not in ("python_runtime_guard", "subprocess_guard"):
        return False
    return egress_manifest.channel_enabled(channel, settings)


def _fx_status(db: Any) -> dict[str, Any]:
    rows = db.execute(text(
        "SELECT currency, MAX(valid_from) FROM fx_rates WHERE is_current = 1 AND valid_until IS NULL "
        "GROUP BY currency")).all()
    present = {str(r[0]) for r in rows}
    defaults = sorted(c for c in DEFAULT_FX_RATES if c not in present and c != "CHF")
    return {
        "fx_rates_as_of": max((r[1] for r in rows if r[1]), default=None),
        "fx_default_currencies": defaults,
        "fx_message": f"{FX_DEFAULT_MESSAGE}: {', '.join(defaults)}" if defaults else None,
    }


def egress_status(db: Any) -> dict[str, Any]:
    """H10 Nachtrag 2/3: kein stiller Ausfall. Jeder aktivierte Kanal, der
    aus irgendeinem Grund gesperrt ist (keine/veraltete Freigabe, fehlende
    Owner-Angaben, Garantie, Grundlage, Zielhost), mit Grund; Datenstand der
    Kurse und Devisen (Ersatzkurse sichtbar). Es wird nie ein Ersatzkurs
    geschrieben."""
    manifest = egress_manifest.load_manifest()
    states = channel_states(db)
    blocked = []
    approved_channels = sorted(
        cid for cid, state in states.items()
        if state.get("approval_exempt") or (state.get("approved_sha256")
                                            and state.get("approved_sha256") == state.get("current_sha256"))
    )
    for channel in egress_manifest.channels(manifest):
        if not _channel_configured(channel):
            continue
        state = states.get(channel["id"]) or {}
        code = None
        if not state.get("approval_exempt"):
            if not state.get("approved_sha256"):
                code = ReasonCode.EGRESS_MANIFEST_MISSING.value
            elif state.get("approved_sha256") != state.get("current_sha256"):
                code = ReasonCode.EGRESS_HASH_MISMATCH.value
        change = None
        if code == ReasonCode.EGRESS_MANIFEST_MISSING.value:
            change = "unapproved"
        elif code == ReasonCode.EGRESS_HASH_MISMATCH.value:
            approved_version = state.get("approved_manifest_version")
            change = ("manifest_update" if approved_version and approved_version != manifest["manifest_version"]
                      else "changed")
        if state.get("owner_block") and not code:
            code = state.get("owner_block")
        if code:
            blocked.append({"channel_id": channel["id"], "class": channel["class"], "reason_code": code,
                            "reason": REASON_LABELS.get(code, code), "change": change,
                            "owner_block": state.get("owner_block"), "owner_field": state.get("owner_field")})
    market_blocked = any(b["class"] == "market_data" for b in blocked)
    data_as_of = {
        "product_prices": db.execute(text("SELECT MAX(price_date) FROM price_history")).scalar(),
        "asset_class_prices": db.execute(text("SELECT MAX(price_date) FROM asset_class_price_history")).scalar(),
        **_fx_status(db),
    }
    return {
        "approved": not blocked,
        "blocked_channels": blocked,
        "approved_channels": approved_channels,
        "blocked_classes": sorted({b["class"] for b in blocked}),
        "message": EGRESS_BLOCKED_MESSAGE if blocked else None,
        "plain_summary": plain_summary(blocked),
        "advisor_hint": ADVISOR_HINT if blocked else None,
        "action": banner_action(blocked),
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
