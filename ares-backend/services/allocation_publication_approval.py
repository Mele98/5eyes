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
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
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


def approval_basis(
    db: Session, *, tenant_id: str | None, approver_id: str, preparer_id: str | None,
    single_approver_attestation: bool, attestation_reason: str | None,
) -> ApprovalBasis:
    """Vier-Augen oder (nur unter den Bedingungen oben) Einzelfreigabe."""
    approvers = tenant_approver_ids(db, tenant_id, roles=PUBLICATION_APPROVER_ROLES)
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
    "tenant_is_single_person_firm",
]
