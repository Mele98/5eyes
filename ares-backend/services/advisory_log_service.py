"""Sprint U-FINMA-2.1 — Service-Layer fuer AdvisoryLog.

Zentralisiert:
- JSON-Serialisierung der List-Felder (participants, topics, risk_warnings, …)
- Integrity-Hash-Berechnung beim Persist
- retain_until-Berechnung (H7 C-6: Mandatsende + 10 Jahre, nie kuerzer als
  entry_datetime + 10 Jahre; offenes Mandat = NULL, Frist laeuft noch nicht)
- Versions-Geschichte: Update legt neue Zeile an, alte wird superseded
- Response-Serialisierung (DB-Strings -> Python-Listen)
- Read-Audit (last_read_at / last_read_by)

So bleiben die Router-Endpoints dünn und die FINMA-Logik an einer Stelle
testbar.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from sqlalchemy import text as _sql_text
from sqlalchemy.orm import Session, object_session

from database import new_uuid
from models.review import AdvisoryLog, MandateReportNotes
from services import pii_vault
from services.advisory_log_integrity import (  # noqa: F401 (L2c-Re-Export)
    ADVISORY_LOG_SEALED_FIELDS,
    CONFLICT_SEALED_FIELDS,
    REPORT_NOTE_FIELDS,
    protocol_text_seal,
    report_note_version_hash,
    compute_integrity_hash,
    compute_relationship_retain_until,
    extended_retain_until,
    verify_integrity_hash,
)

if TYPE_CHECKING:
    from models.users import User


_LIST_FIELDS = (
    ("participants", "participants_json"),
    ("topics", "topics_json"),
    ("risk_warnings_given", "risk_warnings_given_json"),
    ("conflict_disclosure_ids", "conflict_disclosure_ids_json"),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _dump_json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        # Bereits JSON? Pass-through nur wenn parsebar.
        try:
            json.loads(value)
            return value
        except (TypeError, ValueError):
            return json.dumps([value])
    # Pydantic-Model-Liste -> dict-Liste serialisierbar machen
    serialized = []
    for item in value:
        if hasattr(item, "model_dump"):
            serialized.append(item.model_dump())
        else:
            serialized.append(item)
    return json.dumps(serialized, ensure_ascii=False)


def _load_json(raw: str | None) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _load_json_object(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


# ---------------------------------------------------------------------------
# L2c (H-192): versiegelte Protokoll-Freitexte (DSG-Loeschpfad per Crypto-
# Shred, Muster services/pii_vault.py wie L2b fuer advice_rationales).
#
# Pruefsummen-Schema "Siegel ueber den Umschlag": Freitexte werden VOR dem
# Siegeln mit dem Kundenschluessel versiegelt; das Zeilensiegel (hier
# ``integrity_hash``, KN9a) rechnet ueber den GESPEICHERTEN Wert, also den
# Umschlag. Nach einer DSG-Loeschung (Schluessel vernichtet) bleibt es
# pruefbar: "geloescht" ist nicht "manipuliert". Ein veraenderter Umschlag
# (Siegel falsch, Fernet-Pruefung scheitert, Schluessel eines anderen
# Kunden, Tombstone ohne belegte Loeschung) ist "veraendert" und sperrt alle
# Kundenkanaele (409 ADVISORY_LOG_INTEGRITY_FAILED).
#
# Alle Lesestellen gehen ueber diese Funktionen; keine Stelle gibt einen
# Umschlag roh aus.
# ---------------------------------------------------------------------------
PROTOCOL_TEXT_OK = "ok"
PROTOCOL_TEXT_ERASED = "geloescht_dsg"
PROTOCOL_TEXT_TAMPERED = "veraendert"
ERASED_TEXT = "Gelöscht (DSG)."
ProtocolTextSealError = pii_vault.PiiVaultError
ProtocolReader = pii_vault.KeyReader


def mandate_client_id(db: Session, mandate_id: Any) -> str | None:
    return pii_vault.KeyReader(db).client_of_mandate(mandate_id)


def seal_protocol_value(db: Session, client_id: str | None, value: Any) -> Any:
    """Versiegelt einen Freitext (None/leer bleibt). Fail-closed
    ``ProtocolTextSealError`` ohne Kunde oder nach DSG-Loeschung."""
    return pii_vault.seal_for_client(db, client_id, value)


def reveal_protocol_values(
    db: Session | None, client_id: str | None, values: dict[str, Any], fields,
    *, reader: pii_vault.KeyReader | None = None,
) -> tuple[dict[str, Any], str]:
    """(Klartexte, Zustand) fuer die genannten Felder.

    Zustand ``veraendert`` dominiert ``geloescht_dsg`` dominiert ``ok``.
    Geloeschte Felder kommen als ``None`` zurueck (Aufrufer zeigt
    ``ERASED_TEXT``). Ohne Session laesst sich ein Umschlag nicht oeffnen:
    das gilt als ``veraendert`` (nie Umschlag ausgeben)."""
    plain: dict[str, Any] = {}
    state = PROTOCOL_TEXT_OK
    if reader is None and db is not None:
        reader = pii_vault.KeyReader(db)
    for field in fields:
        value = values.get(field)
        if not pii_vault.is_sealed(value):
            plain[field] = value
            continue
        if db is None:
            plain[field] = None
            state = PROTOCOL_TEXT_TAMPERED
            continue
        text_value, status = pii_vault.reveal_state(db, value, client_id=client_id or "", reader=reader)
        if status == pii_vault.REVEAL_SHREDDED:
            plain[field] = None
            if state == PROTOCOL_TEXT_OK:
                state = PROTOCOL_TEXT_ERASED
        elif status == pii_vault.REVEAL_UNREADABLE:
            plain[field] = None
            state = PROTOCOL_TEXT_TAMPERED
        else:
            plain[field] = text_value
    return plain, state


def seal_advisory_entry_texts(db: Session, entry: AdvisoryLog, client_id: str | None) -> None:
    """Versiegelt die Freitexte eines (noch nicht gesiegelten) Eintrags."""
    for field in ADVISORY_LOG_SEALED_FIELDS:
        setattr(entry, field, seal_protocol_value(db, client_id, getattr(entry, field, None)))


def advisory_entry_text_state(
    db: Session | None, entry: Any, *, reader: pii_vault.KeyReader | None = None,
) -> tuple[dict[str, Any], str]:
    """(Klartexte, Zustand) der versiegelten Felder eines Eintrags."""
    values = {field: getattr(entry, field, None) for field in ADVISORY_LOG_SEALED_FIELDS}
    if db is None:
        db = reader.db if reader is not None else (
            object_session(entry) if isinstance(entry, AdvisoryLog) else None)
    if not any(pii_vault.is_sealed(v) for v in values.values()):
        return values, PROTOCOL_TEXT_OK
    if db is None:
        return reveal_protocol_values(None, None, values, ADVISORY_LOG_SEALED_FIELDS)
    reader = reader or pii_vault.KeyReader(db)
    client_id = reader.client_of_mandate(getattr(entry, "mandate_id", None))
    return reveal_protocol_values(db, client_id, values, ADVISORY_LOG_SEALED_FIELDS, reader=reader)


def conflict_text_view(
    db: Session | None, row: Any, *, client_id: str | None = None, reader: pii_vault.KeyReader | None = None,
) -> dict[str, Any]:
    """Interessenkonflikt -> Anzeigeform mit Klartext, ``text_state`` und
    ``integrity_verified`` (Siegel ueber die Umschlaege)."""
    values = {field: getattr(row, field, None) for field in CONFLICT_SEALED_FIELDS}
    stored_seal = getattr(row, "text_seal", None)
    if db is None:
        db = object_session(row)
    if client_id is None and db is not None:
        reader = reader or pii_vault.KeyReader(db)
        client_id = reader.client_of_mandate(getattr(row, "mandate_id", None))
    plain, state = reveal_protocol_values(db, client_id, values, CONFLICT_SEALED_FIELDS, reader=reader)
    verified: bool | None = None
    if stored_seal:
        verified = protocol_text_seal(
            getattr(row, "id", None), getattr(row, "mandate_id", None), values, CONFLICT_SEALED_FIELDS,
        ) == stored_seal
        if not verified:
            state = PROTOCOL_TEXT_TAMPERED
    elif any(pii_vault.is_sealed(v) for v in values.values()):
        # Versiegelt, aber ohne Siegel: kann nicht von uns stammen.
        state = PROTOCOL_TEXT_TAMPERED
    if state == PROTOCOL_TEXT_TAMPERED:
        verified = False
        plain = {field: None for field in CONFLICT_SEALED_FIELDS}
    if state == PROTOCOL_TEXT_ERASED:
        plain = {field: (ERASED_TEXT if values.get(field) else None) for field in CONFLICT_SEALED_FIELDS}
    # mitigation_action ist eine Kategorie (CHECK-Liste), kein versiegelter Freitext.
    return {"description": plain.get("description") or "", "mitigation_action": getattr(row, "mitigation_action", None),
            "text_state": state, "integrity_verified": verified}


def seal_conflict_texts(db: Session, row: Any, client_id: str | None) -> None:
    """Versiegelt die Beschreibung und setzt das Zeilensiegel."""
    for field in CONFLICT_SEALED_FIELDS:
        setattr(row, field, seal_protocol_value(db, client_id, getattr(row, field, None)))
    row.text_seal = protocol_text_seal(
        row.id, row.mandate_id, {f: getattr(row, f, None) for f in CONFLICT_SEALED_FIELDS},
        CONFLICT_SEALED_FIELDS,
    )


# L2c: Berichtsnotizen (mandate_report_notes) -- Versionierung statt
# Ueberschreiben. Jede Speicherung legt eine append-only Version in
# ``mandate_report_note_versions`` an (Freitexte versiegelt, ``content_hash``
# ueber die Umschlaege). Die Kopfzeile ``mandate_report_notes`` traegt nur
# noch Metadaten; die Historie vor L2c (``previous_versions_json``) liegt als
# ein versiegelter Umschlag in der Kopfzeile.
def _report_note_versions(db: Session, mandate_id: str, *, latest_only: bool = False) -> list[dict[str, Any]]:
    rows = db.execute(
        _sql_text(
            "SELECT * FROM mandate_report_note_versions WHERE mandate_id = :mid "
            "ORDER BY version DESC" + (" LIMIT 1" if latest_only else "")
        ),
        {"mid": str(mandate_id)},
    ).mappings().all()
    return [dict(row) for row in rows]


def _reveal_note_version(
    db: Session, row: dict[str, Any], client_id: str | None, reader: pii_vault.KeyReader | None = None,
) -> dict[str, Any]:
    plain, state = reveal_protocol_values(db, client_id, row, REPORT_NOTE_FIELDS, reader=reader)
    if report_note_version_hash(row) != row.get("content_hash") or str(row.get("client_id") or "") != str(client_id or ""):
        state = PROTOCOL_TEXT_TAMPERED
    if state == PROTOCOL_TEXT_TAMPERED:
        plain = {field: None for field in REPORT_NOTE_FIELDS}
    elif state == PROTOCOL_TEXT_ERASED:
        plain = {field: (ERASED_TEXT if row.get(field) and not field.endswith("_json") else None)
                 for field in REPORT_NOTE_FIELDS}
    return {**plain, "version": row.get("version"), "edited_by": row.get("edited_by"),
            "edited_at": row.get("edited_at"), "text_state": state, "id": row.get("id")}


def _legacy_history(db: Session, head: Any, client_id: str | None) -> tuple[list[dict], str]:
    raw = getattr(head, "previous_versions_json", None) if head is not None else None
    if not raw:
        return [], PROTOCOL_TEXT_OK
    plain, state = reveal_protocol_values(db, client_id, {"h": raw}, ("h",))
    if state != PROTOCOL_TEXT_OK or not plain.get("h"):
        return [], state
    try:
        parsed = json.loads(plain["h"])
    except (TypeError, ValueError):
        return [], PROTOCOL_TEXT_TAMPERED
    return (parsed if isinstance(parsed, list) else []), PROTOCOL_TEXT_OK


def report_notes_view(
    db: Session, mandate_id: str, *, client_id: str | None = None, with_history: bool = True,
):
    """Aktueller Stand der Berichtsnotizen (geoeffnet) oder None.

    Attribute wie die alte ORM-Zeile (``aa_anmerkungen`` …), dazu
    ``text_state`` (ok / geloescht_dsg / veraendert), ``current_version``,
    ``history`` (neueste zuerst: Aenderungen je Version, danach die
    Historie vor L2c) und die Metadaten der Kopfzeile. ``veraendert``
    liefert leere Felder (Report faellt auf Standardtexte zurueck) und
    sperrt die Kundenkanaele.

    N-938-02: Kundenkanaele lesen mit ``with_history=False`` nur die aktuelle,
    gepruefte Version. Die ganze Historie oeffnen und pruefen nur die
    Berater-Endpunkte (GET/PUT report-notes)."""
    head = db.query(MandateReportNotes).filter(MandateReportNotes.mandate_id == str(mandate_id)).first()
    if head is None:
        # Versionen gibt es nur mit Kopfzeile (PUT legt beide an, die
        # Migration versioniert nur bestehende Kopfzeilen).
        return None
    if client_id is None:
        client_id = mandate_client_id(db, mandate_id)
    reader = pii_vault.KeyReader(db)
    versions = _report_note_versions(db, mandate_id, latest_only=not with_history)
    revealed = [_reveal_note_version(db, row, client_id, reader) for row in versions]
    legacy, legacy_state = _legacy_history(db, head, client_id) if with_history else ([], PROTOCOL_TEXT_OK)
    if revealed:
        current = {field: revealed[0].get(field) for field in REPORT_NOTE_FIELDS}
        state = revealed[0]["text_state"]
    else:
        # Kopfzeile ohne Version: Altbestand vor der Migration (Klartext)
        # oder bereits versiegelte Kopffelder.
        current, state = reveal_protocol_values(
            db, client_id, {f: getattr(head, f, None) for f in REPORT_NOTE_FIELDS}, REPORT_NOTE_FIELDS,
        )
    if PROTOCOL_TEXT_TAMPERED in (legacy_state, *[r["text_state"] for r in revealed]):
        state = PROTOCOL_TEXT_TAMPERED
        current = {field: None for field in REPORT_NOTE_FIELDS}
    elif state == PROTOCOL_TEXT_OK and (
        legacy_state == PROTOCOL_TEXT_ERASED or any(r["text_state"] == PROTOCOL_TEXT_ERASED for r in revealed)
    ):
        state = PROTOCOL_TEXT_ERASED
    history: list[dict] = []
    for newer, older in zip(revealed if with_history else [], revealed[1:] + [None]):
        changes = {}
        for field in REPORT_NOTE_FIELDS:
            old_value = older.get(field) if older else None
            if (newer.get(field) or None) != (old_value or None):
                changes[field] = {"old": old_value, "new": newer.get(field)}
        if changes:
            history.append({"edited_at": newer.get("edited_at"), "edited_by": newer.get("edited_by"),
                            "version": newer.get("version"), "changes": changes})
    history.extend(legacy)
    return SimpleNamespace(
        id=getattr(head, "id", None), mandate_id=str(mandate_id), **current,
        last_edited_by=getattr(head, "last_edited_by", None) or (revealed[0]["edited_by"] if revealed else None),
        last_edited_at=getattr(head, "last_edited_at", None) or (revealed[0]["edited_at"] if revealed else None),
        created_at=getattr(head, "created_at", None), updated_at=getattr(head, "updated_at", None),
        text_state=state, current_version=(revealed[0]["version"] if revealed else 0),
        history=history,
    )


def append_report_note_version(
    db: Session, *, mandate_id: str, client_id: str | None, values: dict[str, Any],
    edited_by: str, edited_at: str,
) -> dict[str, Any] | None:
    """Neue append-only Version (Freitexte versiegelt). None, wenn sich nichts
    aendert. Fail-closed ``ProtocolTextSealError`` nach DSG-Loeschung; bei
    ``veraendert`` lehnt der Aufrufer vorher ab.

    N-938-03: Eine Kopfzeile mit Text, aber ohne Version (Altbestand) wird
    zuerst als Version 1 uebernommen (Urheber und Zeitpunkt der Kopfzeile) und
    zurueckgelesen -- auch bei einem PUT ohne Aenderung."""
    current = report_notes_view(db, mandate_id, client_id=client_id)
    merged = {field: (getattr(current, field, None) if current is not None else None) for field in REPORT_NOTE_FIELDS}
    changed = False
    for field, value in values.items():
        if field in merged and (merged[field] or None) != (value or None):
            merged[field] = value or None
            changed = True
    version = int(getattr(current, "current_version", 0) or 0)
    legacy = {field: (getattr(current, field, None) or None) for field in REPORT_NOTE_FIELDS}
    adopted = None
    if version == 0 and current is not None and current.text_state == PROTOCOL_TEXT_OK and any(legacy.values()):
        version = 1
        adopted = _insert_report_note_version(
            db, mandate_id=mandate_id, client_id=client_id, version=1, values=legacy,
            edited_by=current.last_edited_by or edited_by, edited_at=current.last_edited_at or edited_at,
        )
        stored = report_notes_view(db, mandate_id, client_id=client_id, with_history=False)
        if stored.text_state != PROTOCOL_TEXT_OK or any(
            (getattr(stored, field) or None) != legacy[field] for field in REPORT_NOTE_FIELDS
        ):
            raise ProtocolTextSealError("Bestehende Berichtsnotizen konnten nicht als Version gesichert werden.")
    if not changed:
        return adopted
    return _insert_report_note_version(
        db, mandate_id=mandate_id, client_id=client_id, version=version + 1, values=merged,
        edited_by=edited_by, edited_at=edited_at,
    )


def _insert_report_note_version(
    db: Session, *, mandate_id: str, client_id: str | None, version: int, values: dict[str, Any],
    edited_by: str, edited_at: str,
) -> dict[str, Any]:
    row = {
        "id": new_uuid(), "mandate_id": str(mandate_id), "client_id": client_id, "version": version,
        **{field: seal_protocol_value(db, client_id, values[field]) for field in REPORT_NOTE_FIELDS},
        "edited_by": edited_by, "edited_at": edited_at,
    }
    row["content_hash"] = report_note_version_hash(row)
    row["tenant_id"] = db.execute(
        _sql_text("SELECT tenant_id FROM mandates WHERE id = :id"), {"id": str(mandate_id)},
    ).scalar()
    columns = ", ".join(row)
    db.execute(
        _sql_text(f"INSERT INTO mandate_report_note_versions ({columns}) VALUES ({', '.join(':' + k for k in row)})"),
        row,
    )
    return row


def build_hash_payload(entry: AdvisoryLog) -> dict:
    """Snapshot der hash-relevanten Felder für `compute_integrity_hash`."""
    return {
        "mandate_id": entry.mandate_id,
        "advisor_id": entry.advisor_id,
        "entry_type": entry.entry_type,
        "entry_datetime": entry.entry_datetime,
        "duration_minutes": entry.duration_minutes,
        "communication_channel": entry.communication_channel,
        "language": entry.language,
        "location": entry.location,
        "title": entry.title,
        "description": entry.description,
        "decision": entry.decision,
        "status": entry.status,
        "participants_json": entry.participants_json,
        "topics_json": entry.topics_json,
        "risk_warnings_given_json": entry.risk_warnings_given_json,
        "cost_disclosure_given": entry.cost_disclosure_given,
        "cost_disclosure_snapshot_json": entry.cost_disclosure_snapshot_json,
        "conflict_disclosure_ids_json": entry.conflict_disclosure_ids_json,
        "suitability_check_id": entry.suitability_check_id,
        "recommendation_run_id": entry.recommendation_run_id,
        "client_signed": entry.client_signed,
        "client_signed_at": entry.client_signed_at,
        "version": entry.version,
    }


ADVISORY_LOG_COST_SNAPSHOT_SCHEMA_VERSION = 2


class AdvisoryLogCostEvidenceError(ValueError):
    """COST-SNAPSHOT-BINDING-001: `cost_disclosure_given=True`, aber der
    Kostennachweis des genannten (bzw. aktuellen) Laufs ist vorhanden und
    ungueltig. Der Router mappt das auf 409 -- ein Protokoll darf weder einen
    ungueltigen Nachweis noch heute live gerechnete Ersatzzahlen als
    "gezeigte Kosten" festhalten."""

    def __init__(self, reason: str, run_id: str | None) -> None:
        self.reason = reason
        self.run_id = run_id
        super().__init__(
            "Der eingefrorene Kostennachweis des Empfehlungslaufs "
            f"{run_id or '(aktuell)'} ist ungueltig ({reason}). Eine "
            "Kostenoffenlegung kann damit nicht belegt werden -- Strategie "
            "neu berechnen und finalisieren."
        )


def _build_cost_disclosure_snapshot(
    db: Session, mandate, *, recommendation_run_id: str | None = None,
) -> str | None:
    """Wie `_resolve_cost_disclosure_snapshot`, aber nur der JSON-String.

    Bei ungueltigem Nachweis `None` -- nie ein Live-Ersatz
    (COST-SNAPSHOT-BINDING-001).
    """
    snapshot_json, _block_reason = _resolve_cost_disclosure_snapshot(
        db, mandate, recommendation_run_id=recommendation_run_id,
    )
    return snapshot_json


def _resolve_cost_disclosure_snapshot(
    db: Session, mandate, *, recommendation_run_id: str | None = None,
) -> tuple[str | None, str | None]:
    """Nachweis der Kostenzahlen, die in dieser Beratung gezeigt wurden.

    Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): `cost_disclosure_given` war ein
    reines Selbst-Attest-Flag ohne Nachweis, WELCHE Zahlen gezeigt wurden.

    COST-EVIDENCE-001 (CERT-COST-CONFLICT-001, 2026-10-13): die erste
    Fassung dieses Nachweises war zu duenn und an den falschen Lauf
    gebunden. Zwei Maengel, beide behoben:

    1. Sie rief `build_cost_disclosure(db, mandate)` -- den MANDATSWEITEN
       Bauer -- und ignorierte die `recommendation_run_id` des
       Protokolleintrags. Der Eintrag dokumentiert aber ein Gespraech ueber
       EINEN bestimmten Lauf; der Nachweis muss an denselben haengen. Vorher
       konnte das Protokoll die Zahlen eines anderen Laufs festhalten als
       den, auf den es sich beruft.
    2. Sie speicherte sechs reduzierte Summenfelder. Ohne Posten,
       Warnungen und Hash ist das kein nachrechenbarer Nachweis: man sieht
       eine Zahl, aber nicht, woraus sie entstand.

    Jetzt: der vollstaendige Payload, gebunden an die Lauf-ID und ihren
    Status, mit Inhalts-Hash. Liegt der bei der Finalisierung eingefrorene
    Nachweis des Laufs vor (COST-CONTEXT-001b), ist ER die Quelle -- also
    genau die Zahlen, die der Kunde erhalten hat, und nicht eine
    Neuberechnung von heute.

    Fail-soft bleibt: schlaegt die Berechnung fehl (keine Empfehlung,
    kaputtes Gebuehrenmodell), wird kein Snapshot gespeichert und das Flag
    bleibt gueltig -- der Berater hat das Gespraech dokumentiert, auch wenn
    die Engine gerade keine Zahlen liefern konnte. Den Protokolleintrag
    daran scheitern zu lassen waere eine Blockade, die dieser Befund nicht
    verlangt.
    """
    if mandate is None:
        return None, None
    try:
        from services.cost_disclosure import (
            build_cost_disclosure,
            build_cost_disclosure_for_run,
            cost_disclosure_content_hash,
            load_frozen_cost_disclosure,
        )

        run = None
        if recommendation_run_id:
            from models.review import RecommendationRun
            run = (
                db.query(RecommendationRun)
                .filter(
                    RecommendationRun.id == recommendation_run_id,
                    # An das Mandat gebunden: ein Lauf eines ANDEREN Mandats
                    # darf nicht zum Nachweis dieses Protokolls werden
                    # (gleiche Haertung wie COST-BASIS-001).
                    RecommendationRun.mandate_id == getattr(mandate, "id", None),
                )
                .first()
            )

        if run is not None:
            frozen, reason = load_frozen_cost_disclosure(run)
            if reason is not None:
                # COST-SNAPSHOT-BINDING-001 (Codex-Befund 3): vorher wurde
                # `reason` ignoriert und ein korrupter Final-Nachweis still
                # durch heute live gerechnete Zahlen ersetzt -- mit eigenem,
                # gueltigem Hash. Jetzt: kein Snapshot, ausgewiesener Grund.
                return None, reason
            payload = frozen if frozen is not None else build_cost_disclosure_for_run(
                db, mandate, run,
            )
            bound_run_id = str(getattr(run, "id", "") or "")
            bound_status = str(getattr(run, "result_status", "") or "")
        else:
            # Kein (oder kein zugehoeriger) Lauf genannt: wie bisher der
            # mandatsweite Bauer. Die Bindung bleibt dann ausdruecklich
            # leer, statt einen Lauf zu behaupten.
            payload = build_cost_disclosure(db, mandate)
            if payload.get("evidence_status") == "blocked":
                return None, str(payload.get("evidence_error") or "snapshot_invalid")
            bound_run_id = str(payload.get("source_run_id") or "") or None
            bound_status = str(payload.get("source_run_status") or "") or None
    except Exception:  # noqa: BLE001 -- siehe Docstring: fail-soft
        return None, None

    totals = payload.get("totals") or {}
    snapshot = {
        "schema_version": ADVISORY_LOG_COST_SNAPSHOT_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "recommendation_run_id": bound_run_id,
        "status": bound_status,
        "currency": payload.get("currency"),
        "advisory_wealth_rappen": payload.get("advisory_wealth_rappen"),
        "invested_amount_rappen": payload.get("invested_amount_rappen"),
        "one_time_rappen": totals.get("one_time_rappen"),
        "annual_rappen": totals.get("annual_rappen"),
        "first_year_rappen": totals.get("first_year_rappen"),
        "totals": totals,
        "cost_items": payload.get("cost_items") or [],
        "warnings": payload.get("warnings") or [],
        "is_complete": payload.get("is_complete"),
        "data_pending": payload.get("data_pending"),
        # Ob der Nachweis aus dem eingefrorenen Snapshot des Laufs stammt --
        # ohne das Feld waere "die Zahlen des Kunden" von "heute neu
        # gerechnet" nicht zu unterscheiden.
        "evidence_frozen": bool(payload.get("evidence_frozen")),
        "source_content_hash": payload.get("content_hash"),
    }
    # Hash ueber den Nachweis selbst, nach demselben Verfahren wie im
    # Kostenausweis. `generated_at` ist Teil des Inhalts: zwei Protokolle
    # ueber dieselben Zahlen sind zwei verschiedene Nachweise.
    snapshot["content_hash"] = cost_disclosure_content_hash(snapshot)
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True), None


def apply_mandate_end_retention(db: Session, mandate) -> int:
    """H7 C-6: ``retain_until`` aller Protokolleintraege eines Mandats an das
    Mandatsende anpassen (Aufruf bei Aenderung von ``closed_at``).

    Nie verkuerzend: beendet -> Maximum aus bisheriger Frist, Eintrag + 10 J.
    und Mandatsende + 10 J.; wieder geoeffnet -> bisherige Frist bleibt als
    Mindestfrist stehen (N-884-06).
    ``retain_until`` ist nicht Teil des Integritaets-Hashes. Rueckgabe: Zahl
    der geaenderten Zeilen.
    """
    closed_at = getattr(mandate, "closed_at", None)
    changed = 0
    for row in db.query(AdvisoryLog).filter(AdvisoryLog.mandate_id == mandate.id).all():
        new_value = extended_retain_until(row.retain_until, row.entry_datetime, closed_at)
        if new_value != row.retain_until:
            row.retain_until = new_value
            changed += 1
    return changed


def create_advisory_log(
    db: Session,
    *,
    mandate_id: str,
    advisor: User,
    payload,
    mandate=None,
) -> AdvisoryLog:
    """Persist einen neuen AdvisoryLog-Eintrag mit Hash + retain_until.

    `payload` ist eine `AdvisoryLogCreate`-Instanz. `mandate` (optional) wird
    fuer den Kosten-Offenlegungs-Snapshot benoetigt, wenn
    payload.cost_disclosure_given=True -- ohne Mandate-Objekt wird das Flag
    weiterhin gespeichert, aber ohne Zahlen-Snapshot.
    """
    now = _now_iso()
    entry_datetime = payload.entry_datetime
    entry_date = payload.entry_date or entry_datetime[:10]
    cost_disclosure_snapshot_json = None
    if payload.cost_disclosure_given:
        named_run_id = getattr(payload, "recommendation_run_id", None)
        cost_disclosure_snapshot_json, block_reason = _resolve_cost_disclosure_snapshot(
            db, mandate,
            # COST-EVIDENCE-001: an den Lauf binden, auf den sich DIESER
            # Eintrag beruft -- nicht an den, den der mandatsweite Bauer
            # gerade waehlen wuerde.
            recommendation_run_id=named_run_id,
        )
        if block_reason is not None:
            # COST-SNAPSHOT-BINDING-001: fail-closed. Ein ungueltiger
            # Nachweis darf weder still durch Live-Zahlen ersetzt noch als
            # nachweisloses `cost_disclosure_given=True` gespeichert werden.
            raise AdvisoryLogCostEvidenceError(block_reason, named_run_id)

    # H7 C-6: Frist ab Mandatsende statt ab Eintrag (validiert entry_datetime
    # weiterhin fail-closed). Ohne uebergebenes Mandat wird es nachgelesen.
    if mandate is not None:
        closed_at = getattr(mandate, "closed_at", None)
    else:
        closed_at = db.execute(
            _sql_text("SELECT closed_at FROM mandates WHERE id = :id"), {"id": mandate_id},
        ).scalar()
    retain_until = compute_relationship_retain_until(entry_datetime, closed_at)

    entry = AdvisoryLog(
        id=new_uuid(),
        mandate_id=mandate_id,
        advisor_id=advisor.id,
        entry_type=payload.entry_type,
        title=payload.title,
        description=payload.description,
        decision=payload.decision,
        trigger_id=payload.trigger_id,
        recommendation_run_id=payload.recommendation_run_id,
        status=payload.status or "Empfohlen",
        client_signed=1 if payload.client_signed else 0,
        client_signed_at=payload.client_signed_at,
        document_id=payload.document_id,
        entry_date=entry_date,
        # FINMA-Erweiterung
        entry_datetime=entry_datetime,
        duration_minutes=payload.duration_minutes,
        communication_channel=payload.communication_channel,
        language=payload.language,
        location=payload.location,
        participants_json=_dump_json(payload.participants),
        topics_json=_dump_json(payload.topics),
        risk_warnings_given_json=_dump_json(payload.risk_warnings_given),
        cost_disclosure_given=1 if payload.cost_disclosure_given else 0,
        cost_disclosure_snapshot_json=cost_disclosure_snapshot_json,
        conflict_disclosure_ids_json=_dump_json(payload.conflict_disclosure_ids),
        suitability_check_id=payload.suitability_check_id,
        retain_until=retain_until,
        version=1,
        created_at=now,
        updated_at=now,
    )
    # L2c: Freitexte VOR dem Siegeln versiegeln (Siegel ueber den Umschlag).
    client_id = str(getattr(mandate, "client_id", "") or "") or mandate_client_id(db, mandate_id)
    seal_advisory_entry_texts(db, entry, client_id)
    entry.integrity_hash = compute_integrity_hash(payload=build_hash_payload(entry))
    db.add(entry)
    return entry


def supersede_advisory_log(
    db: Session,
    *,
    previous: AdvisoryLog,
    advisor: User,
    update,
) -> AdvisoryLog:
    """Erzeugt eine neue Version mit den geänderten Feldern; markiert den
    Vorgänger als superseded. FINMA-Pflicht: keine destructive Updates.

    `update` ist eine `AdvisoryLogUpdate`-Instanz.
    """
    now = _now_iso()

    new = AdvisoryLog(
        id=new_uuid(),
        mandate_id=previous.mandate_id,
        advisor_id=advisor.id,
        entry_type=previous.entry_type,
        title=previous.title,
        description=update.description if update.description is not None else previous.description,
        decision=update.decision if update.decision is not None else previous.decision,
        trigger_id=previous.trigger_id,
        recommendation_run_id=(
            update.recommendation_run_id
            if update.recommendation_run_id is not None
            else previous.recommendation_run_id
        ),
        status=update.status or previous.status,
        client_signed=(
            (1 if update.client_signed else 0)
            if update.client_signed is not None
            else previous.client_signed
        ),
        client_signed_at=(
            update.client_signed_at
            if update.client_signed_at is not None
            else previous.client_signed_at
        ),
        document_id=previous.document_id,
        entry_date=previous.entry_date,
        # FINMA-Felder bleiben weitestgehend aus previous (außer revisierte)
        entry_datetime=previous.entry_datetime,
        duration_minutes=previous.duration_minutes,
        communication_channel=previous.communication_channel,
        language=previous.language,
        location=previous.location,
        participants_json=previous.participants_json,
        topics_json=(
            _dump_json(update.topics) if update.topics is not None else previous.topics_json
        ),
        risk_warnings_given_json=(
            _dump_json(update.risk_warnings_given)
            if update.risk_warnings_given is not None
            else previous.risk_warnings_given_json
        ),
        cost_disclosure_given=previous.cost_disclosure_given,
        cost_disclosure_snapshot_json=previous.cost_disclosure_snapshot_json,
        conflict_disclosure_ids_json=previous.conflict_disclosure_ids_json,
        suitability_check_id=previous.suitability_check_id,
        retain_until=previous.retain_until,
        version=previous.version + 1,
        supersedes_id=previous.id,
        created_at=now,
        updated_at=now,
    )
    # L2c: neue/uebernommene Freitexte versiegeln (bereits versiegelte
    # Umschlaege bleiben unveraendert), dann siegeln.
    seal_advisory_entry_texts(db, new, mandate_client_id(db, previous.mandate_id))
    new.integrity_hash = compute_integrity_hash(payload=build_hash_payload(new))
    db.add(new)
    db.flush()

    # Vorgänger als superseded markieren
    previous.superseded_by_id = new.id
    previous.updated_at = now

    return new


def mark_read(db: Session, *, entry: AdvisoryLog, reader: User) -> None:
    """FINMA-Pflicht: Access-Tracking bei sensiblen Daten."""
    entry.last_read_at = _now_iso()
    entry.last_read_by = reader.id


# ---------------------------------------------------------------------------
# Sprint U-FINMA-2.2 — Detection + Aggregator-Helpers
# ---------------------------------------------------------------------------

def get_latest_active_entry(
    db: Session, *, mandate_id: str
) -> AdvisoryLog | None:
    """Letzter aktiver (non-superseded) Eintrag eines Mandats nach entry_date.

    Wird vom Aggregator konsumiert um „letzter Termin" anzuzeigen.
    """
    return (
        db.query(AdvisoryLog)
        .filter(
            AdvisoryLog.mandate_id == mandate_id,
            AdvisoryLog.superseded_by_id.is_(None),
            # RISK-PROFILE-SIGNOFF-001: System-Ereignisse (z.B. Portal-
            # Signoff des Risikoprofils) sind kein Beratungstermin.
            AdvisoryLog.system_event.is_(None),
        )
        .order_by(
            AdvisoryLog.entry_datetime.desc().nullslast(),
            AdvisoryLog.entry_date.desc(),
            AdvisoryLog.created_at.desc(),
        )
        .first()
    )


def count_active_entries(db: Session, *, mandate_id: str) -> int:
    """Anzahl aktiver (non-superseded) AdvisoryLog-Köpfe."""
    return (
        db.query(AdvisoryLog)
        .filter(
            AdvisoryLog.mandate_id == mandate_id,
            AdvisoryLog.superseded_by_id.is_(None),
        )
        .count()
    )


def detect_suitability_mismatches(db: Session, mandate) -> list[str]:
    """Liefert eine Liste menschenlesbarer Warnings, wenn die aktuelle
    Empfehlung das Risikoprofil-Budget oder die Toleranzbänder verlässt --
    oder wenn die HouseMatrix-Cap-Pruefung nicht moeglich ist.

    FINMA-relevant: jeder Mismatch sollte im nächsten Beratungsprotokoll
    als gegebener Risikohinweis dokumentiert werden.

    Beispiele:
    - „Risky-Fraction 47 % überschreitet HouseMatrix-Cap 45 % (Defensiv)"
    - „Aktien-Anteil 28 % verlässt Toleranzband 15-25 %"
    - „HouseMatrix-Cap nicht pruefbar (SCORE_BUCKET_MISSING): ..."
    """
    return evaluate_suitability_mismatches(db, mandate)["warnings"]


def evaluate_suitability_mismatches(db: Session, mandate) -> dict:
    """Wie ``detect_suitability_mismatches``, plus strukturierter Status der
    HouseMatrix-Cap-Pruefung (``services.suitability_cap_check``).

    Rueckgabe: ``{"warnings": list[str], "cap_check": SuitabilityCapCheck}``.
    """
    from models.allocation import TargetAllocation
    from models.profiling import RiskAssessment
    from services.suitability_cap_check import (
        evaluate_house_matrix_cap,
        not_applicable,
    )

    warnings: list[str] = []

    ta = (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        )
        .first()
    )
    if ta is None:
        # kein aktiver Allokations-Stand → kein Mismatch erfassbar
        return {"warnings": warnings, "cap_check": not_applicable()}

    ra = (
        db.query(RiskAssessment)
        .filter(
            RiskAssessment.mandate_id == mandate.id,
            RiskAssessment.is_current == 1,
            RiskAssessment.deleted_at.is_(None),
        )
        .first()
    )

    raw_risky_fraction = getattr(ta, "risky_fraction_bps", None)
    risky_fraction = _safe_int(raw_risky_fraction)
    risk_budget = _safe_int(getattr(ta, "risk_budget_bps_at_generation", 0))
    # Wenn risk_budget verfuegbar → direkter Check (war zum Generate-Zeitpunkt aktiv)
    if risky_fraction and risk_budget and risky_fraction > risk_budget:
        warnings.append(
            f"Risiko-Anteil {risky_fraction / 100:.1f} % überschreitet "
            f"Risikobudget {risk_budget / 100:.1f} % zum Zeitpunkt der "
            "Empfehlungs-Generierung."
        )

    # Plus: vergleich mit aktueller HouseMatrix (kann sich nach Generate geaendert haben)
    # Kontrollrunde 2026-09-20: override-bewusst (score_bucket_from_assessment
    # nutzt bei aktivem Override override_score_x10).
    # SUITABILITY-DETECTOR-SCALE-001 (2026-10-14): 0..100 -> 1..10-Bucket.
    # SUITABILITY-DETECTOR-AVAILABILITY-001 (2026-10-21): fehlende Policy,
    # fehlender/mehrdeutiger Score-Bucket, fehlendes Risikoprofil oder
    # fehlender Risiko-Anteil wurden vorher still uebersprungen (leere Liste
    # = "geeignet", fail-open). Jetzt expliziter Status ``unavailable`` mit
    # Reason-Code und Berater-Hinweis (fail-closed).
    cap_check = evaluate_house_matrix_cap(
        db,
        assessment=ra,
        risky_fraction_bps=(
            None if raw_risky_fraction is None else risky_fraction
        ),
    )
    if cap_check.requires_advisor_attention and cap_check.message:
        warnings.append(cap_check.message)

    # Buckets gegen Bänder pruefen
    for bucket_key in ("equities", "bonds", "real_estate", "alternatives", "liquidity"):
        target = _safe_int(getattr(ta, f"target_{bucket_key}_bps", 0))
        band_min = _safe_int(getattr(ta, f"band_{bucket_key}_min_bps", 0))
        band_max = _safe_int(getattr(ta, f"band_{bucket_key}_max_bps", 0))
        if target and band_max and band_max > 0:
            if target < band_min or target > band_max:
                bucket_label = bucket_key.replace("_", " ").title()
                warnings.append(
                    f"{bucket_label}-Anteil {target / 100:.1f} % verlässt "
                    f"Toleranzband {band_min / 100:.1f}-{band_max / 100:.1f} %."
                )

    return {"warnings": warnings, "cap_check": cap_check}


def build_auto_log_payload(
    db: Session,
    *,
    mandate,
    advisor: User,
    entry_datetime: str,
    duration_minutes: int = 60,
    communication_channel: str = "schriftlich",
    extra_topics: list[str] | None = None,
    extra_warnings: list[str] | None = None,
) -> dict:
    """Pre-filled AdvisoryLogCreate-Payload als dict.

    Berater nutzt das als Vorlage und ergaenzt nur description / Status /
    decision. Hash + retain_until werden vom create_advisory_log berechnet.

    - Topics: aus existierenden AdvisoryLog-Themen + extra_topics
    - Risk-Warnings: aus detect_suitability_mismatches + extra_warnings
    """
    topics_set = set(extra_topics or [])
    topics_set.update([
        "Strategieueberblick", "Risikoprofil", "Asset Allocation",
    ])
    mismatches = detect_suitability_mismatches(db, mandate)
    risk_warnings = list(mismatches)
    if extra_warnings:
        risk_warnings.extend(extra_warnings)
    if not risk_warnings:
        # Mindestens ein generischer Hinweis fuer FIDLEG-Compliance
        risk_warnings = [
            "Allgemeines Marktrisiko: Wertpapiere koennen an Wert verlieren.",
        ]

    return {
        "entry_type": "Jahresreview",
        "title": f"Beratungsprotokoll {entry_datetime[:10]}",
        "description": (
            f"Auto-generiertes Beratungsprotokoll auf Basis des Advisory-"
            f"Reports vom {entry_datetime[:10]}. Bitte vom Berater "
            "individuell ergaenzen / korrigieren (Mindestlaenge 30 Zeichen)."
        ),
        "decision": None,
        "entry_datetime": entry_datetime,
        "duration_minutes": duration_minutes,
        "communication_channel": communication_channel,
        "language": "de",
        "location": None,
        "participants": [],
        "topics": sorted(topics_set),
        "risk_warnings_given": risk_warnings,
        "cost_disclosure_given": False,
        "status": "Empfohlen",
    }


def _safe_int(value, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def verify_entry_integrity(entry: AdvisoryLog) -> bool | None:
    """Prueft den gespeicherten integrity_hash gegen die aktuellen Feldwerte.

    Mega-Audit (2026-08-04): `verify_integrity_hash()` wurde seit U-FINMA-2.1
    berechnet und persistiert, aber NIRGENDS beim Lesen tatsaechlich
    aufgerufen (nur in Tests) -- der Manipulationsschutz existierte nur auf
    dem Papier. Wird jetzt bei jeder Serialisierung mitgeliefert.

    Returns
    -------
    None
        Kein Hash vorhanden (Legacy-Eintrag vor U-FINMA-2.1) -- nichts zu
        verifizieren, KEIN Manipulationsverdacht.
    True/False
        Hash vorhanden und stimmt/stimmt nicht mit dem aktuellen Inhalt
        ueberein.
    """
    if not entry.integrity_hash:
        return None
    return verify_integrity_hash(
        payload=build_hash_payload(entry), expected_hash=entry.integrity_hash,
    )


# KN9 / N-931-01 + KN9a / N-934-01..02 (CTO-Entscheid): EINE Regel fuer alle
# Kundenkanaele (Advisory-Report-PDF, Beratungsprotokoll-PDF, Beratungsentscheid,
# Kundenportal). Jeder Eintrag, den der Kunde sieht, wird geprueft. Nur
# ``False`` (Pruefsumme passt nicht zum Inhalt) sperrt; True und None
# (Alteintrag ohne Pruefsumme) bleiben erlaubt. Gesperrt wird vor jeder
# Archivierung; der Router antwortet 409 ``ADVISORY_LOG_INTEGRITY_FAILED``,
# das Kundenportal neutral (Code nur in Log/Audit).
LATEST_ENTRY_LABEL = "des letzten Beratungsprotokoll-Eintrags"


def advisory_log_integrity_message(
    document: str = "Advisory-Report", entry_label: str = LATEST_ENTRY_LABEL,
) -> str:
    """Deutsche Ursache fuer die Berater-Antwort (nie fuer den Kunden)."""
    return (
        f"{document} kann nicht als Kunden-PDF erzeugt werden: Die Prüfsumme "
        f"{entry_label} passt nicht zu seinem Inhalt. Der Eintrag wurde nach dem "
        "Speichern verändert oder ist beschädigt. Bitte den Eintrag in der "
        "Beratungsprotokoll-Liste prüfen und neu erfassen."
    )


class AdvisoryLogIntegrityFailed(Exception):
    """Ein gezeigter Protokolleintrag hat eine nicht passende Pruefsumme."""

    def __init__(
        self, entry_id: str | None = None, *, document: str = "Advisory-Report",
        entry_label: str = LATEST_ENTRY_LABEL, entry_kind: str = "advisory_log",
        message: str | None = None,
    ) -> None:
        super().__init__(message or advisory_log_integrity_message(document, entry_label))
        self.entry_id = entry_id
        # N-936-06: Art des gesperrten Eintrags (advisory_log,
        # advice_rationale, report_notes, conflict_disclosure); die 409 nennt
        # die ID neutral als ``entry_id``.
        self.entry_kind = entry_kind


def entry_integrity_failed(entry: Any, reader: pii_vault.KeyReader | None = None) -> bool:
    """True nur, wenn die Pruefsumme nicht zum Inhalt passt. Nimmt eine
    DB-Zeile (wird jetzt geprueft) oder ein serialisiertes Dict
    (``integrity_verified`` aus ``serialize_response``)."""
    if entry is None:
        return False
    if isinstance(entry, dict):
        return entry.get("integrity_verified") is False
    if verify_entry_integrity(entry) is False:
        return True
    # L2c: Siegel passt, aber Umschlag veraendert (fremder Schluessel,
    # unlesbar, Tombstone ohne belegte Loeschung).
    return advisory_entry_text_state(None, entry, reader=reader)[1] == PROTOCOL_TEXT_TAMPERED


def _entry_label(entry: Any) -> str:
    get = entry.get if isinstance(entry, dict) else (lambda key: getattr(entry, key, None))
    raw_date = str(get("entry_datetime") or get("entry_date") or "")[:10]
    try:
        shown = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        shown = ""
    title = get("title")
    if not isinstance(entry, dict):
        plain, state = advisory_entry_text_state(None, entry)
        title = plain.get("title") if state == PROTOCOL_TEXT_OK else None
    title = "" if pii_vault.is_sealed(title) else str(title or "").strip()
    label = "des Beratungsprotokoll-Eintrags"
    if shown:
        label += f" vom {shown}"
    if title:
        label += f" («{title[:60]}»)"
    return label


def assert_shown_entries_intact(
    entries, *, document: str, latest_only: bool = False,
) -> None:
    """Fail-closed: wirft ``AdvisoryLogIntegrityFailed`` beim ersten gezeigten
    Eintrag mit nicht passender Pruefsumme. ``latest_only`` nennt ihn in der
    Ursache «letzter Eintrag» (Advisory-Report zeigt nur diesen)."""
    reader = None
    for entry in entries or ():
        if reader is None and isinstance(entry, AdvisoryLog) and (session := object_session(entry)) is not None:
            reader = pii_vault.KeyReader(session)
        if entry_integrity_failed(entry, reader):
            entry_id = entry.get("id") if isinstance(entry, dict) else getattr(entry, "id", None)
            raise AdvisoryLogIntegrityFailed(
                str(entry_id or "") or None, document=document,
                entry_label=LATEST_ENTRY_LABEL if latest_only else _entry_label(entry),
            )


# KN9a / N-934-05 (Folgefund): der Systemeintrag zur Portal-Signatur des
# Risikoprofils (services.risk_profile_signoff.ADVISORY_SYSTEM_EVENT) traegt
# Audit-Text («Systemeintrag RiskProfileSignoffV1 … SHA-256 …»). In Kunden-PDFs
# (Beratungsprotokoll, Beratungsentscheid) steht dafuer Kundensprache; der
# Nachweis selbst steht im Abschnitt «Signatur des Risikoprofils». DB, Hash und
# Audit bleiben unveraendert.
RISK_PROFILE_SIGNOFF_SYSTEM_EVENT = "risk_profile_signoff"
CUSTOMER_SIGNOFF_ENTRY_TITLE = "Signatur des Risikoprofils"
CUSTOMER_SIGNOFF_ENTRY_TEXT = (
    "Signatur des Risikoprofils erfasst. Den Nachweis zeigt der Abschnitt "
    "«Signatur des Risikoprofils»."
)


def customer_protocol_entry(entry: Any, reader: pii_vault.KeyReader | None = None) -> dict:
    """Ein Protokolleintrag in der Form der Kunden-PDFs (Beratungsprotokoll,
    Beratungsentscheid)."""
    get = entry.get if isinstance(entry, dict) else (lambda key: getattr(entry, key, None))
    if isinstance(entry, dict):
        # Bereits ueber serialize_response geoeffnet.
        texts = {field: entry.get(field) for field in ADVISORY_LOG_SEALED_FIELDS}
        state = PROTOCOL_TEXT_OK
    else:
        texts, state = advisory_entry_text_state(None, entry, reader=reader)
    if state == PROTOCOL_TEXT_ERASED:
        texts = {field: (ERASED_TEXT if field in ("title", "description") else "") for field in texts}
    for field, value in texts.items():
        # Nie einen Umschlag ins Kunden-PDF (veraendert sperrt vorher).
        if pii_vault.is_sealed(value):
            texts[field] = ""
    view = {
        "entry_date": str(get("entry_date") or ""),
        "entry_type": str(get("entry_type") or ""),
        "title": str(texts.get("title") or ""),
        "description": str(texts.get("description") or ""),
        "decision": str(get("decision") or ""),
        "status": str(get("status") or ""),
    }
    if get("system_event") == RISK_PROFILE_SIGNOFF_SYSTEM_EVENT:
        view.update(title=CUSTOMER_SIGNOFF_ENTRY_TITLE, description=CUSTOMER_SIGNOFF_ENTRY_TEXT,
                    decision="")
    return view


def serialize_entries(entries, db: Session) -> list[dict]:
    """Liste mit EINEM Schluessel-/Mandatskontext (N-938-02)."""
    reader = pii_vault.KeyReader(db)
    return [serialize_response(entry, db, reader=reader) for entry in entries]


def serialize_response(
    entry: AdvisoryLog, db: Session | None = None, *, reader: pii_vault.KeyReader | None = None,
) -> dict:
    """Wandelt AdvisoryLog-Row in API-Response-Dict (JSON-Felder → Listen).

    L2c: die versiegelten Freitexte werden ueber ``advisory_entry_text_state``
    geoeffnet (Session: ``db`` oder die der Zeile). ``text_state`` sagt
    ``ok`` / ``geloescht_dsg`` / ``veraendert``; ``veraendert`` setzt
    ``integrity_verified`` auf False (sperrt die Kundenkanaele, KN9a)."""
    texts, text_state = advisory_entry_text_state(db, entry, reader=reader)
    if text_state == PROTOCOL_TEXT_ERASED:
        texts = {"title": ERASED_TEXT, "description": ERASED_TEXT, "location": None, "participants_json": None}
    elif text_state == PROTOCOL_TEXT_TAMPERED:
        texts = {field: None for field in ADVISORY_LOG_SEALED_FIELDS}
    verified = verify_entry_integrity(entry)
    if text_state == PROTOCOL_TEXT_TAMPERED:
        verified = False
    return {
        "id": entry.id,
        "mandate_id": entry.mandate_id,
        "entry_type": entry.entry_type,
        "title": texts.get("title") or "",
        "description": texts.get("description"),
        # decision ist eine Kategorie (CHECK-Liste), nicht versiegelt.
        "decision": entry.decision,
        "trigger_id": entry.trigger_id,
        "recommendation_run_id": entry.recommendation_run_id,
        "status": entry.status,
        "advisor_id": entry.advisor_id,
        "client_signed": entry.client_signed,
        "client_signed_at": entry.client_signed_at,
        "document_id": entry.document_id,
        "entry_date": entry.entry_date,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        # FINMA-Erweiterung
        "entry_datetime": entry.entry_datetime,
        "duration_minutes": entry.duration_minutes,
        "communication_channel": entry.communication_channel,
        "language": entry.language,
        "location": texts.get("location"),
        "participants": _load_json(texts.get("participants_json")),
        "topics": _load_json(entry.topics_json),
        "risk_warnings_given": _load_json(entry.risk_warnings_given_json),
        "cost_disclosure_given": entry.cost_disclosure_given,
        "cost_disclosure_snapshot": _load_json_object(entry.cost_disclosure_snapshot_json),
        "conflict_disclosure_ids": _load_json(entry.conflict_disclosure_ids_json),
        "suitability_check_id": entry.suitability_check_id,
        "integrity_hash": entry.integrity_hash,
        "integrity_verified": verified,
        "retain_until": entry.retain_until,
        "version": entry.version,
        "supersedes_id": entry.supersedes_id,
        "superseded_by_id": entry.superseded_by_id,
        "last_read_at": entry.last_read_at,
        "last_read_by": entry.last_read_by,
    }
