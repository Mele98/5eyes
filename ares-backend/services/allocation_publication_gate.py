"""CCX-P4 Allocation-Publish: die EINE zentrale Publish-Gatefunktion.

Vertrag 2026-11-13 §7. Eine Soll-Allokation -- generiert oder manuell erfasst
bzw. geaendert -- wird ausschliesslich ueber :func:`publish_allocation`
kundenwirksam. Bis dahin ist sie ein Entwurf: aktuelle Soll-Allokation-
Endpunkte liefern sie als ``DRAFT``, Kunden-PDFs tragen das Wasserzeichen
"Entwurf -- Soll-Allokation nicht publiziert" und werden nie als finale
(signierbare) Fassung archiviert, Handoff und "Portfolio umsetzen" sind hart
gesperrt.

Publish ist eine Transaktion (Mandatssperre unter PostgreSQL):

1. Pruefung (:func:`evaluate_allocation_publication`): aktuelle Soll-Allokation
   ist genau die, die der aktuelle versiegelte Envelope (P1) bindet;
   Envelope integer, SEALED und FRESH inkl. Pull-Pruefung der Kanten (P2);
   Bewertungs-Snapshot COMPLETE (P3); wirksame Risiko-/CMA-/Policy-Bindungen
   (Kanten); Summe genau 10'000 bps; jede Quote innerhalb ihrer Baender;
   persistierter Allocation-Context (Reserve-Ledger, Restriktionen,
   Zielanalyse) integer; Eignungs-/Restriktions-/ESG-/Retro-/KYC-Gates
   (H7/H8/C-890/E2, Risikobudget, ADR-12a). Ergebnis: katalogisierte
   Blocker-Codes und ``validation_hash`` (domaenensepariert ueber den
   geprueften Stand inkl. aktuellem Active-Pointer).
2. Freigabe: ``expected_validation_hash`` muss dem Stand beim Commit
   entsprechen (Mutation nach Pruefung -> ``CCX_VALIDATION_HASH_MISMATCH``);
   Vier-Augen-Regel (Freigeber != Finalisierer; Einzelfreigabe nur bei genau
   einer freigabeberechtigten Person mit Begruendung, Muster
   product_eligibility_override). ``approval_hash`` bindet Validation,
   Envelope, Soll-Allokation, Sequenz, Freigeber, Zeit und Modus.
3. Publikationsentscheid (append-only) und Active-Pointer werden atomar
   geschrieben; ein paralleler Publisher scheitert an Sequenz/Unique/Pointer-
   Version (``CCX_PUBLICATION_RACE``).

Jede Ablehnung: Rollback, Tenant-Kontext wieder gesetzt, abgelehnter Versuch
als Entscheid ``publishable = 0`` mit Blocker-Codes festgehalten (soweit die
Sequenz frei ist) und ``ccx.allocation.publication_rejected`` auditiert --
nie ein Fallback auf eine aeltere Publikation.

Lesen (:func:`active_publication_state`) prueft vor jeder kundenwirksamen
Verwendung erneut: Pointer -> publizierbarer Entscheid -> Approval-Hash
reproduzierbar -> Envelope SEALED, Hash gleich, integer, FRESH (Pull) ->
aktuelle Soll-Allokation ist die publizierte. Sonst ist nichts publiziert.
Keine Fachwirkung auf Engine, Optimizer oder Monte Carlo.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.evidence import SCHEME_V1, advisory_domain, canonical_json, domain_sha256_hex
from core.reason_codes import DomainError, ReasonCode
from core.db_integrity import is_check_constraint_violation
from database import new_uuid
from models.allocation import TargetAllocation
from models.review import RecommendationRun
from models.snapshots import (
    ALLOCATION_PUBLICATION_SCHEMA_VERSION,
    AdvisoryDecisionEnvelope,
    AdvisoryDependencyEdge,
    AdvisoryEnvelopeBinding,
    AllocationActivePublication,
    AllocationPublicationDecision,
    HoldingsValuationSnapshot,
)
from services.advisory_decision_envelope import (
    VALUATION_BINDING_KIND,
    current_sealed_envelope,
    lock_mandate_row,
    mandate_tenant,
    persist_freshness_drift,
    pull_freshness,
    rollback_keeping_tenant,
    verify_envelope,
)
# ALLOC-EDITOR-STALE-001: der Browser-Kontext-Abgleich der Strategie-PDFs
# (Vertrags-Consumer) laeuft ueber diese Fassade mit (pdf_reports ohne neue Kante).
from services.allocation_concurrency import AllocationVersionConflict, assert_report_allocation_matches
from services.audit import log
from services.fx_basis import STATUS_MISMATCH, STATUS_OK, STATUS_STALE, load_fx_basis
from services.auth import same_person
from services.portfolio_engine_allocation_integrity import (
    _verified_persisted_allocation_context,
    analysis_integrity_report,
)
from services.product_eligibility_governance import (
    APPROVAL_MODE_FOUR_EYES,
    APPROVAL_MODE_SINGLE_APPROVER_ATTESTED,
    MIN_ATTESTATION_REASON_LENGTH,
    tenant_approver_ids,
)
from services.recommendation_release_gate import (
    CHANNEL_PUBLICATION,
    assert_client_onboarding_release_eligible,
    assert_kyc_review_release_eligible,
    assert_preference_release_ready,
    assert_recommendation_release_eligible,
    assert_retrocession_release_eligible,
    assert_risk_signoff_release_eligible,
)

logger = logging.getLogger(__name__)

# ── Vertrag CCX-04 ────────────────────────────────────────────────────────────

VALIDATION_PASS = "PASS"
VALIDATION_REJECTED = "REJECTED"
APPROVAL_APPROVED = "APPROVED"


def is_publishable(validation: Any, approval: Any) -> bool:
    """CCX-04: publizierbar nur, wenn die Pruefung bestanden UND die Freigabe
    erteilt ist. Alles andere -- abgelehnt, Entwurf, unbekannt, leer -- ist
    nicht publizierbar (unknown != approved)."""
    return validation == VALIDATION_PASS and approval == APPROVAL_APPROVED


# ── Konstanten ────────────────────────────────────────────────────────────────

STATUS_PUBLISHED = "PUBLISHED"
STATUS_DRAFT = "DRAFT"
STATUS_PUBLICATION_INVALID = "PUBLICATION_INVALID"

AUDIT_TABLE = "allocation_publication_decisions"
AUDIT_PUBLISHED = "ccx.allocation.published"
AUDIT_REJECTED = "ccx.allocation.publication_rejected"
AUDIT_CHANNEL_BLOCKED = "ccx.allocation.channel_blocked"

PUBLICATION_APPROVER_ROLES: tuple[str, ...] = ("admin", "advisor")
# Sichtbare Kennzeichnung der Freigabeart in Nachweis, Audit und Masken.
SINGLE_APPROVER_LABEL = "Einzelfreigabe (eine berechtigte Person)"
APPROVAL_MODE_LABELS = {
    APPROVAL_MODE_FOUR_EYES: "Vier-Augen-Freigabe",
    APPROVAL_MODE_SINGLE_APPROVER_ATTESTED: SINGLE_APPROVER_LABEL,
}


def approval_mode_label(mode: Any) -> str | None:
    return APPROVAL_MODE_LABELS.get(str(mode)) if mode else None
BUCKETS: tuple[str, ...] = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
TOTAL_BPS = 10_000
# Wirksame Bindungen, ohne die keine Strategie kundenwirksam wird (P2-Kanten).
REQUIRED_EDGE_KINDS: tuple[str, ...] = ("risk", "cma", "optimizer_policy", "constraints")

_VALIDATION_DOMAIN = advisory_domain("allocation-publication-validation")
_APPROVAL_DOMAIN = advisory_domain("allocation-publication-approval")

_VALUATION_CODES = {
    "COMPLETE": None,
    "PARTIAL": ReasonCode.CCX_VALUATION_INCOMPLETE,
    "UNKNOWN": ReasonCode.CCX_VALUATION_INCOMPLETE,
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hash(domain: bytes, record: dict[str, Any]) -> str:
    _assert_integer_only(record, "record")
    return domain_sha256_hex(domain, canonical_json(record, scheme=SCHEME_V1).encode("utf-8"))


def _assert_integer_only(value: Any, path: str) -> None:
    """Rohwerte bleiben Integer/Strings (Vertrag §1): kein Float im Hash."""
    if isinstance(value, float):
        raise ValueError(f"{path}: float im Publikations-Hash verboten")
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_integer_only(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_integer_only(item, f"{path}[{index}]")


def validation_hash_for(record: dict[str, Any]) -> str:
    """Domaenenseparierter Hash des geprueften Stands."""
    return _hash(_VALIDATION_DOMAIN, record)


def approval_hash_for(
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
) -> str:
    """Approval-Binding: Freigeber, Zeit und Modus an genau diesen
    geprueften Stand (Validation, Envelope, Soll-Allokation, Sequenz)."""
    return _hash(_APPROVAL_DOMAIN, {
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
    })


# ── Pruefung ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PublicationEvaluation:
    tenant_id: str | None
    mandate_id: str
    target_allocation_id: str | None
    envelope_id: str | None
    envelope_hash: str | None
    sealed_by: str | None
    blockers: tuple[str, ...]
    validation_hash: str
    record: dict[str, Any] = field(repr=False)
    already_published: bool = False

    @property
    def validation_status(self) -> str:
        return VALIDATION_PASS if not self.blockers else VALIDATION_REJECTED


def current_target_allocation(db: Session, mandate_id: str) -> TargetAllocation | None:
    """Arbeitsstand: die (einzige) aktuelle Soll-Allokation; mehrere -> Fehler."""
    rows = db.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == str(mandate_id),
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None),
    ).order_by(TargetAllocation.version.desc()).limit(2).all()
    if len(rows) > 1:
        raise ValueError("Mehrere aktuelle Soll-Allokationen gefunden.")
    return rows[0] if rows else None


FX_DEFAULT_SOURCE = "Default"


def _fx_basis_findings(snapshot: Any) -> list[str]:
    """Strikte FX-Basis (N-909-01): publiziert wird nie auf einem Ersatzkurs
    (Quelle ``Default``) oder einer unbelegten/abgelaufenen Kursbasis --
    zusaetzlich zur COMPLETE-Abdeckung des P3-Snapshots."""
    missing = [_finding(reason_code=ReasonCode.CCX_FX_BASIS_MISSING)]
    try:
        basis = json.loads(snapshot.fx_basis_json or "")
    except (TypeError, ValueError):
        return missing
    if not isinstance(basis, dict) or basis.get("fx_basis_hash") != snapshot.fx_basis_hash:
        return missing
    quotes = basis.get("quotes")
    statuses = basis.get("statuses")
    if not isinstance(quotes, list) or not isinstance(statuses, dict):
        return missing
    if any(str(status) != "OK" for status in statuses.values()):
        return missing
    for quote in quotes:
        if not isinstance(quote, dict) or str(quote.get("source") or "") == FX_DEFAULT_SOURCE \
                or not isinstance(quote.get("rate_x10000"), int) or quote["rate_x10000"] <= 0:
            return missing
    return []


def _current_fx_findings(db: Session, snapshot: Any, tenant_id: str | None) -> list[str]:
    """Strikte FX-Basis ZUM PUBLIKATIONSZEITPUNKT (Integration P3 N1): die im
    Snapshot gebundene Basis war bei der Finalisierung belegt; kundenwirksam
    wird die Allokation aber erst jetzt. Fuer jede dort benoetigte Waehrung
    muss auch jetzt ein belegter, frischer DB-Kurs bestehen (Tenant-Frist,
    Default 5 Tage) -- fehlt er oder gibt es nur einen Ersatzkurs (Quelle
    ``Default``), sperrt ``CCX_FX_BASIS_MISSING``; abgelaufen
    ``CCX_FX_BASIS_STALE``, nach dem Stichtag ``CCX_FX_BASIS_MISMATCH``. Die
    gebundene Basis selbst bleibt unveraendert (kein Nachrechnen)."""
    try:
        basis = json.loads(snapshot.fx_basis_json or "")
    except (TypeError, ValueError):
        return []  # bereits von _fx_basis_findings gesperrt
    statuses = basis.get("statuses") if isinstance(basis, dict) else None
    if not isinstance(statuses, dict) or not statuses:
        return []  # nur Basiswaehrung im Spiel: kein Kurs noetig
    currencies = sorted(str(c) for c in statuses)
    current = load_fx_basis(db, basis.get("target_currency") or "CHF", currencies, tenant_id=tenant_id)
    findings: list[str] = []
    for currency in currencies:
        status = current.statuses.get(currency)
        if status == STATUS_OK:
            continue
        if status == STATUS_STALE:
            findings.append(_finding(reason_code=ReasonCode.CCX_FX_BASIS_STALE))
        elif status == STATUS_MISMATCH:
            findings.append(_finding(reason_code=ReasonCode.CCX_FX_BASIS_MISMATCH))
        else:
            findings.append(_finding(reason_code=ReasonCode.CCX_FX_BASIS_MISSING))
    return list(dict.fromkeys(findings))


def _finding(*, reason_code: ReasonCode) -> str:
    """Blocker-Code einer Pruefung (katalogisiert, statisch aufloesbar)."""
    return str(reason_code.value)


def _allocation_findings(ta: TargetAllocation) -> list[str]:
    targets = {b: int(getattr(ta, f"target_{b}_bps") or 0) for b in BUCKETS}
    minimums = {b: int(getattr(ta, f"band_{b}_min_bps")) for b in BUCKETS}
    maximums = {b: int(getattr(ta, f"band_{b}_max_bps")) for b in BUCKETS}
    findings: list[str] = []
    if sum(targets.values()) != TOTAL_BPS or any(v < 0 for v in targets.values()):
        findings.append(_finding(reason_code=ReasonCode.CCX_ALLOCATION_SUM_INVALID))
    if any(not (0 <= minimums[b] <= targets[b] <= maximums[b] <= TOTAL_BPS) for b in BUCKETS):
        findings.append(_finding(reason_code=ReasonCode.CCX_ALLOCATION_BAND_VIOLATED))
    if findings:
        return findings
    try:
        _verified_persisted_allocation_context(ta, targets=targets, minimums=minimums, maximums=maximums)
    except (ValueError, TypeError) as exc:
        logger.info("CCX-P4: Allocation-Context nicht publizierbar | ta=%s: %s", ta.id, exc)
        return [_finding(reason_code=ReasonCode.CCX_ALLOCATION_CONTEXT_INVALID)]
    report = analysis_integrity_report(ta)
    if any(str(v.get("status") if isinstance(v, dict) else v) == "integrity_mismatch" for v in report.values()):
        return [_finding(reason_code=ReasonCode.CCX_ALLOCATION_CONTEXT_INVALID)]
    return []


def _gate_codes(db: Session, mandate: Any, run: Any) -> list[str]:
    """Eignungs-/Restriktions-/ESG-/Retro-/KYC-Gates ohne Seiteneffekt
    (kein Audit-Callback); jeder Block liefert seinen katalogisierten Code."""
    checks: list[Callable[[], Any]] = [
        lambda: assert_risk_signoff_release_eligible(db, mandate, channel=CHANNEL_PUBLICATION),
        lambda: assert_recommendation_release_eligible(db, mandate, channel=CHANNEL_PUBLICATION, run=run),
        lambda: assert_preference_release_ready(db, mandate, channel=CHANNEL_PUBLICATION),
        lambda: assert_retrocession_release_eligible(db, mandate, channel=CHANNEL_PUBLICATION, run=run),
        lambda: assert_client_onboarding_release_eligible(db, mandate, channel=CHANNEL_PUBLICATION),
        lambda: assert_kyc_review_release_eligible(db, mandate, channel=CHANNEL_PUBLICATION),
    ]
    codes: list[str] = []
    for check in checks:
        try:
            check()
        except DomainError as exc:
            codes.append(str(exc.reason_code))
        except Exception as exc:  # HTTPException-artige Gates (Status + detail)
            status = getattr(exc, "status_code", None)
            if status is None or int(status) < 400 or int(status) >= 500:
                raise
            detail = getattr(exc, "detail", None)
            code = detail.get("reason_code") if isinstance(detail, dict) else None
            codes.append(str(code or ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE.value))
    return codes


def _active_pointer(db: Session, tenant_id: str, mandate_id: str) -> AllocationActivePublication | None:
    return db.query(AllocationActivePublication).filter(
        AllocationActivePublication.tenant_id == tenant_id,
        AllocationActivePublication.mandate_id == str(mandate_id),
    ).first()


def _decision(db: Session, tenant_id: str, publication_id: str) -> AllocationPublicationDecision | None:
    return db.query(AllocationPublicationDecision).filter(
        AllocationPublicationDecision.tenant_id == tenant_id,
        AllocationPublicationDecision.id == str(publication_id),
    ).first()


def evaluate_allocation_publication(
    db: Session, mandate: Any, *, collect_drift: list | None = None,
) -> PublicationEvaluation:
    """Prueft, ob die aktuelle Soll-Allokation publiziert werden darf (keine
    Schreibwirkung). Liefert Blocker-Codes und den ``validation_hash``."""
    tenant_id = mandate_tenant(mandate)
    mandate_id = str(mandate.id)
    blockers: list[str] = []
    record: dict[str, Any] = {
        "schema_version": ALLOCATION_PUBLICATION_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "mandate_id": mandate_id,
    }
    try:
        ta = current_target_allocation(db, mandate_id)
    except ValueError:
        ta = None
        blockers.append(_finding(reason_code=ReasonCode.CCX_ALLOCATION_CONTEXT_INVALID))
    envelope = current_sealed_envelope(db, tenant_id, mandate_id) if tenant_id else None
    if tenant_id is None:
        blockers.append(ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE.value)
    if ta is None and not blockers:
        blockers.append(ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE.value)
    if envelope is None:
        blockers.append(ReasonCode.CCX_ENVELOPE_MISSING.value)
    record["target_allocation"] = None if ta is None else {
        "id": str(ta.id), "version": int(ta.version or 0),
        "targets_bps": {b: int(getattr(ta, f"target_{b}_bps") or 0) for b in BUCKETS},
        "bands_bps": {b: [int(getattr(ta, f"band_{b}_min_bps")), int(getattr(ta, f"band_{b}_max_bps"))]
                      for b in BUCKETS},
        "allocation_context_hash": getattr(ta, "allocation_context_hash", None),
    }
    bindings: dict[str, str] = {}
    run = None
    if envelope is not None:
        record["envelope"] = {"id": envelope.id, "envelope_hash": envelope.envelope_hash}
        defect = verify_envelope(db, envelope)
        if defect is not None:
            blockers.append(ReasonCode.CCX_ENVELOPE_HASH_MISMATCH.value
                            if defect[0] == ReasonCode.CCX_ENVELOPE_HASH_MISMATCH else ReasonCode.CCX_BINDING_MISSING.value)
        rows = db.query(AdvisoryEnvelopeBinding).filter(
            AdvisoryEnvelopeBinding.tenant_id == envelope.tenant_id,
            AdvisoryEnvelopeBinding.envelope_id == envelope.id,
        ).all()
        bindings = {row.binding_kind: row.object_id for row in rows}
        child = {row.binding_kind: row.child_hash for row in rows}
        record["bindings"] = {kind: child[kind] for kind in sorted(child)}
        if ta is not None and bindings.get("target_allocation") != str(ta.id):
            # Neuer Entwurf seit der Finalisierung: erst finalisieren, dann publizieren.
            blockers.append(ReasonCode.CCX_BINDING_MISSING.value)
        code, _detail, drift = pull_freshness(db, envelope, mandate=mandate)
        if code is not None:
            blockers.append(str(code))
            if collect_drift is not None and drift:
                collect_drift.extend(drift)
        edge_kinds = {row[0] for row in db.query(AdvisoryDependencyEdge.dependency_kind).filter(
            AdvisoryDependencyEdge.tenant_id == envelope.tenant_id,
            AdvisoryDependencyEdge.envelope_id == envelope.id,
        ).all()}
        if not set(REQUIRED_EDGE_KINDS) <= edge_kinds:
            blockers.append(ReasonCode.CCX_BINDING_MISSING.value)
        snapshot_id = bindings.get(VALUATION_BINDING_KIND)
        snapshot = db.query(HoldingsValuationSnapshot).filter(
            HoldingsValuationSnapshot.tenant_id == envelope.tenant_id,
            HoldingsValuationSnapshot.id == str(snapshot_id or ""),
        ).first() if snapshot_id else None
        if snapshot is None:
            blockers.append(ReasonCode.CCX_VALUATION_MISSING.value)
        else:
            record["valuation"] = {"snapshot_hash": snapshot.snapshot_hash, "coverage": snapshot.coverage_status}
            valuation_code = _VALUATION_CODES.get(snapshot.coverage_status, ReasonCode.CCX_VALUATION_INCOMPLETE)
            if valuation_code is not None:
                blockers.append(valuation_code.value)
            blockers.extend(_fx_basis_findings(snapshot))
            blockers.extend(_current_fx_findings(db, snapshot, envelope.tenant_id))
        run = db.query(RecommendationRun).filter(
            RecommendationRun.id == str(bindings.get("recommendation_run") or ""),
            RecommendationRun.mandate_id == mandate_id,
        ).first()
        if run is None or run.result_status != "Final":
            blockers.append(ReasonCode.CCX_BINDING_MISSING.value)
    if ta is not None:
        blockers.extend(_allocation_findings(ta))
    if ta is not None and run is not None:
        blockers.extend(_gate_codes(db, mandate, run))
    pointer = _active_pointer(db, tenant_id, mandate_id) if tenant_id else None
    already = False
    if pointer is not None:
        record["active_publication"] = {"id": pointer.publication_id, "version": int(pointer.optimistic_version)}
        active = _decision(db, tenant_id, pointer.publication_id)
        already = bool(envelope is not None and active is not None and active.envelope_id == envelope.id)
    else:
        record["active_publication"] = None
    unique_blockers = tuple(dict.fromkeys(blockers))
    record["blockers"] = list(unique_blockers)
    return PublicationEvaluation(
        tenant_id=tenant_id, mandate_id=mandate_id,
        target_allocation_id=str(ta.id) if ta is not None else None,
        envelope_id=envelope.id if envelope is not None else None,
        envelope_hash=envelope.envelope_hash if envelope is not None else None,
        sealed_by=getattr(envelope, "sealed_by", None) if envelope is not None else None,
        blockers=unique_blockers, validation_hash=validation_hash_for(record), record=record,
        already_published=already,
    )


# ── Vier Augen ────────────────────────────────────────────────────────────────


def approval_mode_for(
    db: Session, *, tenant_id: str, approver_id: str, preparer_id: str | None,
    single_approver_attestation: bool, attestation_reason: str | None,
) -> str | None:
    """Vier-Augen: Freigeber != Finalisierer. Einzelfreigabe nur, wenn genau
    eine Person freigabeberechtigt ist und eine Begruendung vorliegt.
    ``None`` = nicht freigegeben."""
    if preparer_id and not same_person(db, approver_id, preparer_id):
        return APPROVAL_MODE_FOUR_EYES
    if not single_approver_attestation:
        return None
    if len((attestation_reason or "").strip()) < MIN_ATTESTATION_REASON_LENGTH:
        return None
    if tenant_approver_ids(db, tenant_id, roles=PUBLICATION_APPROVER_ROLES) != [str(approver_id)]:
        return None
    return APPROVAL_MODE_SINGLE_APPROVER_ATTESTED


# ── Publizieren ───────────────────────────────────────────────────────────────


def _audit(db: Session, *, user: Any, mandate: Any, tenant_id: str | None, ip_address: str | None,
           field_name: str, record_id: str, **parts: Any) -> None:
    value = ";".join(f"{k}={v if v not in (None, '') else '-'}" for k, v in parts.items())
    log(db, user_id=user.id, user_name=getattr(user, "full_name", None) or getattr(user, "username", ""),
        table_name=AUDIT_TABLE, record_id=record_id, action="CREATE", field_name=field_name,
        new_value=value, mandate_id=getattr(mandate, "id", None), client_id=getattr(mandate, "client_id", None),
        ip_address=ip_address, tenant_id=tenant_id)


def _next_sequence(db: Session, mandate_id: str) -> int:
    rows = db.query(AllocationPublicationDecision.publication_sequence).filter(
        AllocationPublicationDecision.mandate_id == str(mandate_id),
    ).order_by(AllocationPublicationDecision.publication_sequence.desc()).limit(1).all()
    return (int(rows[0][0]) if rows else 0) + 1


def _reject(
    db: Session, *, evaluation: PublicationEvaluation, mandate: Any, user: Any, ip_address: str | None,
    code: ReasonCode, message: str, blockers: tuple[str, ...], drift: list | None = None,
    http_status: int = 409,
) -> DomainError:
    """Rollback, Tenant-Kontext, abgelehnter Versuch als Entscheid
    ``publishable = 0`` (soweit die Sequenz frei ist), Audit, Commit."""
    rollback_keeping_tenant(db)
    if drift and evaluation.envelope_id:
        envelope = db.get(AdvisoryDecisionEnvelope, evaluation.envelope_id)
        if envelope is not None:
            persist_freshness_drift(db, envelope, drift, user)
    tenant_id = evaluation.tenant_id
    decision_id = None
    if tenant_id is not None:
        try:
            decision_id = new_uuid()
            db.add(AllocationPublicationDecision(
                id=decision_id, tenant_id=tenant_id, mandate_id=evaluation.mandate_id,
                schema_version=ALLOCATION_PUBLICATION_SCHEMA_VERSION, envelope_id=evaluation.envelope_id,
                target_allocation_id=evaluation.target_allocation_id,
                publication_sequence=_next_sequence(db, evaluation.mandate_id),
                validation_hash=evaluation.validation_hash, publishable=0,
                blocker_codes_json=json.dumps(list(blockers) or [code.value]),
                created_at=_now(), created_by=user.id,
            ))
            db.flush()
        except IntegrityError as exc:
            # Sequenz parallel vergeben (oder F1: CHECK-Verletzung): der Versuch
            # steht dann nur im Audit -- die Ablehnung selbst bleibt bestehen.
            logger.info("CCX-P4: abgelehnter Versuch nicht festgehalten (check=%s)",
                        is_check_constraint_violation(exc))
            rollback_keeping_tenant(db)
            decision_id = None
    _audit(db, user=user, mandate=mandate, tenant_id=tenant_id, ip_address=ip_address,
           field_name=AUDIT_REJECTED, record_id=decision_id or evaluation.mandate_id,
           reason_code=code.value, blockers=",".join(blockers), target_allocation=evaluation.target_allocation_id,
           envelope_hash=evaluation.envelope_hash, validation_hash=evaluation.validation_hash)
    db.commit()
    return DomainError(code, message, http_status=http_status, extra={
        "channel": CHANNEL_PUBLICATION, "blocker_codes": list(blockers),
        "validation_hash": evaluation.validation_hash,
    })


def publish_allocation(
    db: Session,
    mandate: Any,
    *,
    user: Any,
    expected_validation_hash: str,
    expected_target_allocation_id: str,
    single_approver_attestation: bool = False,
    attestation_reason: str | None = None,
    ip_address: str | None = None,
) -> AllocationPublicationDecision:
    """Die einzige Stelle, die eine Soll-Allokation kundenwirksam macht."""
    lock_mandate_row(db, str(mandate.id))
    drift: list = []
    evaluation = evaluate_allocation_publication(db, mandate, collect_drift=drift)
    common = {"evaluation": evaluation, "mandate": mandate, "user": user, "ip_address": ip_address}
    if evaluation.blockers:
        raise _reject(db, code=ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE, blockers=evaluation.blockers, drift=drift,
                      message="Die Soll-Allokation kann noch nicht publiziert werden.", **common)
    if evaluation.already_published:
        raise _reject(db, code=ReasonCode.CCX_PUBLICATION_RACE, blockers=(ReasonCode.CCX_PUBLICATION_RACE.value,),
                      message="Diese Soll-Allokation ist bereits publiziert.", **common)
    if (expected_target_allocation_id != evaluation.target_allocation_id
            or expected_validation_hash != evaluation.validation_hash):
        raise _reject(db, code=ReasonCode.CCX_VALIDATION_HASH_MISMATCH,
                      blockers=(ReasonCode.CCX_VALIDATION_HASH_MISMATCH.value,),
                      message="Die Daten haben sich seit der Pruefung geaendert. Bitte neu laden.", **common)
    mode = approval_mode_for(
        db, tenant_id=evaluation.tenant_id, approver_id=str(user.id), preparer_id=evaluation.sealed_by,
        single_approver_attestation=single_approver_attestation, attestation_reason=attestation_reason,
    )
    approval = APPROVAL_APPROVED if mode is not None else "PENDING"
    if not is_publishable(evaluation.validation_status, approval):
        raise _reject(db, code=ReasonCode.CCX_APPROVAL_BINDING_MISSING,
                      blockers=(ReasonCode.FOUR_EYES_REQUIRED.value,),
                      message="Vier-Augen-Prinzip: die Freigabe muss eine zweite Person erteilen.", **common)
    now = _now()
    sequence = _next_sequence(db, evaluation.mandate_id)
    decision = AllocationPublicationDecision(
        id=new_uuid(), tenant_id=evaluation.tenant_id, mandate_id=evaluation.mandate_id,
        schema_version=ALLOCATION_PUBLICATION_SCHEMA_VERSION, envelope_id=evaluation.envelope_id,
        target_allocation_id=evaluation.target_allocation_id, publication_sequence=sequence,
        validation_hash=evaluation.validation_hash,
        approval_hash=approval_hash_for(
            tenant_id=evaluation.tenant_id, mandate_id=evaluation.mandate_id, publication_sequence=sequence,
            validation_hash=evaluation.validation_hash, envelope_id=evaluation.envelope_id,
            envelope_hash=evaluation.envelope_hash, target_allocation_id=evaluation.target_allocation_id,
            approved_by=str(user.id), approved_at=now, approval_mode=mode,
        ),
        approval_mode=mode, approved_at=now, approved_by=str(user.id), publishable=1,
        blocker_codes_json="[]", published_envelope_hash=evaluation.envelope_hash,
        created_at=now, created_by=str(user.id),
    )
    try:
        db.add(decision)
        db.flush()
        pointer = _active_pointer(db, evaluation.tenant_id, evaluation.mandate_id)
        expected_version = (evaluation.record.get("active_publication") or {}).get("version")
        if pointer is None:
            if expected_version is not None:
                raise IntegrityError("pointer vanished", None, Exception("CCX_PUBLICATION_RACE"))
            db.add(AllocationActivePublication(
                id=new_uuid(), tenant_id=evaluation.tenant_id, mandate_id=evaluation.mandate_id,
                publication_id=decision.id, optimistic_version=1, updated_at=now, updated_by=str(user.id),
            ))
        else:
            moved = db.query(AllocationActivePublication).filter(
                AllocationActivePublication.id == pointer.id,
                AllocationActivePublication.optimistic_version == int(expected_version or -1),
            ).update({
                "publication_id": decision.id, "optimistic_version": int(expected_version or 0) + 1,
                "updated_at": now, "updated_by": str(user.id),
            }, synchronize_session=False)
            if moved != 1:
                raise IntegrityError("pointer moved", None, Exception("CCX_PUBLICATION_RACE"))
        db.flush()
        _audit(db, user=user, mandate=mandate, tenant_id=evaluation.tenant_id, ip_address=ip_address,
               field_name=AUDIT_PUBLISHED, record_id=decision.id, publication_sequence=sequence,
               target_allocation=evaluation.target_allocation_id, envelope_hash=evaluation.envelope_hash,
               validation_hash=evaluation.validation_hash, approval_hash=decision.approval_hash,
               approval_mode=mode, approval_label=approval_mode_label(mode),
               attestation_reason=((attestation_reason or "").strip() or None)
               if mode == APPROVAL_MODE_SINGLE_APPROVER_ATTESTED else None)
        db.commit()
    except IntegrityError as exc:
        logger.info("CCX-P4: Publikation verloren | mandate=%s: %s", evaluation.mandate_id, exc)
        if is_check_constraint_violation(exc):
            # F1: eine CHECK-Verletzung ist kein Wettlauf, sondern ein nicht
            # publizierbarer Datensatz (422, Audit).
            raise _reject(db, code=ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE,
                          blockers=(ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE.value,), http_status=422,
                          message="Die Publikation verletzt eine Datenbankregel.", **common) from exc
        raise _reject(db, code=ReasonCode.CCX_PUBLICATION_RACE, blockers=(ReasonCode.CCX_PUBLICATION_RACE.value,),
                      message="Die Soll-Allokation wurde parallel publiziert. Bitte neu laden.", **common) from exc
    db.refresh(decision)
    return decision


# ── Lesen: nur der publizierte Stand ──────────────────────────────────────────


@dataclass(frozen=True)
class PublicationState:
    status: str
    reason_code: str | None = None
    publication_id: str | None = None
    publication_sequence: int | None = None
    target_allocation_id: str | None = None
    envelope_id: str | None = None
    published_envelope_hash: str | None = None
    validation_hash: str | None = None
    approval_hash: str | None = None
    approved_at: str | None = None
    approved_by: str | None = None
    approval_mode: str | None = None
    drift: tuple = field(default=(), repr=False, compare=False)

    @property
    def published(self) -> bool:
        return self.status == STATUS_PUBLISHED

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "reason_code": self.reason_code, "publication_id": self.publication_id,
            "publication_sequence": self.publication_sequence, "target_allocation_id": self.target_allocation_id,
            "envelope_id": self.envelope_id, "published_envelope_hash": self.published_envelope_hash,
            "validation_hash": self.validation_hash, "approval_hash": self.approval_hash,
            "approved_at": self.approved_at, "approved_by": self.approved_by, "approval_mode": self.approval_mode,
            "approval_mode_label": approval_mode_label(self.approval_mode),
        }


def _decision_state(decision: AllocationPublicationDecision, status: str, code: Any = None, drift=()) -> PublicationState:
    return PublicationState(
        status=status, reason_code=None if code is None else str(code), publication_id=decision.id,
        publication_sequence=int(decision.publication_sequence), target_allocation_id=decision.target_allocation_id,
        envelope_id=decision.envelope_id, published_envelope_hash=decision.published_envelope_hash,
        validation_hash=decision.validation_hash, approval_hash=decision.approval_hash,
        approved_at=decision.approved_at, approved_by=decision.approved_by, approval_mode=decision.approval_mode,
        drift=tuple(drift),
    )


def active_publication_state(db: Session, mandate: Any, *, deep: bool = True) -> PublicationState:
    """Aktive Publikation des Mandats, vor jeder Verwendung neu geprueft.

    ``deep`` (Default, kundenwirksame Kanaele): Integritaet und Frische des
    Envelopes inkl. Pull-Pruefung der Kanten. ``deep=False`` (nur Anzeige im
    Arbeitsstand): gespeicherter Status ohne Pull -- nie Grundlage einer
    Kundenwirkung."""
    tenant_id = mandate_tenant(mandate)
    if tenant_id is None:
        return PublicationState(STATUS_DRAFT, ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE.value)
    pointer = _active_pointer(db, tenant_id, str(mandate.id))
    if pointer is None:
        return PublicationState(STATUS_DRAFT, ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE.value)
    decision = _decision(db, tenant_id, pointer.publication_id)
    if decision is None or int(decision.publishable or 0) != 1:
        return PublicationState(STATUS_PUBLICATION_INVALID, ReasonCode.CCX_APPROVAL_BINDING_MISSING.value)
    expected_approval = approval_hash_for(
        tenant_id=decision.tenant_id, mandate_id=decision.mandate_id,
        publication_sequence=int(decision.publication_sequence), validation_hash=decision.validation_hash,
        envelope_id=str(decision.envelope_id), envelope_hash=str(decision.published_envelope_hash),
        target_allocation_id=str(decision.target_allocation_id), approved_by=str(decision.approved_by),
        approved_at=str(decision.approved_at), approval_mode=str(decision.approval_mode),
    ) if decision.approved_by and decision.approved_at and decision.approval_mode else None
    if expected_approval is None or expected_approval != decision.approval_hash \
            or not is_publishable(VALIDATION_PASS, APPROVAL_APPROVED if expected_approval else None):
        return _decision_state(decision, STATUS_PUBLICATION_INVALID, ReasonCode.CCX_APPROVAL_BINDING_MISSING)
    envelope = db.query(AdvisoryDecisionEnvelope).filter(
        AdvisoryDecisionEnvelope.tenant_id == tenant_id,
        AdvisoryDecisionEnvelope.id == str(decision.envelope_id),
    ).first()
    if envelope is None:
        return _decision_state(decision, STATUS_PUBLICATION_INVALID, ReasonCode.CCX_ENVELOPE_MISSING)
    if envelope.status != "SEALED":
        return _decision_state(decision, STATUS_PUBLICATION_INVALID, ReasonCode.CCX_RESULT_SUPERSEDED)
    if envelope.envelope_hash != decision.published_envelope_hash:
        return _decision_state(decision, STATUS_PUBLICATION_INVALID, ReasonCode.CCX_ENVELOPE_HASH_MISMATCH)
    try:
        current = current_target_allocation(db, str(mandate.id))
    except ValueError:
        current = None
    if current is None or str(current.id) != str(decision.target_allocation_id):
        return _decision_state(decision, STATUS_PUBLICATION_INVALID, ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE)
    if not deep:
        if envelope.freshness_status != "FRESH":
            return _decision_state(decision, STATUS_PUBLICATION_INVALID, ReasonCode.CCX_INPUT_STALE
                                   if envelope.freshness_status == "STALE" else ReasonCode.CCX_FRESHNESS_UNKNOWN)
        return _decision_state(decision, STATUS_PUBLISHED)
    defect = verify_envelope(db, envelope)
    if defect is not None:
        return _decision_state(decision, STATUS_PUBLICATION_INVALID, ReasonCode.CCX_ENVELOPE_HASH_MISMATCH)
    code, _detail, drift = pull_freshness(db, envelope, mandate=mandate)
    if code is not None:
        return _decision_state(decision, STATUS_PUBLICATION_INVALID, code, drift)
    return _decision_state(decision, STATUS_PUBLISHED)


def allocation_publication_status(state: PublicationState, target_allocation_id: Any) -> str:
    """Anzeige-Status einer Soll-Allokation: nur die gueltig publizierte ist
    ``PUBLISHED``; eine publizierte, aber nicht mehr gueltige
    ``PUBLICATION_INVALID``; alles andere ist ``DRAFT``."""
    if state.target_allocation_id is None or str(state.target_allocation_id) != str(target_allocation_id or ""):
        return STATUS_DRAFT
    return state.status if state.status in (STATUS_PUBLISHED, STATUS_PUBLICATION_INVALID) else STATUS_DRAFT


_SNAPSHOT_BUCKETS = {
    "equities": "equities", "bonds": "bonds", "real_estate": "real_estate",
    "liquidity": "liquidity", "alternatives": "alternatives",
}


def published_allocation_matches_snapshot(db: Session, state: PublicationState, body: Any) -> bool:
    """"Portfolio umsetzen": Quoten und Baender des Snapshots muessen exakt die
    der publizierten Soll-Allokation sein (bps, Integer)."""
    ta = db.query(TargetAllocation).filter(TargetAllocation.id == str(state.target_allocation_id or "")).first()
    if ta is None:
        return False
    for snap_key, bucket in _SNAPSHOT_BUCKETS.items():
        if int(getattr(body, f"soll_{snap_key}_bps")) != int(getattr(ta, f"target_{bucket}_bps") or 0):
            return False
        lo, hi = getattr(body, f"band_{snap_key}_lo_bps"), getattr(body, f"band_{snap_key}_hi_bps")
        if lo is not None and int(lo) != int(getattr(ta, f"band_{bucket}_min_bps")):
            return False
        if hi is not None and int(hi) != int(getattr(ta, f"band_{bucket}_max_bps")):
            return False
    return True


UNPUBLISHED_WATERMARK = "unpublished"


def customer_document_watermark(db: Session, mandate: Any) -> str | None:
    """Kunden-PDF mit Soll-Allokation: ``None`` (final) nur, wenn es keine
    aktuelle Soll-Allokation gibt oder genau sie gueltig publiziert ist (tiefe
    Pruefung). Sonst ``"unpublished"`` -- Entwurf, nie archiviert."""
    try:
        current = current_target_allocation(db, str(mandate.id))
    except ValueError:
        return UNPUBLISHED_WATERMARK
    if current is None:
        return None
    state = active_publication_state(db, mandate)
    if state.published and str(state.target_allocation_id) == str(current.id):
        return None
    return UNPUBLISHED_WATERMARK


def require_published_allocation(
    db: Session, mandate: Any, *, channel: str, user: Any, ip_address: str | None = None,
) -> PublicationState:
    """Gate fuer kundenwirksame Kanaele (Handoff, "Portfolio umsetzen"): nur
    eine gueltig publizierte, frische Soll-Allokation. Sonst Reason-Code
    ``CCX_ALLOCATION_NOT_PUBLISHABLE`` (Ursache in ``blocker_code``) und
    Audit ``ccx.allocation.channel_blocked`` -- kein Fallback."""
    state = active_publication_state(db, mandate)
    if state.published:
        return state
    tenant_id = mandate_tenant(mandate)
    rollback_keeping_tenant(db)
    if state.drift and state.envelope_id:
        envelope = db.get(AdvisoryDecisionEnvelope, state.envelope_id)
        if envelope is not None:
            persist_freshness_drift(db, envelope, list(state.drift), user)
    _audit(db, user=user, mandate=mandate, tenant_id=tenant_id, ip_address=ip_address,
           field_name=AUDIT_CHANNEL_BLOCKED, record_id=state.publication_id or str(mandate.id),
           reason_code=ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE.value, blocker_code=state.reason_code,
           channel=channel, publication_status=state.status)
    db.commit()
    raise DomainError(
        ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE,
        "Die Soll-Allokation ist nicht publiziert (oder die Publikation ist nicht mehr gueltig). "
        "Bitte zuerst finalisieren und publizieren.",
        http_status=409,
        extra={"channel": channel, "blocker_code": state.reason_code, "publication_status": state.status},
    )


def publication_overview(db: Session, mandate: Any) -> dict[str, Any]:
    """Status fuer die Masken: aktive Publikation (tief geprueft) und die
    Pruefung der aktuellen Soll-Allokation. ``can_publish`` nur, wenn alle
    Pruefungen gruen sind (Owner-UX: nur Erfuellbares anbieten)."""
    state = active_publication_state(db, mandate)
    evaluation = evaluate_allocation_publication(db, mandate)
    current_status = allocation_publication_status(state, evaluation.target_allocation_id)
    return {
        "mandate_id": str(mandate.id),
        "target_allocation_id": evaluation.target_allocation_id,
        "envelope_id": evaluation.envelope_id,
        "envelope_hash": evaluation.envelope_hash,
        "publication_status": current_status,
        "validation_status": evaluation.validation_status,
        "validation_hash": evaluation.validation_hash,
        "blocker_codes": list(evaluation.blockers),
        "can_publish": not evaluation.blockers and not evaluation.already_published,
        "already_published": evaluation.already_published,
        "prepared_by": evaluation.sealed_by,
        "active_publication": state.as_dict(),
    }


__all__ = [
    "AllocationVersionConflict", "UNPUBLISHED_WATERMARK", "assert_report_allocation_matches",
    "customer_document_watermark", "published_allocation_matches_snapshot",
    "APPROVAL_APPROVED", "STATUS_DRAFT", "STATUS_PUBLICATION_INVALID", "STATUS_PUBLISHED",
    "VALIDATION_PASS", "VALIDATION_REJECTED", "PublicationEvaluation", "PublicationState",
    "active_publication_state", "allocation_publication_status", "approval_hash_for", "approval_mode_for",
    "current_target_allocation", "evaluate_allocation_publication", "is_publishable", "publication_overview",
    "publish_allocation", "require_published_allocation", "validation_hash_for",
]
