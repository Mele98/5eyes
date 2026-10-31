"""FinancialCoverageAttestationV1 -- Vollstaendigkeits-Bestaetigung der
erfassten Finanzdaten eines Haushalts.

RISK-CAPACITY-PLAUSIBILITY-001 Restbefund A (Codex-Closure-Review PR #653,
2026-10-20): ``expense_cashflow_count > 0`` machte die Ausgaben-Coverage zu
``recorded`` -- eine einzige CHF-1-Zeile genuegte, damit eine hohe deklarierte
Sparquote und niedrige Verpflichtungen als "konsistent" galten. Zeilen-
praesenz ist aber keine Vollstaendigkeit.

Jetzt gilt: niedrige erfasste Ausgaben belegen Konsistenz nur mit einer
GUELTIGEN Bestaetigung (``resolve_attestation(...)["status"] == "valid"``):

* neueste Zeile des Mandats (Korrektur = neue Zeile, append-only);
* Hash verifiziert (SHA-256 ueber den kanonischen Snapshot);
* gleicher Haushalt (client_id des Mandats) und mindestens eine Person;
* alle Kategorien bestaetigt: Einnahmen, Ausgaben, Verpflichtungen,
  unregelmaessige Ausgaben geprueft;
* aktuelle Policy-Version;
* Stichtag nicht aelter als ``MAX_AGE_DAYS``;
* Cashflow-Fingerprint unveraendert -- jede inhaltliche Aenderung der
  erfassten Cashflows (Betrag, Typ, Frequenz, Zeitraum, Waehrung, aktiv,
  einbezogen, neu, geloescht) invalidiert die Bestaetigung.

Ohne gueltige Bestaetigung bleiben erfasste Ausgaben eine UNTERGRENZE: zu
hohe Werte flaggen weiterhin (einwegig), niedrige Werte sind "nicht pruefbar".

DSG (DSG-ERASURE-NEW-EVIDENCE-001, Nachzug zu #681): die Tabelle ist
append-only. Personennamen (``household_persons_json``) und die Notiz
(``note``) werden deshalb VOR dem Hashen pro Kunde versiegelt
(services/pii_vault.py, Crypto-Shredding); Zeile und audit_log-Snapshot
tragen nur den Umschlag, der Hash bindet ihn. Die Gueltigkeitspruefung liest
keine Namen, sondern die hash-gebundene ``household_person_count``
(Schema V2). Altbestand V1 (Klartext, ohne Personenzahl) bleibt mit dem
V1-Hashvertrag verifizierbar und gueltig; die Erasure meldet ihn
(``pii_vault.count_unsealed_rows``).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from core.evidence import canonical_json, evidence_hash

SCHEMA_VERSION = "FinancialCoverageAttestationV2"
SCHEMA_VERSION_V1 = "FinancialCoverageAttestationV1"
# CIO-Default, Compliance zu bestaetigen: eine Bestaetigung gilt hoechstens
# 365 Tage ab Stichtag (jaehrlicher Review-Rhythmus).
POLICY_VERSION = "FCA-2026-10-20.v1"
MAX_AGE_DAYS = 365
ALLOWED_SOURCES: tuple[str, ...] = ("Kundengespräch", "Kundenunterlagen", "Kundenportal")

STATUS_VALID = "valid"
STATUS_MISSING = "missing"
STATUS_HASH_MISMATCH = "hash_mismatch"
STATUS_HOUSEHOLD_MISMATCH = "household_mismatch"
STATUS_POLICY_OUTDATED = "policy_outdated"
STATUS_INCOMPLETE = "incomplete_categories"
STATUS_EXPIRED = "expired"
STATUS_INPUTS_CHANGED = "inputs_changed"

STATUS_REASONS = {
    STATUS_VALID: "Vollständigkeit der Finanzdaten bestätigt.",
    STATUS_MISSING: "Vollständigkeit der erfassten Finanzdaten ist nicht bestätigt.",
    STATUS_HASH_MISMATCH: "Bestätigung der Finanzabdeckung ist nicht verifizierbar (Hash).",
    STATUS_HOUSEHOLD_MISMATCH: "Bestätigung der Finanzabdeckung gehört zu einem anderen Haushalt.",
    STATUS_POLICY_OUTDATED: "Bestätigung der Finanzabdeckung folgt einer veralteten Policy.",
    STATUS_INCOMPLETE: "Bestätigung der Finanzabdeckung ist unvollständig (nicht alle Kategorien bestätigt).",
    STATUS_EXPIRED: "Bestätigung der Finanzabdeckung ist abgelaufen.",
    STATUS_INPUTS_CHANGED: "Erfasste Cashflows wurden nach der Bestätigung geändert.",
}

# V1 (Altbestand, Klartext). Neue Felder nur mit neuer SCHEMA_VERSION --
# sonst gaelten bestehende Zeilen faelschlich als manipuliert.
HASHED_FIELDS_V1: tuple[str, ...] = (
    "id",
    "schema_version",
    "mandate_id",
    "client_id",
    "household_persons_json",
    "income_complete",
    "expenses_complete",
    "obligations_complete",
    "irregular_expenses_reviewed",
    "as_of_date",
    "source",
    "note",
    "cashflow_fingerprint",
    "cashflow_row_count",
    "actor_id",
    "attested_at",
    "policy_version",
)

# V2: Namen/Notiz versiegelt; die Personenzahl ist strukturiert gebunden.
HASHED_FIELDS: tuple[str, ...] = HASHED_FIELDS_V1 + ("household_person_count",)

_HASHED_FIELDS_BY_VERSION: dict[str, tuple[str, ...]] = {
    SCHEMA_VERSION_V1: HASHED_FIELDS_V1,
    SCHEMA_VERSION: HASHED_FIELDS,
}

CATEGORY_FIELDS: tuple[str, ...] = (
    "income_complete",
    "expenses_complete",
    "obligations_complete",
    "irregular_expenses_reviewed",
)

# Inhaltlich relevante Cashflow-Felder (Label/Notizen/updated_at bewusst nicht:
# reine Umbenennung aendert die Vollstaendigkeitsaussage nicht).
_FINGERPRINT_FIELDS: tuple[str, ...] = (
    "id",
    "cashflow_type",
    "amount_rappen",
    "gross_amount_rappen",
    "currency",
    "frequency",
    "nature",
    "valid_from",
    "valid_until",
    "is_active",
    "is_included",
)


def _value(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _canonical(payload: Any) -> str:
    return canonical_json(payload)


def attestation_payload(attestation: Any) -> dict[str, Any]:
    fields = _HASHED_FIELDS_BY_VERSION.get(
        str(_value(attestation, "schema_version") or ""), HASHED_FIELDS,
    )
    return {name: _value(attestation, name) for name in fields}


def compute_attestation_hash(attestation: Any) -> str:
    return evidence_hash(attestation_payload(attestation))


def verify_attestation(attestation: Any) -> bool:
    stored = _value(attestation, "attestation_hash")
    return bool(stored) and stored == compute_attestation_hash(attestation)


def fingerprint_cashflows(rows: Iterable[Any]) -> tuple[str, int]:
    """SHA-256 ueber die inhaltlichen Felder der erfassten Cashflows."""
    items = sorted(
        ([_value(row, name) for name in _FINGERPRINT_FIELDS] for row in rows),
        key=lambda item: str(item[0]),
    )
    digest = evidence_hash(items)
    return digest, len(items)


def current_cashflow_fingerprint(db, client_id: str) -> tuple[str, int]:
    from models.wealth import Cashflow

    rows = db.query(Cashflow).filter(
        Cashflow.client_id == client_id,
        Cashflow.deleted_at.is_(None),
    ).all()
    return fingerprint_cashflows(rows)


def _parse_date(value: Any) -> date | None:
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _normalize_persons(persons: Iterable[Any] | None) -> list[str]:
    cleaned = [str(p).strip() for p in (persons or [])]
    return [p for p in cleaned if p]


def create_attestation(
    db,
    mandate: Any,
    *,
    actor: Any,
    household_persons: Iterable[Any],
    income_complete: bool,
    expenses_complete: bool,
    obligations_complete: bool,
    irregular_expenses_reviewed: bool,
    as_of_date: str,
    source: str,
    note: str | None = None,
    now: str | None = None,
    today: date | None = None,
):
    """Legt eine neue Bestaetigung an (``db.add``, kein Commit).

    Wirft ValueError bei ungueltigen Angaben (Router -> 422).
    """
    from database import new_uuid
    from models.wealth import FinancialCoverageAttestation
    from services.pii_vault import seal_for_client

    today = today or date.today()
    persons = _normalize_persons(household_persons)
    if not persons:
        raise ValueError("Mindestens eine Person des Haushalts angeben.")
    as_of = _parse_date(as_of_date)
    if as_of is None:
        raise ValueError("Stichtag fehlt oder ist kein Datum (JJJJ-MM-TT).")
    if as_of > today:
        raise ValueError("Stichtag darf nicht in der Zukunft liegen.")
    if as_of + timedelta(days=MAX_AGE_DAYS) < today:
        raise ValueError(f"Stichtag ist älter als {MAX_AGE_DAYS} Tage.")
    source = str(source or "").strip()
    if source not in ALLOWED_SOURCES:
        raise ValueError("Quelle muss eine von: " + ", ".join(ALLOWED_SOURCES) + ".")
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    fingerprint, row_count = current_cashflow_fingerprint(db, mandate.client_id)
    note_text = (str(note).strip() or None) if note is not None else None
    # Versiegeln VOR dem Hashen (PiiVaultError fuer einen DSG-geloeschten
    # Kunden -> Router 409; es wird nie Klartext geschrieben).
    sealed_persons = seal_for_client(db, mandate.client_id, _canonical(persons))
    sealed_note = seal_for_client(db, mandate.client_id, note_text)
    row = FinancialCoverageAttestation(
        id=new_uuid(),
        schema_version=SCHEMA_VERSION,
        mandate_id=mandate.id,
        client_id=mandate.client_id,
        household_persons_json=sealed_persons,
        household_person_count=len(persons),
        income_complete=1 if income_complete else 0,
        expenses_complete=1 if expenses_complete else 0,
        obligations_complete=1 if obligations_complete else 0,
        irregular_expenses_reviewed=1 if irregular_expenses_reviewed else 0,
        as_of_date=as_of.isoformat(),
        source=source,
        note=sealed_note,
        cashflow_fingerprint=fingerprint,
        cashflow_row_count=row_count,
        actor_id=actor.id,
        attested_at=now,
        policy_version=POLICY_VERSION,
        created_at=now,
    )
    row.attestation_hash = compute_attestation_hash(row)
    db.add(row)
    db.flush()
    return row


def attestation_snapshot(row: Any) -> dict[str, Any]:
    """Replaybarer Audit-Snapshot: Payload + attestation_hash."""
    snapshot = attestation_payload(row)
    snapshot["attestation_hash"] = _value(row, "attestation_hash")
    return snapshot


def _status(code: str, row: Any = None, **extra) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "status": code,
        "reason": STATUS_REASONS[code],
        "attestation_id": _value(row, "id") if row is not None else None,
        "attestation_hash": _value(row, "attestation_hash") if row is not None else None,
        "as_of_date": _value(row, "as_of_date") if row is not None else None,
        "attested_at": _value(row, "attested_at") if row is not None else None,
        "actor_id": _value(row, "actor_id") if row is not None else None,
    }
    result.update(extra)
    return result


def _person_count(row: Any) -> int:
    """Personenzahl ohne Klartext-Namen: V2 -> hash-gebundene Spalte; V1-
    Altbestand (Klartext-JSON, keine Spalte) -> Laenge der Namensliste."""
    if row.schema_version != SCHEMA_VERSION_V1:
        try:
            return int(row.household_person_count or 0)
        except (TypeError, ValueError):
            return 0
    try:
        persons = json.loads(row.household_persons_json or "[]")
    except (TypeError, ValueError):
        persons = []
    return len(_normalize_persons(persons if isinstance(persons, list) else []))


def resolve_attestation(db, mandate: Any, *, today: date | None = None) -> dict[str, Any]:
    """Status der neuesten Bestaetigung des Mandats (read-only)."""
    from models.wealth import FinancialCoverageAttestation

    today = today or date.today()
    row = (
        db.query(FinancialCoverageAttestation)
        .filter(FinancialCoverageAttestation.mandate_id == mandate.id)
        .order_by(
            FinancialCoverageAttestation.attested_at.desc(),
            FinancialCoverageAttestation.created_at.desc(),
        )
        .first()
    )
    if row is None:
        return _status(STATUS_MISSING)
    if not verify_attestation(row):
        return _status(STATUS_HASH_MISMATCH, row)
    if row.client_id != getattr(mandate, "client_id", None):
        return _status(STATUS_HOUSEHOLD_MISMATCH, row)
    if _person_count(row) < 1:
        return _status(STATUS_HOUSEHOLD_MISMATCH, row)
    if row.policy_version != POLICY_VERSION or row.schema_version not in _HASHED_FIELDS_BY_VERSION:
        return _status(STATUS_POLICY_OUTDATED, row)
    missing = [name for name in CATEGORY_FIELDS if int(getattr(row, name) or 0) != 1]
    if missing:
        return _status(STATUS_INCOMPLETE, row, unconfirmed_categories=missing)
    as_of = _parse_date(row.as_of_date)
    expires = as_of + timedelta(days=MAX_AGE_DAYS) if as_of else None
    if expires is None or today > expires:
        return _status(STATUS_EXPIRED, row, valid_until=expires.isoformat() if expires else None)
    fingerprint, _count = current_cashflow_fingerprint(db, row.client_id)
    if fingerprint != row.cashflow_fingerprint:
        return _status(STATUS_INPUTS_CHANGED, row)
    return _status(STATUS_VALID, row, valid_until=expires.isoformat())


__all__ = [
    "SCHEMA_VERSION",
    "POLICY_VERSION",
    "MAX_AGE_DAYS",
    "ALLOWED_SOURCES",
    "attestation_snapshot",
    "compute_attestation_hash",
    "create_attestation",
    "current_cashflow_fingerprint",
    "fingerprint_cashflows",
    "resolve_attestation",
    "verify_attestation",
]
