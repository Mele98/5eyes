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

import hashlib
import json
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session

from core.evidence import SCHEME_V1, advisory_domain, canonical_json, domain_sha256_hex
from core.reason_codes import DomainError, ReasonCode
from core.db_integrity import is_check_constraint_violation
from core.goal_metric_contract import GOAL_METRIC_CONTRACT_VERSION, GoalMetricUncertified
from core.risk_parameter_set import PARAMETER_CONTRACT_VERSION, ParameterSetMissing, stored_risk_parameter_set
from database import CHANNEL_PUBLICATION_SCHEMA, new_uuid
from models.allocation import TargetAllocation
from models.review import RecommendationRun
from models.snapshots import (
    ALLOCATION_PUBLICATION_SCHEMA_VERSION,
    AdvisoryChannelPublication,
    AdvisoryDecisionEnvelope,
    AdvisoryDependencyEdge,
    AdvisoryEnvelopeBinding,
    AllocationActivePublication,
    AllocationPublicationDecision,
    HoldingsValuationSnapshot,
)
import services.advisory_decision_envelope as _ade
import services.recommendation_release_gate as release_gate
from services.advisory_decision_envelope import (
    GOAL_METRIC_BINDING_KIND,
    PARAMETER_SET_BINDING_KIND,
    VALUATION_BINDING_KIND,
    utc_now,
    current_sealed_envelope,
    lock_mandate_row,
    mandate_tenant,
    persist_freshness_drift,
    pull_freshness,
    reapply_tenant_context,
    rollback_keeping_tenant,
    verify_envelope,
)
# ALLOC-EDITOR-STALE-001: der Browser-Kontext-Abgleich der Strategie-PDFs
# (Vertrags-Consumer) laeuft ueber diese Fassade mit (pdf_reports ohne neue Kante).
from services.allocation_concurrency import AllocationVersionConflict, assert_report_allocation_matches
from services.audit import log
from services.fx_basis import STATUS_MISMATCH, STATUS_OK, STATUS_STALE, load_fx_basis
from services.portfolio_engine_allocation_integrity import (
    _verified_persisted_allocation_context,
    analysis_integrity_report,
)
# N-910-02/-05: Freigabemodus (Ein-Personen-Firma nur per Konfiguration) und
# HMAC-Approval-Binding leben im eigenen Modul.
from services.allocation_publication_approval import (
    APPROVAL_MODE_FOUR_EYES,
    APPROVAL_MODE_LABELS,
    APPROVAL_MODE_SINGLE_APPROVER_ATTESTED,
    MIN_ATTESTATION_REASON_LENGTH,
    PUBLICATION_APPROVER_ROLES,
    SINGLE_APPROVER_LABEL,
    ApprovalBasis,
    ApprovalKeyUnavailable,
    approval_basis,
    approval_hash_for,
    approval_mode_label,
    current_approval_key_version,
)
from services.recommendation_release_gate import (
    CHANNEL_PUBLICATION,
    RECOMMENDATION_DOCUMENT_TYPES,
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
# Meldung des Insert-Triggers (SQLite RAISE / PG RAISE EXCEPTION), wenn der
# Envelope beim Insert nicht mehr SEALED + FRESH ist.
INSERT_STALE_MARKER = "CCX_ALLOCATION_NOT_PUBLISHABLE"
# H12 N-910-16: erkennbare Meldungen der Publikations-Guards (SQLite RAISE /
# PG RAISE EXCEPTION). Ein IntegrityError ist immer ein Domaenenfehler; jeder
# andere DB-Fehler (PG RAISE EXCEPTION erscheint je nach Treiber als
# InternalError oder ProgrammingError, psycopg 3: ProgrammingError) nur mit einer
# dieser Meldungen -- sonst bleibt er ein technischer Fehler.
PUBLICATION_GUARD_MARKERS: tuple[str, ...] = (
    INSERT_STALE_MARKER,
    "CCX_PUBLICATION_RACE",
    "is append-only",
    "pointer is never deleted",
    "MANDATE_EVIDENCE_TENANT_MISMATCH",
)

# P5c: Meldung des Nummern-Triggers der Kanalzeilen (P5b, SQLite RAISE / PG).
CHANNEL_SEQUENCE_RACE_MARKER = "CCX_CHANNEL_SEQUENCE_RACE"
# N-933-05: Erkennungsmerkmale der Nummern-Verletzung -- Trigger-Meldung,
# Unique-Index (PostgreSQL nennt den Namen, SQLite die Spalten).
CHANNEL_SEQUENCE_RACE_MARKERS = (
    CHANNEL_SEQUENCE_RACE_MARKER,
    "ux_advisory_channel_publications_sequence",
)
# KN9 / N-933R-03: SQLite nennt beim Unique-Index nur die Spalten. Die Spalte
# allein reicht nicht (auch «NOT NULL constraint failed: …channel_sequence»
# enthaelt sie); gezaehlt wird sie nur in der Unique-Meldung.
SQLITE_UNIQUE_PREFIX = "UNIQUE constraint failed:"
SQLITE_SEQUENCE_COLUMN = "advisory_channel_publications.channel_sequence"


def is_channel_sequence_race(exc: BaseException) -> bool:
    """True nur fuer die Verletzung der laufenden Kanalnummer (Unique/Trigger)."""
    message = str(getattr(exc, "orig", None) or exc)
    if any(marker in message for marker in CHANNEL_SEQUENCE_RACE_MARKERS):
        return True
    return message.lstrip().startswith(SQLITE_UNIQUE_PREFIX) and SQLITE_SEQUENCE_COLUMN in message

BUCKETS: tuple[str, ...] = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
TOTAL_BPS = 10_000
# Wirksame Bindungen, ohne die keine Strategie kundenwirksam wird (P2-Kanten).
REQUIRED_EDGE_KINDS: tuple[str, ...] = ("risk", "cma", "optimizer_policy", "constraints")

_VALIDATION_DOMAIN = advisory_domain("allocation-publication-validation")

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
    gebundene Basis selbst bleibt unveraendert (kein Nachrechnen).

    CCX P5 / N-925-01: zusaetzlich muss der heutige Kurs jeder gebundenen
    Waehrung GLEICH dem versiegelten ``rate_x10000`` sein. Ein neuer, frischer
    Kurs mit anderem Wert (USD 0.88 -> 0.93) macht den Entscheid nicht mehr
    auslieferbar (``CCX_FX_BASIS_CHANGED``) -- in Publikation, PDF, Signatur und
    Handoff gleich. Ein Kurs einer nicht gebundenen Waehrung wirkt nicht."""
    try:
        basis = json.loads(snapshot.fx_basis_json or "")
    except (TypeError, ValueError):
        return []  # bereits von _fx_basis_findings gesperrt
    statuses = basis.get("statuses") if isinstance(basis, dict) else None
    if not isinstance(statuses, dict) or not statuses:
        return []  # nur Basiswaehrung im Spiel: kein Kurs noetig
    currencies = sorted(str(c) for c in statuses)
    current = load_fx_basis(db, basis.get("target_currency") or "CHF", currencies, tenant_id=tenant_id)
    bound_rates = {
        str(q.get("currency") or "").upper(): q.get("rate_x10000")
        for q in (basis.get("quotes") or []) if isinstance(q, dict)
    }
    findings: list[str] = []
    for currency in currencies:
        status = current.statuses.get(currency)
        if status == STATUS_OK:
            quote = current.quote(currency)
            bound = bound_rates.get(str(currency).upper())
            if quote is not None and bound is not None and int(quote.rate_x10000) != int(bound):
                findings.append(_finding(reason_code=ReasonCode.CCX_FX_BASIS_CHANGED))
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
    """Freigabemodus (``None`` = nicht freigegeben); Regeln siehe
    ``services.allocation_publication_approval.approval_basis``."""
    return approval_basis(
        db, tenant_id=tenant_id, approver_id=approver_id, preparer_id=preparer_id,
        single_approver_attestation=single_approver_attestation, attestation_reason=attestation_reason,
    ).mode


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


def _retryable_reject(db: Session, common: dict) -> DomainError:
    """H12 N-910-16: ``CCX_PUBLICATION_RETRYABLE`` (503, ``retryable``). Der
    abgelehnte Versuch wird wie jeder andere festgehalten, soweit die DB das
    zulaesst; scheitert auch das technisch, bleibt es beim Fehler ohne Spur in
    der DB (Log beim Aufrufer)."""
    code = ReasonCode.CCX_PUBLICATION_RETRYABLE
    message = ("Die Publikation wurde technisch unterbrochen (Datenbank voruebergehend nicht "
               "verfuegbar). Bitte erneut versuchen.")
    try:
        err = _reject(db, code=code, blockers=(code.value,), message=message, http_status=503, **common)
    except OperationalError:
        try:
            db.rollback()
        except Exception:  # noqa: BLE001 - Verbindung bereits verloren
            pass
        err = DomainError(code, message, http_status=503, extra={
            "channel": CHANNEL_PUBLICATION, "blocker_codes": [code.value],
            "validation_hash": common["evaluation"].validation_hash,
        })
    err.extra["retryable"] = True
    return err


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
    basis: ApprovalBasis = approval_basis(
        db, tenant_id=evaluation.tenant_id, approver_id=str(user.id), preparer_id=evaluation.sealed_by,
        single_approver_attestation=single_approver_attestation, attestation_reason=attestation_reason,
    )
    mode = basis.mode
    approval = APPROVAL_APPROVED if mode is not None else "PENDING"
    if not is_publishable(evaluation.validation_status, approval):
        raise _reject(db, code=ReasonCode.CCX_APPROVAL_BINDING_MISSING,
                      blockers=(ReasonCode.FOUR_EYES_REQUIRED.value,),
                      message="Vier-Augen-Prinzip: die Freigabe muss eine zweite Person erteilen.", **common)
    now = _now()
    sequence = _next_sequence(db, evaluation.mandate_id)
    try:
        key_version = current_approval_key_version(db, evaluation.tenant_id)  # H12 N-910-14
        approval_hash = approval_hash_for(
            db, tenant_id=evaluation.tenant_id, mandate_id=evaluation.mandate_id, publication_sequence=sequence,
            validation_hash=evaluation.validation_hash, envelope_id=evaluation.envelope_id,
            envelope_hash=evaluation.envelope_hash, target_allocation_id=evaluation.target_allocation_id,
            approved_by=str(user.id), approved_at=now, approval_mode=mode,
            eligible_approver_count=basis.eligible_approver_count, single_person_firm=basis.single_person_firm,
            approval_key_version=key_version,
        )
    except ApprovalKeyUnavailable as exc:
        raise _reject(db, code=ReasonCode.CCX_APPROVAL_BINDING_MISSING,
                      blockers=(ReasonCode.CCX_APPROVAL_BINDING_MISSING.value,),
                      message="Die Freigabe kann ohne Mandantenschluessel nicht gebunden werden.",
                      **common) from exc
    decision = AllocationPublicationDecision(
        id=new_uuid(), tenant_id=evaluation.tenant_id, mandate_id=evaluation.mandate_id,
        schema_version=ALLOCATION_PUBLICATION_SCHEMA_VERSION, envelope_id=evaluation.envelope_id,
        target_allocation_id=evaluation.target_allocation_id, publication_sequence=sequence,
        validation_hash=evaluation.validation_hash, approval_hash=approval_hash,
        approval_mode=mode, approved_at=now, approved_by=str(user.id), publishable=1,
        blocker_codes_json="[]", published_envelope_hash=evaluation.envelope_hash,
        created_at=now, created_by=str(user.id),
        eligible_approver_count=basis.eligible_approver_count, single_person_firm=basis.single_person_firm,
        approval_key_version=key_version,
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
               eligible_approver_count=basis.eligible_approver_count,
               single_person_firm=basis.single_person_firm,
               attestation_reason=((attestation_reason or "").strip() or None)
               if mode == APPROVAL_MODE_SINGLE_APPROVER_ATTESTED else None,
               approval_key_version=key_version)
        db.commit()
    except OperationalError as exc:
        # H12 N-910-16: Lock-Timeout, Verbindungsabbruch, "database is locked" --
        # kein Wettlauf und kein Datenfehler, sondern ein voruebergehender
        # technischer Fehler: eigener, wiederholbarer Code (nichts publiziert).
        logger.warning("CCX-P4: Publikation technisch abgebrochen (retryable) | mandate=%s: %s",
                       evaluation.mandate_id, type(getattr(exc, "orig", None) or exc).__name__)
        raise _retryable_reject(db, common) from exc
    except DBAPIError as exc:  # OperationalError oben abgefangen
        message = str(getattr(exc, "orig", None) or exc)
        if not isinstance(exc, IntegrityError) and not any(marker in message for marker in PUBLICATION_GUARD_MARKERS):
            raise  # H12 N-910-16: kein Guard-Text -> technischer Fehler, nicht als Wettlauf maskieren
        logger.info("CCX-P4: Publikation verloren | mandate=%s: %s", evaluation.mandate_id, exc)
        if INSERT_STALE_MARKER in message:
            # N-910-04: der Insert-Trigger fand den Envelope nicht mehr SEALED
            # + FRESH -- eine parallele Invalidierung hat gewonnen (kein
            # paralleler Publisher). Fail-closed mit dem praezisen Code.
            raise _reject(db, code=ReasonCode.CCX_INPUT_STALE, blockers=(ReasonCode.CCX_INPUT_STALE.value,),
                          message="Die Beratungsdaten wurden parallel geaendert. Bitte neu finalisieren.",
                          **common) from exc
        if is_check_constraint_violation(exc):
            # F1: eine CHECK-Verletzung ist kein Wettlauf, sondern ein nicht
            # publizierbarer Datensatz (422, Audit).
            raise _reject(db, code=ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE,
                          blockers=(ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE.value,), http_status=422,
                          message="Die Publikation verletzt eine Datenbankregel.", **common) from exc
        raise _reject(db, code=ReasonCode.CCX_PUBLICATION_RACE, blockers=(ReasonCode.CCX_PUBLICATION_RACE.value,),
                      message="Die Soll-Allokation wurde parallel publiziert. Bitte neu laden.", **common) from exc
    # PostgreSQL: nach dem Commit kehrt die Verbindung in den Pool zurueck und
    # verliert den Mandantenkontext (attach_tenant_context_reset); ohne ihn
    # saehe das Nachladen unter FORCE RLS die eigene Zeile nicht.
    reapply_tenant_context(db)
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
    # N-910-02: Basis der Freigabe (Nachweis).
    eligible_approver_count: int | None = None
    single_person_firm: int | None = None
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
            "eligible_approver_count": self.eligible_approver_count,
            "single_person_firm": self.single_person_firm,
        }


def _decision_state(decision: AllocationPublicationDecision, status: str, code: Any = None, drift=()) -> PublicationState:
    return PublicationState(
        status=status, reason_code=None if code is None else str(code), publication_id=decision.id,
        publication_sequence=int(decision.publication_sequence), target_allocation_id=decision.target_allocation_id,
        envelope_id=decision.envelope_id, published_envelope_hash=decision.published_envelope_hash,
        validation_hash=decision.validation_hash, approval_hash=decision.approval_hash,
        approved_at=decision.approved_at, approved_by=decision.approved_by, approval_mode=decision.approval_mode,
        eligible_approver_count=decision.eligible_approver_count, single_person_firm=decision.single_person_firm,
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
    # H12 N-910-14: Schluesselversion VOR der Hash-Pruefung (erkennbare Ursache
    # statt eines stummen Hash-Fehlers nach einer DEK-Rotation).
    stored_key_version = getattr(decision, "approval_key_version", None)
    if stored_key_version is None:
        return _decision_state(decision, STATUS_PUBLICATION_INVALID, ReasonCode.CCX_APPROVAL_KEY_VERSION_MISSING)
    try:
        key_version = current_approval_key_version(db, decision.tenant_id)
    except ApprovalKeyUnavailable:
        return _decision_state(decision, STATUS_PUBLICATION_INVALID, ReasonCode.CCX_APPROVAL_BINDING_MISSING)
    if int(stored_key_version) != key_version:
        return _decision_state(decision, STATUS_PUBLICATION_INVALID, ReasonCode.CCX_APPROVAL_KEY_ROTATED)
    expected_approval = None
    if decision.approved_by and decision.approved_at and decision.approval_mode \
            and decision.eligible_approver_count is not None and decision.single_person_firm is not None:
        try:
            expected_approval = approval_hash_for(
                db, tenant_id=decision.tenant_id, mandate_id=decision.mandate_id,
                publication_sequence=int(decision.publication_sequence), validation_hash=decision.validation_hash,
                envelope_id=str(decision.envelope_id), envelope_hash=str(decision.published_envelope_hash),
                target_allocation_id=str(decision.target_allocation_id), approved_by=str(decision.approved_by),
                approved_at=str(decision.approved_at), approval_mode=str(decision.approval_mode),
                eligible_approver_count=int(decision.eligible_approver_count),
                single_person_firm=int(decision.single_person_firm),
                approval_key_version=int(stored_key_version),
            )
        except ApprovalKeyUnavailable:
            expected_approval = None  # fail-closed: ohne Schluessel keine gueltige Freigabe
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


def publication_inbox_envelopes(db: Session, tenant_id: str | None) -> list[AdvisoryDecisionEnvelope]:
    """ROL-05 (CTO-Entscheid H-180): die zur Freigabe vorgelegten Akten des
    Mandanten -- versiegelte Beratungsentscheide (finalisiert), auf die noch
    keine aktive Publikation zeigt. Ohne Mandant: keine (fail-closed)."""
    if not tenant_id:
        return []
    envelopes = db.query(AdvisoryDecisionEnvelope).filter(
        AdvisoryDecisionEnvelope.tenant_id == str(tenant_id),
        AdvisoryDecisionEnvelope.status == "SEALED",
    ).order_by(AdvisoryDecisionEnvelope.sealed_at.asc()).all()
    pending: list[AdvisoryDecisionEnvelope] = []
    for envelope in envelopes:
        pointer = _active_pointer(db, str(tenant_id), envelope.mandate_id)
        active = _decision(db, str(tenant_id), pointer.publication_id) if pointer is not None else None
        if active is not None and active.envelope_id == envelope.id:
            continue
        pending.append(envelope)
    return pending


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



# ══ CCX P5: Kanal-Envelope (Vertrag 2026-11-13 §8) ═══════════════════════════
# Jede kundengerichtete Zahl (Kunden-PDF, Signatur, Vor-Ort-Signatur, Handoff)
# kommt aus genau EINEM versiegelten Envelope. Ein Kanal liefert nur aus, wenn
# (1) die aktuelle Soll-Allokation gueltig publiziert ist (P4 tief: SEALED,
# Hash, Integritaet, P2-Frische), (2) die FX-Basis des gebundenen Bewertungs-
# Snapshots JETZT noch belegt und frisch ist (§8.3: keine Ausnahme fuer ein
# Live-Neurendern), (3) der Envelope Parametersatz (M-2) und Zielkennzahl (M-3)
# bindet und beide Hashes heute aus der Soll-Allokation reproduzierbar sind.
# Sonst 409 mit katalogisiertem Code, Ursache und Audit ``ccx.channel.blocked``.
# Hier im P4-Gate, weil alle Kanal-Router ihn bereits verwenden
# (Architektur-Ratsche: keine neuen Modulkanten); die Signatur-Router erreichen
# ihn ueber ``services.recommendation_release_gate`` (Hook, unten registriert).

CHANNEL_API = "API"
CHANNEL_PDF = "PDF"
CHANNEL_ADVISOR_SIGNATURE = "ADVISOR_SIGNATURE"
CHANNEL_ONSITE_SIGNATURE = "ONSITE_SIGNATURE"
CHANNEL_HANDOFF = "HANDOFF"
CHANNEL_ARCHIVE = "ARCHIVE"
CHANNELS = ("API", "CLASSIC", "REACT", "PDF", "ADVISOR_SIGNATURE", "ONSITE_SIGNATURE", "HANDOFF", "ARCHIVE")
P5_AUDIT_CHANNEL_BLOCKED = "ccx.channel.blocked"
CHANNEL_STATUS_PUBLISHED = "PUBLISHED"

_CHANNEL_CAUSES: dict[str, str] = {
    ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE.value:
        "Die aktuelle Soll-Allokation ist nicht als Beratungsentscheid publiziert. Bitte finalisieren und publizieren.",
    ReasonCode.CCX_INPUT_STALE.value:
        "Beratungsdaten wurden seit der Versiegelung geändert. Bitte neu berechnen, finalisieren und publizieren.",
    ReasonCode.CCX_FRESHNESS_UNKNOWN.value:
        "Die Aktualität des Beratungsentscheids ist nicht belegt. Bitte neu finalisieren.",
    ReasonCode.CCX_ENVELOPE_MISSING.value:
        "Der versiegelte Beratungsentscheid ist nicht auffindbar. Bitte neu finalisieren und publizieren.",
    ReasonCode.CCX_FX_BASIS_STALE.value:
        "Ein Wechselkurs des versiegelten Entscheids ist veraltet. Bitte einen aktuellen Kurs erfassen.",
    ReasonCode.CCX_FX_BASIS_MISSING.value:
        "Für eine Währung des versiegelten Entscheids fehlt ein belegter Wechselkurs. Bitte einen Kurs erfassen.",
    ReasonCode.CCX_FX_BASIS_MISMATCH.value:
        "Der Wechselkurs liegt nach dem Stichtag des Entscheids. Bitte neu finalisieren.",
    ReasonCode.CCX_FX_BASIS_CHANGED.value:
        "Ein Wechselkurs einer gebundenen Währung hat sich seit der Versiegelung geändert. Bitte neu "
        "berechnen, finalisieren und publizieren.",
    ReasonCode.CCX_CHANNEL_BINDING_MISSING.value:
        "Der Beratungsentscheid bindet keinen Risikoparametersatz bzw. keine Zielkennzahl (vor der "
        "Kanal-Bindung versiegelt). Bitte neu finalisieren und publizieren.",
    ReasonCode.CCX_CHANNEL_HASH_MISMATCH.value:
        "Der Risikoparametersatz der Soll-Allokation entspricht nicht mehr dem versiegelten Entscheid.",
    ReasonCode.CCX_GOAL_METRIC_MISMATCH.value:
        "Die Zielkennzahl der Soll-Allokation entspricht nicht mehr dem versiegelten Entscheid.",
    ReasonCode.CCX_PARAMETER_SET_MISSING.value:
        "Es fehlt ein gültiger, freigegebener Risikoparametersatz.",
    ReasonCode.CCX_GOAL_METRIC_UNCERTIFIED.value:
        "Für mindestens ein Ziel fehlt eine zertifizierte Erfolgswahrscheinlichkeit.",
}
_FX_CODES = {ReasonCode.CCX_FX_BASIS_STALE.value, ReasonCode.CCX_FX_BASIS_MISSING.value,
             ReasonCode.CCX_FX_BASIS_MISMATCH.value, ReasonCode.CCX_FX_BASIS_CHANGED.value}


@dataclass(frozen=True)
class ChannelDecision:
    """Ergebnis des Kanal-Gates (``applicable`` False: keine Soll-Allokation)."""

    applicable: bool
    reason_code: str | None = None
    envelope_id: str | None = None
    envelope_hash: str | None = None
    schema_version: str | None = None
    rounding_policy_version: str | None = None
    target_allocation_id: str | None = None
    parameter_set_hash: str | None = None
    goal_metric_payload_hash: str | None = None
    ic_release_status: str | None = None
    # N-925R-02: ein Entscheid ist versiegelt (auch wenn nicht auslieferbar).
    sealed: bool = False
    # N-925-08: monotone Fassung = laufende Nummer der Versiegelung im Mandat.
    fassung: int | None = None
    drift: tuple = field(default=(), repr=False, compare=False)

    @property
    def ok(self) -> bool:
        return self.applicable and self.reason_code is None

    @property
    def cause(self) -> str:
        return _CHANNEL_CAUSES.get(str(self.reason_code or ""), "Der Beratungsentscheid ist nicht auslieferbar.")

    def footer_ref(self) -> dict[str, str] | None:
        """Envelope-Hash/Version fuer den Fuss jedes Kunden-PDFs; dazu der
        IC-Status des Risikoparametersatzes der Soll-Allokation (N-925-05)."""
        ic = {"ic_release_status": self.ic_release_status} if self.ic_release_status else {}
        if not self.ok:
            # N-925R-02: versiegelt, aber nicht auslieferbar != keiner versiegelt.
            state = {"decision_state": "sealed_not_deliverable"} if self.sealed else {}
            return {**ic, **state} or None
        return {"envelope_hash": str(self.envelope_hash), "schema_version": str(self.schema_version),
                "fassung": str(self.fassung or 1), **ic}


def _channel_blocked(code: Any, **kw: Any) -> ChannelDecision:
    return ChannelDecision(applicable=True, reason_code=str(getattr(code, "value", code)), **kw)


def evaluate_channel_envelope(db: Session, mandate: Any) -> ChannelDecision:
    """Kanal-Pruefung (siehe ``_evaluate_channel_envelope``) samt IC-Status
    des gespeicherten Risikoparametersatzes der aktuellen Soll-Allokation."""
    decision = _evaluate_channel_envelope(db, mandate)
    try:
        ta = current_target_allocation(db, str(mandate.id))
    except ValueError:
        ta = None
    record = stored_risk_parameter_set(ta) if ta is not None else None
    status = record.get("ic_release_status") if isinstance(record, dict) else None
    tenant_id = mandate_tenant(mandate)
    sealed = current_sealed_envelope(db, tenant_id, str(mandate.id)) if tenant_id else None
    own = db.get(AdvisoryDecisionEnvelope, str(decision.envelope_id)) if decision.envelope_id else None
    fassung = _envelope_fassung(db, own) if own is not None else None
    return replace(decision, ic_release_status=str(status) if status else None,
                   sealed=sealed is not None, fassung=fassung)


def _evaluate_channel_envelope(db: Session, mandate: Any) -> ChannelDecision:
    """Kanal-Pruefung ohne Schreibwirkung (Reihenfolge: P4, FX, P5-Bindung)."""
    try:
        ta = current_target_allocation(db, str(mandate.id))
    except ValueError:
        return _channel_blocked(ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE)
    if ta is None:
        return ChannelDecision(applicable=False)
    state = active_publication_state(db, mandate)
    if not state.published:
        code = state.reason_code or ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE
        if str(code) not in _CHANNEL_CAUSES:
            code = ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE
        return _channel_blocked(code, envelope_id=state.envelope_id, target_allocation_id=str(ta.id), drift=state.drift)
    envelope = db.get(AdvisoryDecisionEnvelope, str(state.envelope_id)) if state.envelope_id else None
    if envelope is None:
        # P5b-CI-Fix: publiziert ohne auffindbaren Entscheid -> typisiert
        # blockiert (nie AttributeError/500 in Anzeige- oder PDF-Pfaden).
        return _channel_blocked(ReasonCode.CCX_ENVELOPE_MISSING, envelope_id=state.envelope_id,
                                target_allocation_id=str(ta.id))
    base = {"envelope_id": envelope.id, "envelope_hash": envelope.envelope_hash,
            "schema_version": envelope.schema_version, "target_allocation_id": str(ta.id)}
    rows = db.query(AdvisoryEnvelopeBinding).filter(
        AdvisoryEnvelopeBinding.tenant_id == envelope.tenant_id,
        AdvisoryEnvelopeBinding.envelope_id == envelope.id,
    ).all()
    bindings = {row.binding_kind: row for row in rows}
    snapshot_row = bindings.get(VALUATION_BINDING_KIND)
    snapshot = db.query(HoldingsValuationSnapshot).filter(
        HoldingsValuationSnapshot.tenant_id == envelope.tenant_id,
        HoldingsValuationSnapshot.id == str(snapshot_row.object_id),
    ).first() if snapshot_row is not None else None
    if snapshot is None:
        return ChannelDecision(applicable=True, reason_code=ReasonCode.CCX_FX_BASIS_MISSING.value, **base)
    fx = _fx_basis_findings(snapshot) or _current_fx_findings(db, snapshot, envelope.tenant_id)
    if fx:
        return _channel_blocked(fx[0], **base)
    bound_parameter = bindings.get(PARAMETER_SET_BINDING_KIND)
    bound_goal = bindings.get(GOAL_METRIC_BINDING_KIND)
    if bound_parameter is None or bound_goal is None:
        return ChannelDecision(applicable=True, reason_code=ReasonCode.CCX_CHANNEL_BINDING_MISSING.value, **base)
    try:
        parameter_hash, goal_hash = _ade.p5_decision_hashes(db, mandate=mandate, ta=ta)
    except ParameterSetMissing:
        return ChannelDecision(applicable=True, reason_code=ReasonCode.CCX_PARAMETER_SET_MISSING.value, **base)
    except GoalMetricUncertified:
        return ChannelDecision(applicable=True, reason_code=ReasonCode.CCX_GOAL_METRIC_UNCERTIFIED.value, **base)
    if parameter_hash != bound_parameter.child_hash:
        return ChannelDecision(applicable=True, reason_code=ReasonCode.CCX_CHANNEL_HASH_MISMATCH.value, **base)
    if goal_hash != bound_goal.child_hash:
        return ChannelDecision(applicable=True, reason_code=ReasonCode.CCX_GOAL_METRIC_MISMATCH.value, **base)
    try:
        rounding = json.loads(envelope.canonical_payload_json or "{}").get("rounding_policy_version")
    except (TypeError, ValueError):
        rounding = None
    return ChannelDecision(applicable=True, rounding_policy_version=rounding,
                           parameter_set_hash=parameter_hash, goal_metric_payload_hash=goal_hash, **base)


def _channel_audit(db: Session, *, user: Any, mandate: Any, ip_address: str | None, field_name: str,
           record_id: str, **values: Any) -> None:
    log(db, user_id=getattr(user, "id", None),
        user_name=getattr(user, "full_name", None) or getattr(user, "username", "") or "system",
        table_name="advisory_decision_envelopes", record_id=str(record_id), action="UPDATE",
        field_name=field_name, new_value=json.dumps(values, sort_keys=True, default=str),
        mandate_id=getattr(mandate, "id", None), client_id=getattr(mandate, "client_id", None),
        ip_address=ip_address, tenant_id=mandate_tenant(mandate))


def require_channel_envelope(
    db: Session, mandate: Any, *, channel: str, user: Any, ip_address: str | None = None,
    outdated_code: ReasonCode | None = None, decision: ChannelDecision | None = None,
) -> ChannelDecision:
    """Gate: auslieferbar oder 409 (Audit ``ccx.channel.blocked``).

    ``outdated_code`` (Signatur/Handoff): ein publizierter, aber nicht mehr
    aktueller Entscheid (veraltet, Bindung/Hash weicht ab) wird als
    ``CCX_SIGNATURE_ENVELOPE_OUTDATED`` bzw. ``CCX_HANDOFF_ENVELOPE_OUTDATED``
    gemeldet; FX-Ursachen behalten ihren FX-Code. Die Ursache steht in
    ``blocker_code`` und ``cause``."""
    decision = decision or evaluate_channel_envelope(db, mandate)
    if decision.ok or not decision.applicable:
        if not decision.applicable:
            decision = _channel_blocked(ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE)
        else:
            return decision
    blocker = str(decision.reason_code)
    code: str = blocker
    if outdated_code is not None and blocker not in _FX_CODES:
        code = outdated_code.value
    rollback_keeping_tenant(db)
    if decision.drift and decision.envelope_id:
        envelope = db.get(AdvisoryDecisionEnvelope, decision.envelope_id)
        if envelope is not None:
            persist_freshness_drift(db, envelope, list(decision.drift), user)
    _channel_audit(db, user=user, mandate=mandate, ip_address=ip_address, field_name=P5_AUDIT_CHANNEL_BLOCKED,
           record_id=decision.envelope_id or str(mandate.id), reason_code=code, blocker_code=blocker,
           channel=channel, envelope_hash=decision.envelope_hash)
    db.commit()
    prefix = "Auslieferung gesperrt"
    if code == ReasonCode.CCX_HANDOFF_ENVELOPE_OUTDATED.value:
        prefix = "Weiterleitung gesperrt"
    elif code == ReasonCode.CCX_SIGNATURE_ENVELOPE_OUTDATED.value:
        prefix = "Signatur gesperrt"
    extra = {"channel": channel, "blocker_code": blocker, "cause": decision.cause,
             "envelope_hash": decision.envelope_hash}
    if code == ReasonCode.CCX_HANDOFF_ENVELOPE_OUTDATED.value:
        raise DomainError(ReasonCode.CCX_HANDOFF_ENVELOPE_OUTDATED,
                          f"{prefix} ({channel}): {decision.cause}", http_status=409, extra=extra)
    raise DomainError(code, f"{prefix} ({channel}): {decision.cause}", http_status=409, extra=extra)


def record_channel_publication(
    db: Session, decision: ChannelDecision, *, mandate: Any, channel: str, artifact_id: str,
    channel_payload_hash: str, render_hash: str | None, user: Any,
) -> AdvisoryChannelPublication:
    """Append-only Kanalzeile (idempotent je ``(envelope, channel, artifact)``)."""
    if not decision.ok:
        raise DomainError(ReasonCode.CCX_CHANNEL_BINDING_MISSING,
                          "Kanalzeile ohne auslieferbaren Beratungsentscheid.", http_status=409)
    existing = db.query(AdvisoryChannelPublication).filter(
        AdvisoryChannelPublication.envelope_id == decision.envelope_id,
        AdvisoryChannelPublication.channel == channel,
        AdvisoryChannelPublication.artifact_id == str(artifact_id),
    ).first()
    if existing is not None:
        if existing.channel_payload_hash != channel_payload_hash or existing.render_hash != render_hash:
            raise DomainError(ReasonCode.CCX_CHANNEL_HASH_MISMATCH,
                              "Das Artefakt wurde für diesen Entscheid bereits mit anderem Inhalt ausgeliefert.",
                              http_status=409, extra={"channel": channel})
        return existing
    # P5b (Vertrag §1 "monotone Version"): laufende Nummer je Mandat; ein
    # paralleles Schreiben derselben Nummer scheitert am Unique-Index.
    last = db.query(AdvisoryChannelPublication.channel_sequence).filter(
        AdvisoryChannelPublication.mandate_id == str(mandate.id),
    ).order_by(AdvisoryChannelPublication.channel_sequence.desc()).first()
    row = AdvisoryChannelPublication(
        channel_sequence=int(last[0] or 0) + 1 if last else 1,
        id=new_uuid(), tenant_id=mandate_tenant(mandate), mandate_id=str(mandate.id),
        envelope_id=decision.envelope_id, channel=channel, artifact_id=str(artifact_id),
        schema_version=CHANNEL_PUBLICATION_SCHEMA, channel_payload_hash=channel_payload_hash,
        render_hash=render_hash, rounding_policy_version=str(decision.rounding_policy_version or ""),
        bound_envelope_hash=decision.envelope_hash, parameter_contract_version=PARAMETER_CONTRACT_VERSION,
        parameter_set_hash=decision.parameter_set_hash, goal_metric_contract_version=GOAL_METRIC_CONTRACT_VERSION,
        goal_metric_payload_hash=decision.goal_metric_payload_hash, status=CHANNEL_STATUS_PUBLISHED,
        created_at=utc_now(), created_by=getattr(user, "id", None),
    )
    # P5c (H-183-Pruefung, Hinweis): verliert ein paralleles Schreiben die Nummer
    # (Unique-Index / Trigger CCX_CHANNEL_SEQUENCE_RACE), ist das ein typisierter
    # 409 statt eines 500. Der SAVEPOINT laesst die umgebende Transaktion intakt.
    # Fixrunde 1 / N-933-05: ausstehende Objekte der aeusseren Transaktion vorher
    # schreiben (ihre Fehler sind kein Wettlauf), und nur die Verletzung der
    # laufenden Nummer gilt als Wettlauf -- jeder andere Integritaetsfehler
    # (FK, NOT NULL, CHECK, Bindung) bleibt unveraendert.
    db.flush()
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except OperationalError:
        raise  # Lock/Verbindung: technischer Fehler, kein Wettlauf
    except DBAPIError as exc:
        if not is_channel_sequence_race(exc):
            raise
        logger.info("P5c: Kanalzeile verloren (Nummernwettlauf) | mandate=%s", mandate.id)
        raise DomainError(ReasonCode.CCX_CHANNEL_SEQUENCE_RACE,
                          "Das Dokument wurde gleichzeitig ein zweites Mal ausgeliefert. Bitte erneut versuchen.",
                          http_status=409, extra={"channel": channel}) from exc
    return row


def artifact_publication(db: Session, decision: ChannelDecision, *, artifact_id: str,
                         channel: str = CHANNEL_PDF) -> AdvisoryChannelPublication | None:
    """Kanalzeile eines Artefakts fuer genau diesen Entscheid (oder None)."""
    if not decision.ok:
        return None
    return db.query(AdvisoryChannelPublication).filter(
        AdvisoryChannelPublication.envelope_id == decision.envelope_id,
        AdvisoryChannelPublication.channel == channel,
        AdvisoryChannelPublication.artifact_id == str(artifact_id),
        AdvisoryChannelPublication.bound_envelope_hash == decision.envelope_hash,
        AdvisoryChannelPublication.parameter_set_hash == decision.parameter_set_hash,
        AdvisoryChannelPublication.goal_metric_payload_hash == decision.goal_metric_payload_hash,
    ).first()


def require_signable_decision_artifact(
    db: Session, mandate: Any, document: Any, *, channel: str, user: Any, ip_address: str | None = None,
) -> tuple[ChannelDecision, AdvisoryChannelPublication]:
    """Signatur eines Empfehlungsdokuments: Kanal-Gate + das Dokument muss als
    PDF-Artefakt genau dieses Entscheids ausgeliefert worden sein (Envelope-,
    Parameter-, Zielkennzahl- und Render-Hash) -- sonst
    ``CCX_SIGNATURE_ENVELOPE_OUTDATED``. Eine erneute Signatur eines alten
    Artefakts macht nie wieder FRESH."""
    decision = require_channel_envelope(db, mandate, channel=channel, user=user, ip_address=ip_address,
                                        outdated_code=ReasonCode.CCX_SIGNATURE_ENVELOPE_OUTDATED)
    publication = artifact_publication(db, decision, artifact_id=str(document.id))
    checksum = str(getattr(document, "checksum_sha256", "") or "").lower()
    if publication is None or str(publication.render_hash or "") != checksum:
        rollback_cause = (
            "Das Dokument gehört nicht zum aktuellen versiegelten Beratungsentscheid (anderer Entscheid, "
            "neu gerechnet oder vor der Kanal-Bindung erzeugt). Bitte das Dokument neu erzeugen."
        )
        rollback_keeping_tenant(db)
        _channel_audit(db, user=user, mandate=mandate, ip_address=ip_address, field_name=P5_AUDIT_CHANNEL_BLOCKED,
               record_id=decision.envelope_id, reason_code=ReasonCode.CCX_SIGNATURE_ENVELOPE_OUTDATED.value,
               blocker_code="artifact_not_bound", channel=channel, document_id=str(document.id),
               envelope_hash=decision.envelope_hash)
        db.commit()
        raise DomainError(
            ReasonCode.CCX_SIGNATURE_ENVELOPE_OUTDATED, f"Signatur gesperrt: {rollback_cause}",
            http_status=409, extra={"channel": channel, "blocker_code": "artifact_not_bound",
                                    "cause": rollback_cause, "envelope_hash": decision.envelope_hash},
        )
    return decision, publication


# Dokumenttypen, deren finale Fassung als PDF-Artefakt eines Entscheids
# archiviert wird (routers/pdf_reports.py::_archive_final mit Allokationsbindung).
DECISION_ARTIFACT_DOCUMENT_TYPES = frozenset({
    "Anlagestrategie", "Anlagerezept", "Beratungsprotokoll", "Kostenausweis",
})


def require_signature_envelope(
    db: Session, mandate: Any, document: Any, *, channel: str, user: Any, ip_address: str | None = None,
) -> tuple[ChannelDecision, AdvisoryChannelPublication] | None:
    """Signatur-Gate (Berater- und Vor-Ort-Signatur). ``(decision,
    publication)`` fuer Entscheid-Dokumente, ``None`` fuer Dokumente ohne
    Entscheidbezug; sonst 409 (``CCX_SIGNATURE_ENVELOPE_OUTDATED``/FX-Code)."""
    document_type = str(getattr(document, "document_type", "") or "")
    if document_type not in RECOMMENDATION_DOCUMENT_TYPES:
        return None
    if document_type in DECISION_ARTIFACT_DOCUMENT_TYPES:
        return require_signable_decision_artifact(
            db, mandate, document, channel=channel, user=user, ip_address=ip_address,
        )
    require_channel_envelope(db, mandate, channel=channel, user=user, ip_address=ip_address,
                             outdated_code=ReasonCode.CCX_SIGNATURE_ENVELOPE_OUTDATED)
    return None


_RENDER_CHANNELS = ("PDF", "ARCHIVE", "ADVISOR_SIGNATURE", "ONSITE_SIGNATURE")


def _envelope_fassung(db: Session, envelope: AdvisoryDecisionEnvelope) -> int | None:
    """Laufende Nummer der Versiegelung im Mandat (monoton, N-925-08)."""
    if not envelope.sealed_at:
        return None
    return db.query(AdvisoryDecisionEnvelope).filter(
        AdvisoryDecisionEnvelope.tenant_id == envelope.tenant_id,
        AdvisoryDecisionEnvelope.mandate_id == envelope.mandate_id,
        AdvisoryDecisionEnvelope.status.in_(("SEALED", "SUPERSEDED")),
        AdvisoryDecisionEnvelope.sealed_at <= envelope.sealed_at,
    ).count()


def verify_archive_replay(db: Session, document: Any, pdf_bytes: bytes) -> dict | None:
    """P5b / N-925-04 (Vertrag §8.3 Punkt 2): ein archiviertes Entscheid-
    Artefakt wird nur wiedergegeben, wenn die gespeicherten Bytes genau den
    ``render_hash`` seiner Kanalzeile(n) tragen, der gebundene Envelope mit
    diesem Hash existiert und die Rundungsfassung der Zeile die des Envelopes
    ist. Nicht neu gerechnet, nicht neu gerendert; FRESH ist fuer die
    Wiedergabe nicht verlangt (Nachweis "was wurde gezeigt")."""
    rows = db.query(AdvisoryChannelPublication).filter(
        AdvisoryChannelPublication.mandate_id == str(document.mandate_id),
        AdvisoryChannelPublication.artifact_id == str(document.id),
        AdvisoryChannelPublication.channel.in_(_RENDER_CHANNELS),
    ).order_by(AdvisoryChannelPublication.channel_sequence).all()
    if not rows:
        return None
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    reference: dict | None = None
    for row in rows:
        if row.render_hash != digest or str(getattr(document, "checksum_sha256", "") or digest) != digest:
            raise DomainError(ReasonCode.CCX_SEALED_ARTIFACT_HASH_MISMATCH,
                              "Das archivierte Dokument weicht vom versiegelten Artefakt ab.", http_status=409)
        envelope = db.query(AdvisoryDecisionEnvelope).filter(
            AdvisoryDecisionEnvelope.tenant_id == row.tenant_id,
            AdvisoryDecisionEnvelope.id == row.envelope_id,
        ).first()
        if envelope is None or envelope.envelope_hash != row.bound_envelope_hash \
                or str(envelope.mandate_id) != str(row.mandate_id):
            raise DomainError(ReasonCode.CCX_SEALED_ARTIFACT_ENVELOPE_MISMATCH,
                              "Der Beratungsentscheid des archivierten Dokuments ist nicht nachweisbar.",
                              http_status=409)
        try:
            rounding = json.loads(envelope.canonical_payload_json or "{}").get("rounding_policy_version")
        except (TypeError, ValueError):
            rounding = None
        if str(rounding or "") != str(row.rounding_policy_version or ""):
            raise DomainError(ReasonCode.CCX_RENDER_POLICY_MISMATCH,
                              "Die Rundungsfassung des archivierten Dokuments passt nicht zum Entscheid.",
                              http_status=409)
        reference = {"pruefnummer": str(row.bound_envelope_hash)[:12],
                     "fassung": _envelope_fassung(db, envelope), "envelope_hash": str(row.bound_envelope_hash)}
    return reference


def decision_envelope_reference(db: Session, mandate: Any) -> dict:
    """P5b / N-925-04 (Tier 1 API/Classic/React): Envelope-Bezug der
    Soll-Allokation fuer die Anzeige -- Pruefnummer, Fassung, Zustand, die
    gebundenen P5-Hashes und die Kanalzeilen des Entscheids."""
    decision = evaluate_channel_envelope(db, mandate)
    if decision.ok:
        state = "deliverable"
    elif decision.sealed:
        state = "sealed_not_deliverable"
    else:
        state = "none"
    rows = []
    if decision.envelope_id:
        rows = [{
            "channel": row.channel, "artifact_id": row.artifact_id, "channel_sequence": row.channel_sequence,
            "channel_payload_hash": row.channel_payload_hash, "render_hash": row.render_hash,
            "parameter_set_hash": row.parameter_set_hash, "goal_metric_payload_hash": row.goal_metric_payload_hash,
            "created_at": row.created_at,
        } for row in db.query(AdvisoryChannelPublication).filter(
            AdvisoryChannelPublication.envelope_id == str(decision.envelope_id),
        ).order_by(AdvisoryChannelPublication.channel_sequence).all()]
    return {
        "state": state,
        "reason_code": None if decision.ok else decision.reason_code,
        "pruefnummer": str(decision.envelope_hash)[:12] if decision.ok and decision.envelope_hash else None,
        "fassung": decision.fassung if decision.ok else None,
        "envelope_hash": decision.envelope_hash if decision.ok else None,
        "parameter_set_hash": decision.parameter_set_hash if decision.ok else None,
        "goal_metric_payload_hash": decision.goal_metric_payload_hash if decision.ok else None,
        "ic_release_status": decision.ic_release_status,
        "channel_publications": rows,
    }


release_gate.register_signature_envelope_gate(
    require_signature_envelope, record_channel_publication, CHANNEL_ADVISOR_SIGNATURE,
    replay=verify_archive_replay,
)


__all__ = [
    "CHANNEL_ADVISOR_SIGNATURE", "CHANNEL_HANDOFF", "CHANNEL_ONSITE_SIGNATURE", "CHANNEL_PDF", "ChannelDecision",
    "DECISION_ARTIFACT_DOCUMENT_TYPES", "artifact_publication", "evaluate_channel_envelope",
    "record_channel_publication", "require_channel_envelope", "require_signable_decision_artifact",
    "require_signature_envelope",
    "AllocationVersionConflict", "UNPUBLISHED_WATERMARK", "assert_report_allocation_matches",
    "customer_document_watermark", "published_allocation_matches_snapshot",
    "APPROVAL_APPROVED", "STATUS_DRAFT", "STATUS_PUBLICATION_INVALID", "STATUS_PUBLISHED",
    "VALIDATION_PASS", "VALIDATION_REJECTED", "PublicationEvaluation", "PublicationState",
    "active_publication_state", "allocation_publication_status", "approval_hash_for", "approval_mode_for",
    "current_target_allocation", "evaluate_allocation_publication", "is_publishable", "publication_overview",
    "publication_inbox_envelopes",
    "publish_allocation", "require_published_allocation", "validation_hash_for",
]
