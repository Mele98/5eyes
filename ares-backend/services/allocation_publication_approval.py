"""CCX-P4 Approval-Binding der Allokations-Publikation (Nachtrag 1).

* **Freigabemodus** (N-910-02, CTO-Entscheid): Vier-Augen (Freigeber !=
  Finalisierer, auch ueber die normalisierte E-Mail eines Zweitkontos) oder
  Einzelfreigabe. Die Einzelfreigabe ist nur zulaessig, wenn der Mandant
  AUSDRUECKLICH als Ein-Personen-Firma konfiguriert ist
  (``tenants.single_person_firm``, Admin-Einstellung mit Audit) UND zum
  Zeitpunkt genau ein aktiver Benutzer mit Publish-Recht existiert (eben der
  Freigeber), dazu eine Begruendung (>= 20 Zeichen). Zahl der Berechtigten und
  Konfiguration gehen in den ``approval_hash`` und ins Audit -- Deaktivieren und
  Reaktivieren eines Kollegen hebelt das nicht aus (ohne Konfiguration keine
  Einzelfreigabe, und die Konfiguration ist auditiert).
* **approval_hash** (N-910-05): HMAC-SHA256 statt ungeschluesseltem SHA-256.
  Schluessel: aus dem Tenant-DEK abgeleitet (``services.tenant_crypto``,
  Envelope-Verschluesselung unter der Master-KEK) mit eigener Domaene. Wer den
  Append-only-Trigger umgeht, kann den Hash ohne den Schluessel nicht
  nachrechnen. Ohne verfuegbaren Schluessel gilt keine Freigabe (fail-closed).
* **Schluesselversion** (H12 N-910-14, Codex-Pflicht): ``approval_key_version``
  = ``tenants.dek_version`` des Schluessels, mit dem gebunden wurde. Sie steht
  als eigene Spalte im Entscheid UND im HMAC-Record (eine manipulierte Spalte
  bricht den Hash). Beim Lesen wird sie VOR der Hash-Pruefung mit der heutigen
  DEK-Version verglichen: abweichend -> ``CCX_APPROVAL_KEY_ROTATED`` (die
  Freigabe muss nach einer DEK-Rotation bewusst neu publiziert werden), fehlend
  (Altpublikation vor H12) -> ``CCX_APPROVAL_KEY_VERSION_MISSING``; beides
  fail-closed. Die KEK-Generation gehoert NICHT zur Schluesselversion: ein
  Rewrap auf eine neue KEK behaelt den DEK, die Hashes bleiben gueltig
  (``get_tenant_dek`` verlangt ohnehin die aktuelle KEK-Generation).
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from core.evidence import SCHEME_V1, advisory_domain, canonical_json
from services.auth import same_person
from services.product_eligibility_governance import (
    APPROVAL_MODE_FOUR_EYES,
    APPROVAL_MODE_SINGLE_APPROVER_ATTESTED,
    MIN_ATTESTATION_REASON_LENGTH,
    tenant_approver_ids,
)
from services.tenant_crypto import TenantCryptoError, get_tenant_dek

ALLOCATION_PUBLICATION_SCHEMA_VERSION = "ares/allocation-publication/1"
# Publish-Recht: die Rollen von require_advisor (admin/advisor des Mandanten).
PUBLICATION_APPROVER_ROLES: tuple[str, ...] = ("admin", "advisor")
SINGLE_APPROVER_LABEL = "Einzelfreigabe (eine berechtigte Person)"
APPROVAL_MODE_LABELS = {
    APPROVAL_MODE_FOUR_EYES: "Vier-Augen-Freigabe",
    APPROVAL_MODE_SINGLE_APPROVER_ATTESTED: SINGLE_APPROVER_LABEL,
}

_APPROVAL_DOMAIN = advisory_domain("allocation-publication-approval")
_APPROVAL_KEY_LABEL = b"Ares\x00ares/allocation-publication/approval-key/1\x00"


class ApprovalKeyUnavailable(RuntimeError):
    """Kein Tenant-Schluessel fuer das Approval-Binding (fail-closed)."""


@dataclass(frozen=True)
class ApprovalBasis:
    """Ergebnis der Freigabepruefung (``mode`` None = nicht freigegeben)."""

    mode: str | None
    eligible_approver_count: int
    single_person_firm: int


def approval_mode_label(mode: Any) -> str | None:
    return APPROVAL_MODE_LABELS.get(str(mode)) if mode else None


def tenant_is_single_person_firm(db: Session, tenant_id: str | None) -> bool:
    """Ausdrueckliche Tenant-Konfiguration; ohne Spalte/Wert: nein."""
    if not tenant_id:
        return False
    try:
        value = db.execute(
            text("SELECT single_person_firm FROM tenants WHERE id = :t"), {"t": str(tenant_id)},
        ).scalar()
    except Exception:  # noqa: BLE001 - Altschema ohne Spalte: keine Ein-Personen-Firma
        return False
    return value == 1


def publication_approver_ids(db: Session, tenant_id: str | None) -> list[str]:
    """Aktive Publish-Berechtigte des Mandanten -- dieselbe Zaehlung wie die
    Einzelfreigabe (``approval_basis``) und die Plausibilisierung der
    Ein-Personen-Firma (H12 N-910-15, ``routers/tenants.py``)."""
    return tenant_approver_ids(db, tenant_id, roles=PUBLICATION_APPROVER_ROLES)


def approval_basis(
    db: Session, *, tenant_id: str | None, approver_id: str, preparer_id: str | None,
    single_approver_attestation: bool, attestation_reason: str | None,
) -> ApprovalBasis:
    """Vier-Augen oder (nur unter den Bedingungen oben) Einzelfreigabe."""
    approvers = publication_approver_ids(db, tenant_id)
    configured = 1 if tenant_is_single_person_firm(db, tenant_id) else 0
    count = len(approvers)
    mode: str | None = None
    if preparer_id and not same_person(db, approver_id, preparer_id):
        mode = APPROVAL_MODE_FOUR_EYES
    elif (single_approver_attestation
          and len((attestation_reason or "").strip()) >= MIN_ATTESTATION_REASON_LENGTH
          and configured == 1 and approvers == [str(approver_id)]):
        mode = APPROVAL_MODE_SINGLE_APPROVER_ATTESTED
    return ApprovalBasis(mode=mode, eligible_approver_count=count, single_person_firm=configured)


def _approval_key(db: Session, tenant_id: str) -> bytes:
    try:
        dek = get_tenant_dek(db, str(tenant_id))
    except (TenantCryptoError, RuntimeError, ValueError) as exc:
        raise ApprovalKeyUnavailable(str(exc)) from exc
    return hmac.new(dek, _APPROVAL_KEY_LABEL, hashlib.sha256).digest()


def _read_dek_version(db: Session, tenant_id: str) -> Any:
    """N-912-05: Auf PostgreSQL bricht ein fehlgeschlagenes Statement die ganze
    Transaktion ab. Darum dort ein SAVEPOINT direkt auf der Session-Verbindung
    (kein ORM-Flush); scheitert der SELECT, wird nur der Savepoint
    zurueckgerollt und die Session bleibt benutzbar. SQLite bricht die
    Transaktion bei einem fehlgeschlagenen SELECT nicht ab (unveraendert)."""
    statement = text("SELECT dek_version FROM tenants WHERE id = :t")
    params = {"t": str(tenant_id)}
    conn = db.connection()
    if conn.dialect.name == "postgresql":
        with conn.begin_nested():
            return conn.execute(statement, params).scalar()
    return conn.execute(statement, params).scalar()


def current_approval_key_version(db: Session, tenant_id: str) -> int:
    """H12 N-910-14: Version des heutigen Approval-Schluessels (= DEK-Generation
    ``tenants.dek_version``). Stellt den DEK bei Bedarf bereit (wie
    ``_approval_key``); ohne lesbare Version keine Freigabe (fail-closed)."""
    _approval_key(db, tenant_id)
    try:
        version = _read_dek_version(db, tenant_id)
    except (OperationalError, ProgrammingError) as exc:
        # N-912-05: nur die DB-Fehler eines Altschemas ohne Spalte (SQLite
        # OperationalError, PostgreSQL ProgrammingError) -> fail-closed. Alles
        # andere wird nicht maskiert.
        raise ApprovalKeyUnavailable(f"DEK-Version nicht lesbar: {exc}") from exc
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ApprovalKeyUnavailable(f"DEK-Version des Mandanten unbekannt ({version!r}).")
    return version


def approval_hash_for(
    db: Session,
    *,
    tenant_id: str,
    mandate_id: str,
    publication_sequence: int,
    validation_hash: str,
    envelope_id: str,
    envelope_hash: str,
    target_allocation_id: str,
    approved_by: str,
    approved_at: str,
    approval_mode: str,
    eligible_approver_count: int,
    single_person_firm: int,
    approval_key_version: int,
) -> str:
    """Approval-Binding (HMAC): Freigeber, Zeit, Modus und Basis der Freigabe
    an genau diesen geprueften Stand (Validation, Envelope, Soll-Allokation,
    Sequenz)."""
    record = {
        "schema_version": ALLOCATION_PUBLICATION_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "mandate_id": mandate_id,
        "publication_sequence": int(publication_sequence),
        "validation_hash": validation_hash,
        "envelope_id": envelope_id,
        "envelope_hash": envelope_hash,
        "target_allocation_id": target_allocation_id,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "approval_mode": approval_mode,
        "eligible_approver_count": int(eligible_approver_count),
        "single_person_firm": int(single_person_firm),
        "approval_key_version": int(approval_key_version),
    }
    payload = _APPROVAL_DOMAIN + canonical_json(record, scheme=SCHEME_V1).encode("utf-8")
    return hmac.new(_approval_key(db, tenant_id), payload, hashlib.sha256).hexdigest()


__all__ = [
    "ALLOCATION_PUBLICATION_SCHEMA_VERSION",
    "APPROVAL_MODE_FOUR_EYES",
    "APPROVAL_MODE_LABELS",
    "APPROVAL_MODE_SINGLE_APPROVER_ATTESTED",
    "ApprovalBasis",
    "ApprovalKeyUnavailable",
    "MIN_ATTESTATION_REASON_LENGTH",
    "PUBLICATION_APPROVER_ROLES",
    "SINGLE_APPROVER_LABEL",
    "approval_basis",
    "approval_hash_for",
    "approval_mode_label",
    "current_approval_key_version",
    "publication_approver_ids",
    "tenant_is_single_person_firm",
]
