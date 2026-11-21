"""Owner-Inhalte: Katalog, Pruefung und Aufloesung (H-179, L2/L3).

Ares erfindet keinen Rechtstext und keinen Owner-Wert. Dieser Katalog kennt
nur SCHLUESSEL, Bezeichnungen und den Platzhalter ``__OWNER_..._REQUIRED__``,
nie einen Text. Die Firma erfasst Inhalte versioniert
(models/contract_layer.py::OwnerContentVersion); wirksam ist nur die juengste
Version mit Vier-Augen-Freigabe (OwnerContentApproval) in einer lueckenlosen,
siegelgleichen Freigabekette. Alles andere ist "nicht freigegeben".

Gruppen (Dok. 112 Kap. 7.1):

* ``vertrag``: Pflichtklauseln je Mandatstyp (V-1, darin A-1 Rechenschaft und
  D-1 Datenbearbeitung/Delegation). Schluessel ``vertrag.<typ>.<klausel>``;
  ein gemeinsamer Text ``vertrag.gemeinsam.<klausel>`` gilt fuer alle Typen,
  ein typspezifischer hat Vorrang.
* ``datenschutz``: Abschnitt Datenbearbeitung der Kundeninformation (D-1,
  DSG Art. 19 Abs. 2).
* ``w033``: Restinhalte der Eignungspruefung (E-1, Dok. 112 Kap. 4.1).
* ``depotbank``: Zuwendungen der Depotbank je Bankbeziehung (R-1) als
  typisierter Wert.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import text as _sql_text
from sqlalchemy.orm import Session

from models.contract_layer import OWNER_CONTENT_GENESIS
from services.recommendation_release_gate import row_seal

CATALOG_VERSION = "ARES-OWNER-KATALOG-1"

KIND_TEXT = "text"
KIND_INTEGER = "integer"
KIND_DEPOT_BANK = "depot_bank_inducement"

STATUS_APPROVED = "freigegeben"
STATUS_UNAPPROVED = "nicht_freigegeben"
STATUS_MISSING = "fehlt"
STATUS_INVALID = "kette_ungueltig"

# ---------------------------------------------------------------------------
# V-1: Mandatstypen mit Vertragsvorlage und Pflichtklauseln (Dok. 112 7.1 V-1)
# ---------------------------------------------------------------------------

CONTRACT_MANDATE_TYPES: dict[str, str] = {
    "Vermögensverwaltung": "vv",
    "Anlageberatung": "anlageberatung",
    "Finanzplanung": "finanzplanung",
}
CONTRACT_SHARED_SLUG = "gemeinsam"

# (Klauselschluessel, Bezeichnung, was der Owner liefern muss, Platzhalter).
CONTRACT_CLAUSES: tuple[tuple[str, str, str, str], ...] = (
    ("parteien_personalien", "Parteien und Personalien",
     "Wortlaut der Parteienbezeichnung (Firma, Kunde, Vertretung)", "__OWNER_VERTRAG_PARTEIEN_REQUIRED__"),
    ("leistung", "Leistung",
     "Leistungsumfang des Mandatstyps", "__OWNER_VERTRAG_LEISTUNG_REQUIRED__"),
    ("bestandteile", "Vertragsbestandteile",
     "Bestandteile (Strategiedokument, Gebührenvereinbarung, Kundeninformation)",
     "__OWNER_VERTRAG_BESTANDTEILE_REQUIRED__"),
    ("rechenschaft", "Rechenschaft",
     "Abgrenzung der Rechenschaft: wer liefert Vermögensausweis, Performance und Ex-post-Kosten "
     "(Depotbank-Auszüge), mit welcher Periodizität", "__OWNER_REPORTING_MODEL_REQUIRED__"),
    ("kommunikation_zustellung", "Kommunikation und Zustellung",
     "Kanäle, Zustellung über Portal/E-Mail inkl. Risikohinweis", "__OWNER_VERTRAG_KOMMUNIKATION_REQUIRED__"),
    ("datenbearbeitung_geheimnisentbindung", "Datenbearbeitung und Geheimnisentbindung",
     "Datenbearbeitung, Entbindung vom Geheimnis gegenüber Depotbank/Dritten",
     "__OWNER_VERTRAG_DATENBEARBEITUNG_REQUIRED__"),
    ("delegation", "Delegation",
     "Beizug Dritter/Delegation von Aufgaben", "__OWNER_VERTRAG_DELEGATION_REQUIRED__"),
    ("ausschluss_steuer_rechtsberatung", "Keine Steuer- und Rechtsberatung",
     "Abgrenzung Steuer-/Rechtsberatung", "__OWNER_VERTRAG_STEUER_RECHT_REQUIRED__"),
    ("segmentierung_kag_qualifikation", "Kundensegment und KAG-Qualifikation",
     "Kundensegmentierung (FIDLEG) und Qualifikation nach KAG", "__OWNER_VERTRAG_SEGMENTIERUNG_REQUIRED__"),
    ("meldepflicht_kunde", "Meldepflichten des Kunden",
     "Pflicht des Kunden, wesentliche Änderungen zu melden", "__OWNER_VERTRAG_MELDEPFLICHT_REQUIRED__"),
    ("wohnsitzwechsel", "Wohnsitzwechsel",
     "Folgen eines Wohnsitzwechsels", "__OWNER_VERTRAG_WOHNSITZ_REQUIRED__"),
    ("steuerkonformitaet", "Steuerkonformität",
     "Steuerkonformität des Kunden", "__OWNER_VERTRAG_STEUERKONFORMITAET_REQUIRED__"),
    ("beendigung", "Beendigung",
     "Beendigung des Auftrags (OR 404)", "__OWNER_VERTRAG_BEENDIGUNG_REQUIRED__"),
    ("recht_gerichtsstand", "Anwendbares Recht und Gerichtsstand",
     "anwendbares Recht, Gerichtsstand/Sitz (OWN-BRAND-01)", "__OWNER_VERTRAG_GERICHTSSTAND_REQUIRED__"),
)
CONTRACT_CLAUSE_KEYS: tuple[str, ...] = tuple(c[0] for c in CONTRACT_CLAUSES)
CONTRACT_CLAUSE_LABELS: dict[str, str] = {c[0]: c[1] for c in CONTRACT_CLAUSES}

# ---------------------------------------------------------------------------
# D-1: Datenbearbeitung in der Kundeninformation (DSG Art. 19 Abs. 2)
# ---------------------------------------------------------------------------

PRIVACY_SECTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("verantwortlicher", "Verantwortlicher", "Identität des Verantwortlichen", "__OWNER_DSG_VERANTWORTLICHER_REQUIRED__"),
    ("kontakt", "Kontakt Datenschutz", "Kontaktdaten für Datenschutzanliegen", "__OWNER_DSG_KONTAKT_REQUIRED__"),
    ("zwecke", "Bearbeitungszwecke", "Zwecke der Bearbeitung", "__OWNER_DSG_ZWECKE_REQUIRED__"),
    ("empfaenger", "Empfänger", "Empfänger bzw. Kategorien von Empfängern", "__OWNER_DSG_EMPFAENGER_REQUIRED__"),
    ("ausland", "Bekanntgabe ins Ausland", "Staaten und Garantien bzw. «keine Bekanntgabe ins Ausland»",
     "__OWNER_DSG_AUSLAND_REQUIRED__"),
    ("rechte", "Ihre Rechte", "Rechte der betroffenen Person und deren Ausübung", "__OWNER_DSG_RECHTE_REQUIRED__"),
)
PRIVACY_KEY_PREFIX = "kundeninformation.datenschutz."

# ---------------------------------------------------------------------------
# E-1: W033-Restinhalte (Dok. 112 Kap. 4.1)
# ---------------------------------------------------------------------------

W033_DECLARATION_KEY = "w033.angaben_wahr_meldepflicht"
W033_HORIZON_ADVICE_KEY = "w033.horizont_abraten"
W033_MIN_HORIZON_KEY = "w033.mindesthorizont_jahre"
W033_DISTRIBUTION_KEY = "w033.ausschuettung_kapitalunterschreitung"

# ---------------------------------------------------------------------------
# R-1: Zuwendungen der Depotbank (Bank-Ebene)
# ---------------------------------------------------------------------------

DEPOT_BANK_KEY_PREFIX = "depotbank_zuwendung."
DEPOT_BANK_STATUSES = ("keine", "satz", "verzicht")
DEPOT_BANK_PLACEHOLDER = "__OWNER_DEPOT_BANK_INDUCEMENT_REQUIRED__"


@dataclass(frozen=True)
class CatalogEntry:
    key: str
    group: str
    label: str
    kind: str
    placeholder: str
    owner_input: str
    visible_in: str
    required: bool = True


def contract_clause_key(type_slug: str, clause: str) -> str:
    return f"vertrag.{type_slug}.{clause}"


def static_catalog() -> tuple[CatalogEntry, ...]:
    """Alle festen Schluessel (ohne Bank-Schluessel, die je Bank entstehen)."""
    entries: list[CatalogEntry] = []
    for slug in (CONTRACT_SHARED_SLUG, *CONTRACT_MANDATE_TYPES.values()):
        for clause, label, owner_input, placeholder in CONTRACT_CLAUSES:
            entries.append(CatalogEntry(
                key=contract_clause_key(slug, clause), group="vertrag",
                label=f"Vertrag ({_type_label(slug)}): {label}", kind=KIND_TEXT,
                placeholder=placeholder, owner_input=owner_input,
                visible_in="Vertrags-PDF (Beratungsvertrag), Vertragsvorlagen-Hash",
                # Je Typ genuegt der typspezifische ODER der gemeinsame Text.
                required=False,
            ))
    for section, label, owner_input, placeholder in PRIVACY_SECTIONS:
        entries.append(CatalogEntry(
            key=PRIVACY_KEY_PREFIX + section, group="datenschutz",
            label=f"Kundeninformation – Datenbearbeitung: {label}", kind=KIND_TEXT,
            placeholder=placeholder, owner_input=owner_input,
            visible_in="Kundeninformation (Abschnitt Datenbearbeitung)",
        ))
    entries.extend((
        CatalogEntry(
            key=W033_DECLARATION_KEY, group="w033",
            label="Erklärung: Angaben wahr, wesentliche Änderungen werden gemeldet", kind=KIND_TEXT,
            placeholder="__OWNER_W033_ANGABEN_WAHR_REQUIRED__",
            owner_input="Wortlaut der Kundenerklärung",
            visible_in="Risikoprofil-PDF, Kundenbestätigung (W033)",
        ),
        CatalogEntry(
            key=W033_HORIZON_ADVICE_KEY, group="w033",
            label="Abraten bei kurzem Anlagehorizont", kind=KIND_TEXT,
            placeholder="__OWNER_W033_HORIZONT_ABRATEN_REQUIRED__",
            owner_input="Wortlaut des Abraten-Hinweises und der Kundenbestätigung",
            visible_in="Risikoprofil-PDF, Kundenbestätigung (W033)",
        ),
        CatalogEntry(
            key=W033_MIN_HORIZON_KEY, group="w033",
            label="Mindestanlagehorizont in Jahren (Owner/IC)", kind=KIND_INTEGER,
            placeholder="__OWNER_MIN_HORIZON_YEARS_REQUIRED__",
            owner_input="ganze Zahl Jahre (OWN-IC-05/06)",
            visible_in="Gate Finalisierung/Signatur, Risikoprofil-PDF",
        ),
        CatalogEntry(
            key=W033_DISTRIBUTION_KEY, group="w033",
            label="Hinweis Ausschüttung bei Kapitalunterschreitung", kind=KIND_TEXT,
            placeholder="__OWNER_W033_AUSSCHUETTUNG_REQUIRED__",
            owner_input="Wortlaut (nur nötig, wenn ausschüttende Lösungen im Universum sind)",
            visible_in="Risikoprofil-PDF (nur wenn freigegeben)",
            required=False,
        ),
    ))
    return tuple(entries)


def _type_label(slug: str) -> str:
    if slug == CONTRACT_SHARED_SLUG:
        return "alle Mandatstypen"
    for label, value in CONTRACT_MANDATE_TYPES.items():
        if value == slug:
            return label
    return slug


def depot_bank_slug(name: Any) -> str:
    """Stabiler Schluesselteil einer Depotbank (klein, ASCII, Bindestriche)."""
    raw = str(name or "").strip().lower()
    raw = raw.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")


def depot_bank_key(name: Any) -> Optional[str]:
    slug = depot_bank_slug(name)
    return DEPOT_BANK_KEY_PREFIX + slug if slug else None


def catalog_entry(key: str) -> Optional[CatalogEntry]:
    for entry in static_catalog():
        if entry.key == key:
            return entry
    if key.startswith(DEPOT_BANK_KEY_PREFIX) and depot_bank_slug(key[len(DEPOT_BANK_KEY_PREFIX):]) == key[
        len(DEPOT_BANK_KEY_PREFIX):
    ] and key != DEPOT_BANK_KEY_PREFIX:
        return CatalogEntry(
            key=key, group="depotbank", label=f"Zuwendungen der Depotbank ({key[len(DEPOT_BANK_KEY_PREFIX):]})",
            kind=KIND_DEPOT_BANK, placeholder=DEPOT_BANK_PLACEHOLDER,
            owner_input="keine | Satz + Basis | Verzicht mit Bandbreite; Beleg, Gültigkeit",
            visible_in="Kundeninformation, Kostenausweis, Gate Finalisierung/Signatur",
        )
    return None


class OwnerContentInvalid(ValueError):
    """Inhalt passt nicht zum Katalog (Router: 422 mit ``code``)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _iso_day(value: Any, field: str) -> str:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError) as exc:
        raise OwnerContentInvalid("OWNER_CONTENT_VALUE_INVALID", f"{field}: Datum JJJJ-MM-TT erwartet.") from exc


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OwnerContentInvalid("OWNER_CONTENT_VALUE_INVALID", f"{field}: ganze Zahl ≥ 0 erwartet.")
    return value


def normalize_payload(entry: CatalogEntry, body_text: Any, value: Any) -> tuple[Optional[str], Optional[str]]:
    """(body_text, value_json) fuer die Speicherung; wirft OwnerContentInvalid."""
    if entry.kind == KIND_TEXT:
        text = str(body_text or "").strip()
        if not text:
            raise OwnerContentInvalid("OWNER_CONTENT_VALUE_INVALID", "Der Text der Firma fehlt.")
        if "__OWNER_" in text:
            raise OwnerContentInvalid(
                "OWNER_CONTENT_VALUE_INVALID", "Der Text enthält noch einen Platzhalter.",
            )
        return text, None
    if entry.kind == KIND_INTEGER:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise OwnerContentInvalid("OWNER_CONTENT_VALUE_INVALID", "Erwartet wird eine ganze Zahl > 0.")
        return None, json.dumps({"value": value}, sort_keys=True)
    if not isinstance(value, dict):
        raise OwnerContentInvalid("OWNER_CONTENT_VALUE_INVALID", "Erwartet wird ein strukturierter Wert.")
    status = str(value.get("status") or "")
    if status not in DEPOT_BANK_STATUSES:
        raise OwnerContentInvalid(
            "OWNER_CONTENT_VALUE_INVALID", "status muss «keine», «satz» oder «verzicht» sein.",
        )
    bank = str(value.get("depot_bank") or "").strip()
    evidence = str(value.get("evidence_reference") or "").strip()
    if not bank:
        raise OwnerContentInvalid("OWNER_CONTENT_VALUE_INVALID", "Name der Depotbank fehlt.")
    if depot_bank_key(bank) != entry.key:
        raise OwnerContentInvalid("OWNER_CONTENT_VALUE_INVALID", "Depotbank passt nicht zum Schlüssel.")
    if not evidence:
        raise OwnerContentInvalid("OWNER_CONTENT_VALUE_INVALID", "Beleg (Dokument-Referenz) fehlt.")
    out: dict[str, Any] = {
        "depot_bank": bank, "status": status, "evidence_reference": evidence,
        "valid_from": _iso_day(value.get("valid_from"), "valid_from"),
        "valid_until": _iso_day(value["valid_until"], "valid_until") if value.get("valid_until") else None,
        "rate_bps": None, "basis": None, "range_min_bps": None, "range_max_bps": None,
    }
    if out["valid_until"] and out["valid_until"] < out["valid_from"]:
        raise OwnerContentInvalid("OWNER_CONTENT_VALUE_INVALID", "Gültigkeitsende liegt vor dem Beginn.")
    if status == "satz":
        out["rate_bps"] = _non_negative_int(value.get("rate_bps"), "rate_bps")
        out["basis"] = str(value.get("basis") or "").strip()
        if not out["basis"]:
            raise OwnerContentInvalid("OWNER_CONTENT_VALUE_INVALID", "Bemessungsbasis des Satzes fehlt.")
    elif status == "verzicht":
        low = _non_negative_int(value.get("range_min_bps"), "range_min_bps")
        high = _non_negative_int(value.get("range_max_bps"), "range_max_bps")
        if low > high:
            raise OwnerContentInvalid("OWNER_CONTENT_VALUE_INVALID", "Bandbreite: Minimum über Maximum.")
        out["range_min_bps"], out["range_max_bps"] = low, high
    return None, json.dumps(out, sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Aufloesung (gelesen per SQL wie die uebrigen Freigabe-Gates)
# ---------------------------------------------------------------------------


def _rows(db: Session, sql: str, params: dict) -> list[dict]:
    return [dict(r) for r in db.execute(_sql_text(sql), params).mappings().all()]


def owner_content_chain(db: Session, tenant_id: str, key: str) -> tuple[dict[str, dict], list[dict]]:
    versions = _rows(
        db, "SELECT * FROM owner_content_versions WHERE tenant_id = :tid AND content_key = :key",
        {"tid": str(tenant_id), "key": key},
    )
    approvals = _rows(
        db, "SELECT * FROM owner_content_approvals WHERE tenant_id = :tid AND content_key = :key",
        {"tid": str(tenant_id), "key": key},
    )
    return {str(v["id"]): v for v in versions}, approvals


def resolve_owner_content(db: Session, tenant_id: Optional[str], key: str) -> dict:
    """Wirksame Version eines Schluessels fuer eine Firma.

    ``status``: freigegeben | nicht_freigegeben (nur Entwuerfe) | fehlt |
    kette_ungueltig (Siegel- oder Kettenbruch -> nie wirksam)."""
    result: dict[str, Any] = {"key": key, "status": STATUS_MISSING, "version": None, "approval": None}
    if not tenant_id:
        return result
    versions, approvals = owner_content_chain(db, tenant_id, key)
    if not versions:
        return result
    if not approvals:
        result["status"] = STATUS_UNAPPROVED
        result["latest_draft"] = max(versions.values(), key=lambda v: int(v["version"]))
        return result
    by_predecessor: dict[str, dict] = {}
    for approval in approvals:
        pred = str(approval["predecessor_approval_id"])
        if pred in by_predecessor:
            result["status"] = STATUS_INVALID
            return result
        by_predecessor[pred] = approval
    head = None
    cursor = OWNER_CONTENT_GENESIS
    seen = 0
    last_version = 0
    while cursor in by_predecessor:
        approval = by_predecessor[cursor]
        version = versions.get(str(approval["content_row_id"]))
        if (
            version is None
            or row_seal(approval, "approval_hash") != approval["approval_hash"]
            or row_seal(version, "content_hash") != version["content_hash"]
            or approval["content_hash"] != version["content_hash"]
            or str(approval["approved_by"]) == str(version["created_by"])
            or int(version["version"]) <= last_version
        ):
            result["status"] = STATUS_INVALID
            return result
        last_version = int(version["version"])
        head = (version, approval)
        cursor = str(approval["id"])
        seen += 1
    if seen != len(approvals) or head is None:
        result["status"] = STATUS_INVALID
        return result
    result.update(status=STATUS_APPROVED, version=head[0], approval=head[1])
    newer = [v for v in versions.values() if int(v["version"]) > last_version]
    if newer:
        result["latest_draft"] = max(newer, key=lambda v: int(v["version"]))
    return result


def approved_text(resolution: dict) -> Optional[str]:
    if resolution.get("status") != STATUS_APPROVED:
        return None
    return str(resolution["version"].get("body_text") or "") or None


def approved_value(resolution: dict) -> Any:
    if resolution.get("status") != STATUS_APPROVED:
        return None
    raw = resolution["version"].get("value_json")
    try:
        parsed = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None
    return parsed


def binding_of(resolution: dict) -> dict:
    """Kompakte, hashbare Bindung einer aufgeloesten Version."""
    version = resolution.get("version") or {}
    approval = resolution.get("approval") or {}
    return {
        "key": resolution.get("key"),
        "content_row_id": version.get("id"),
        "version": version.get("version"),
        "content_hash": version.get("content_hash"),
        "approval_id": approval.get("id"),
        "approval_hash": approval.get("approval_hash"),
    }
