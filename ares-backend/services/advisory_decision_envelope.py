"""CCX-P1 Snapshot und Hash: Beratungsentscheid erzeugen, binden, versiegeln.

Vertrag 2026-11-13 §4. Ein Beratungsentscheid (finalisierte Empfehlung) wird
genau einmal als unveraenderlicher Envelope ``ares/advisory-envelope/1``
versiegelt; alle Kanaele referenzieren spaeter (P5) denselben
``envelope_hash``.

Ablauf ``seal_advisory_envelope`` (innerhalb der Finalisierungs-Transaktion,
die Mandatszeile ist bereits gesperrt):

1. Inputs lesen (Effective-Input-Manifest, zehn Kind-Hashes).
2. Kind-Bindungen bilden: Manifest, Soll-Allokation, Lauf, Positionen.
3. Kanonischen Payload und Root-Hash berechnen (Vorgaenger-Hash ist Teil des
   Payloads -- eine Rueckkehr A -> B -> A ergibt einen neuen Envelope).
4. Bisher versiegelten Envelope des Mandats SEALED -> SUPERSEDED (optimistisch,
   genau eine Zeile), neuen Envelope als DRAFT einfuegen, Bindungen und
   Manifest schreiben.
5. Snapshot-Fence: Inputs erneut lesen; jede Abweichung -> ``RETRY`` ->
   ``CCX_INPUT_MANIFEST_MISMATCH``, nichts wird versiegelt.
6. DRAFT -> SEALED. Die Datenbank erzwingt: hoechstens ein SEALED je Mandat,
   ein Nachfolger je Vorgaenger, Unique (tenant, envelope_hash) -- bei
   paralleler Versiegelung gewinnt genau eine Transaktion, die andere endet
   mit ``CCX_ENVELOPE_UNSEALED``.

CCX-P2 (Vertrag 2026-11-13 §5) ergaenzt: die Versiegelung sperrt die
Mandatszeile selbst (PostgreSQL), schreibt je Abhaengigkeit eine Kante
(``advisory_dependency_edges``) und setzt den Envelope erst damit FRESH. Ein
verspaetetes Ergebnis (Manifest beim Start != Manifest beim Commit) endet mit
``CCX_RESULT_SUPERSEDED``; eine Invalidation des entstehenden DRAFT durch den
zentralen Mutation Hook (models/snapshots.py) mit ``CCX_INVALIDATION_RACE``
(Audit ``ccx.envelope.race_rejected``). Ausgeliefert wird nur ein FRESH-
Entscheid: STALE -> ``CCX_INPUT_STALE``, UNKNOWN -> ``CCX_FRESHNESS_UNKNOWN``;
vor der Auslieferung werden die Kanten zusaetzlich gegen die aktuellen
Objekte geprueft (Abweichung -> Ereignis + STALE). Jedes Invalidations-
ereignis wird im selben Commit als ``ccx.envelope.invalidated`` auditiert.

Jede Ablehnung verwirft die offene Transaktion, setzt den Tenant-Kontext der
Session wieder (H7-Muster, N-884-09) und schreibt einen tenant- und
mandatsgebundenen Audit-Eintrag ``ccx.envelope.rejected`` (IDs und Hashes,
nie Payload); erfolgreiche Versiegelung schreibt ``ccx.envelope.sealed`` und
fuer den Vorgaenger ``ccx.envelope.superseded``. Es gibt keinen Fallback auf
einen aelteren oder unvollstaendigen Entscheid.
"""
from __future__ import annotations
import json

from core.goal_metric_contract import GoalMetricUncertified, build_goal_metric_payload
from core.risk_parameter_set import ParameterSetMissing, stored_risk_parameter_set, verify_parameter_set

import logging
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from core.fx_freshness import freshness_cause
from core.advisory_envelope_codec import (
    CanonicalPayloadError,
    envelope_hash as compute_envelope_hash,
    manifest_hash as compute_manifest_hash,
    none_sort_key,
    parse_canonical,
    ENVELOPE_PAYLOAD_SCHEMA,
    rows_child_hash,
    utc_now,
)
from core.db_integrity import is_check_constraint_violation
from core.evidence import ADVISORY_ENVELOPE_SCHEMA
from core.presentation_rounding import ROUNDING_POLICY_VERSION
from core.reason_codes import DomainError, ReasonCode
from database import new_uuid
from models.allocation import TargetAllocation
from models.review import RecommendationPosition, RecommendationRun
from models.snapshots import (
    ACTOR_INFO_KEY,
    FRESHNESS_FRESH,
    FRESHNESS_STALE,
    FRESHNESS_UNKNOWN,
    REFERENCE_KINDS,
    AdvisoryDecisionEnvelope,
    AdvisoryDependencyEdge,
    AdvisoryEffectiveInputManifest,
    AdvisoryEnvelopeBinding,
    AdvisoryInvalidationEvent,
    HoldingsValuationSnapshot,
    PositionDecisionLedger,
    mark_envelope_stale,
    register_invalidation_audit_sink,
    signed_decision_sql,
)
from services.advisory_cache_scope import ADVISORY_REPORT_CONSUMER, advisory_cache_key
from services.advisory_envelope_integrity import MANIFEST_BINDING_KIND, envelope_integrity_defect
from services.advisory_snapshot_transaction import RETRY, classify_snapshot_consistency
from services.audit import log, restore_tenant_after_rollback
from services.effective_input_manifest import (
    active_included_goals,
    build_manifest_record,
    collect_dependency_parts,
    collect_effective_input_components,
    components_from_parts,
    legacy_projection_allowed,
    empty_required_kinds,
)
from services.tenant_context import set_tenant_context

logger = logging.getLogger(__name__)

AUDIT_TABLE = "advisory_decision_envelopes"
AUDIT_SEALED = "ccx.envelope.sealed"
AUDIT_REJECTED = "ccx.envelope.rejected"
AUDIT_SUPERSEDED = "ccx.envelope.superseded"
AUDIT_INVALIDATED = "ccx.envelope.invalidated"
AUDIT_RACE_REJECTED = "ccx.envelope.race_rejected"

# Lebenszyklus-Spalten, die NICHT zum Entscheidinhalt gehoeren (aendern sich
# nach dem Siegel legitim, z. B. Final -> Superseded).
_VOLATILE = {
    "target_allocations": frozenset({"updated_at", "deleted_at", "is_current"}),
    "recommendation_runs": frozenset({"updated_at", "result_status"}),
    "recommendation_positions": frozenset({"updated_at"}),
}


class AdvisoryEnvelopeError(DomainError):
    """Gate-Fehler des Beratungsentscheids (Reason-Code ``CCX_*``)."""

    channel = "advisory_envelope"


def _columns(model: Any) -> list[str]:
    skip = _VOLATILE.get(model.__tablename__, frozenset())
    return [attr.key for attr in sa_inspect(model).column_attrs if attr.key not in skip]


def _row_hash(kind: str, model: Any, rows: list[Any], sort_fields: tuple[str, ...]) -> str:
    return rows_child_hash(
        kind, _columns(model), rows,
        lambda row: tuple(none_sort_key(getattr(row, name)) for name in sort_fields),
    )


def mandate_tenant(mandate: Any) -> str | None:
    tenant_id = str(getattr(mandate, "tenant_id", None) or "").strip()
    return tenant_id or None


def current_sealed_envelope(
    db: Session, tenant_id: str, mandate_id: str, *, for_update: bool = False,
) -> AdvisoryDecisionEnvelope | None:
    query = db.query(AdvisoryDecisionEnvelope).filter(
        AdvisoryDecisionEnvelope.tenant_id == tenant_id,
        AdvisoryDecisionEnvelope.mandate_id == str(mandate_id),
        AdvisoryDecisionEnvelope.status == "SEALED",
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


def advisory_report_cache_scope(db: Session, mandate: Any) -> str:
    """CCX-10: Cache-Scope (tenant, mandate, envelope_hash) des Advisory-Reports.

    CCX-P2: ein nicht FRESHer Entscheid traegt Frische und
    ``optimistic_version`` im Consumer-Vertrag -- jede Invalidation ergibt
    damit einen neuen Scope, ein vor der Mutation gecachter Report wird nie
    wiederverwendet."""
    tenant_id = mandate_tenant(mandate) or "unbound"
    row = db.query(
        AdvisoryDecisionEnvelope.envelope_hash,
        AdvisoryDecisionEnvelope.freshness_status,
        AdvisoryDecisionEnvelope.optimistic_version,
    ).filter(
        AdvisoryDecisionEnvelope.tenant_id == tenant_id,
        AdvisoryDecisionEnvelope.mandate_id == str(mandate.id),
        AdvisoryDecisionEnvelope.status == "SEALED",
    ).first()
    if row is None:
        return advisory_cache_key(tenant_id, str(mandate.id), None)
    if row[1] == FRESHNESS_FRESH:
        # N-908-01: gespeicherter Status allein genuegt nicht -- Kanten pruefen
        # (lesend); eine Abweichung ergibt einen eigenen, nicht FRESHen Scope.
        envelope = current_sealed_envelope(db, tenant_id, str(mandate.id))
        defect = envelope_freshness_defect(db, envelope, mandate=mandate, persist=False) if envelope else None
        if defect is None:
            return advisory_cache_key(tenant_id, str(mandate.id), row[0])
        return advisory_cache_key(
            tenant_id, str(mandate.id), row[0],
            consumer_contract_version=f"{ADVISORY_REPORT_CONSUMER}#PULL:{defect[0]}#{defect[1]}",
        )
    return advisory_cache_key(
        tenant_id, str(mandate.id), row[0],
        consumer_contract_version=f"{ADVISORY_REPORT_CONSUMER}#{row[1]}#{int(row[2])}",
    )


# ── Audit ────────────────────────────────────────────────────────────────────


def _audit_value(reason: str | None = None, **parts: Any) -> str:
    items = ([("reason_code", reason)] if reason is not None else []) + list(parts.items())
    return ";".join(f"{key}={value if value not in (None, '') else '-'}" for key, value in items)


def _reject(
    db: Session,
    error: AdvisoryEnvelopeError,
    *,
    user: Any,
    mandate: Any,
    tenant_id: str | None,
    ip_address: str | None,
    record_id: str | None,
    audit_field: str = AUDIT_REJECTED,
    **refs: Any,
) -> AdvisoryEnvelopeError:
    """Verwirft offene Aenderungen, setzt den Tenant-Kontext wieder, schreibt
    und committet ``ccx.envelope.rejected`` (bzw. ``ccx.envelope.
    race_rejected``) -- danach wirft der Aufrufer."""
    restore_tenant_after_rollback(db, set_tenant_context)
    log(
        db, user_id=user.id, user_name=getattr(user, "full_name", None) or getattr(user, "username", ""),
        table_name=AUDIT_TABLE, record_id=str(record_id or getattr(mandate, "id", "") or "-"),
        action="CREATE", field_name=audit_field,
        new_value=_audit_value(error.reason_code, **refs),
        mandate_id=getattr(mandate, "id", None), client_id=getattr(mandate, "client_id", None),
        ip_address=ip_address, tenant_id=tenant_id,
    )
    db.commit()
    return error


def reject_fx_basis_before_seal(
    db: Session, error: DomainError, *, mandate: Any, run: Any, user: Any, ip_address: str | None = None,
) -> DomainError:
    """CCX-P3-FX (N-909-12): eine FX-Sperre VOR dem Siegel (Payload-Neuberechnung
    der Finalisierung mit strikter Quelle) wird wie die Bewertungssperre im
    Siegel behandelt: Bewertungsabdeckung UNKNOWN, Audit ``ccx.envelope.rejected``
    mit Stage ``valuation``, Code, Mandat und Tenant. Der Aufrufer wirft danach."""
    error.extra.setdefault("coverage_status", "UNKNOWN")
    return _reject(
        db, error, user=user, mandate=mandate, tenant_id=mandate_tenant(mandate), ip_address=ip_address,
        record_id=run.id, run=run.id, stage="valuation", coverage="UNKNOWN", origin="target_payload",
    )


def call_with_fx_basis_audit(fn: Any, db: Session, *, mandate: Any, run: Any, user: Any,
                             ip_address: str | None = None) -> Any:
    """Fuehrt ``fn()`` aus; eine FX-Sperre (Kanal ``fx_basis``) wird vor dem
    Weiterwerfen wie die Bewertungssperre im Siegel auditiert (N-909-12)."""
    try:
        return fn()
    except DomainError as exc:
        if getattr(exc, "channel", None) != "fx_basis":
            raise
        raise reject_fx_basis_before_seal(
            db, exc, mandate=mandate, run=run, user=user, ip_address=ip_address,
        ) from exc


# ── Versiegeln ───────────────────────────────────────────────────────────────


VALUATION_BINDING_KIND = "holdings_valuation_snapshot"
LEDGER_BINDING_KIND = "position_decision_ledger"


PARAMETER_SET_BINDING_KIND = "risk_parameter_set"
GOAL_METRIC_BINDING_KIND = "goal_metric"


def _p5_bindings(ta: Any, parameter_set_hash: str | None, goal_metric_hash: str | None) -> list[dict[str, Any]]:
    """CCX P5: Parametersatz (M-2) und Zielkennzahl (M-3) als Kind-Bindungen."""
    out: list[dict[str, Any]] = []
    if parameter_set_hash:
        out.append({"binding_kind": PARAMETER_SET_BINDING_KIND, "ordinal": 0,
                    "object_type": TargetAllocation.__tablename__, "object_id": str(ta.id),
                    "object_version": None, "child_hash": parameter_set_hash})
    if goal_metric_hash:
        out.append({"binding_kind": GOAL_METRIC_BINDING_KIND, "ordinal": 0,
                    "object_type": TargetAllocation.__tablename__, "object_id": str(ta.id),
                    "object_version": None, "child_hash": goal_metric_hash})
    return out


def p5_decision_hashes(db: Session, *, mandate: Any, ta: Any) -> tuple[str, str]:
    """``(parameter_set_hash, goal_metric_payload_hash)`` der Soll-Allokation,
    fail-closed (``ParameterSetMissing`` / ``GoalMetricUncertified``)."""
    record = stored_risk_parameter_set(ta)
    try:
        persisted = json.loads(getattr(ta, "effective_constraints_json", None) or "{}").get(
            "risky_fraction_per_bucket_bps")
    except (TypeError, ValueError, AttributeError):
        persisted = None
    parameter_hash = verify_parameter_set(record, persisted_coefficients=persisted if isinstance(persisted, dict) else {})
    # IC-Freigabe: fail-closed bei der Berechnung (Produktion, Engine/manuell);
    # hier nur Integritaet und Kohaerenz des gespeicherten Satzes.
    goal_payload = build_goal_metric_payload(
        active_included_goals(db, str(mandate.id)), mandate=mandate, target_allocation=ta,
    )
    return parameter_hash, goal_payload["goal_metric_payload_hash"]


def _bindings(
    db: Session, *, manifest: AdvisoryEffectiveInputManifest, ta: Any, run: Any,
    valuation: tuple[str, str] | None = None, ledger_hash: str | None = None,
    p5_hashes: tuple[str, str] | None = None,
) -> list[dict[str, Any]]:
    positions = db.query(RecommendationPosition).filter(RecommendationPosition.run_id == str(run.id)).all()
    # CCX-P3: Bewertungs-Snapshot (Stichtag, Quelle, FX-Basis) und Entscheid je
    # Position als Kind-Bindungen; Kind-Hashes enthalten keine DB-IDs, die erst
    # nach dem Hash entstehen.
    p3 = [] if valuation is None else [
        {"binding_kind": VALUATION_BINDING_KIND, "ordinal": 0,
         "object_type": HoldingsValuationSnapshot.__tablename__, "object_id": valuation[0],
         "object_version": None, "child_hash": valuation[1]},
        {"binding_kind": LEDGER_BINDING_KIND, "ordinal": 0,
         "object_type": PositionDecisionLedger.__tablename__, "object_id": str(run.id),
         "object_version": None, "child_hash": ledger_hash},
    ]
    p5 = [] if p5_hashes is None else _p5_bindings(ta, *p5_hashes)
    return p3 + p5 + [
        {"binding_kind": MANIFEST_BINDING_KIND, "ordinal": 0,
         "object_type": AdvisoryEffectiveInputManifest.__tablename__, "object_id": str(manifest.id),
         "object_version": None, "child_hash": manifest.manifest_hash},
        {"binding_kind": "target_allocation", "ordinal": 0,
         "object_type": TargetAllocation.__tablename__, "object_id": str(ta.id),
         "object_version": int(ta.version) if ta.version is not None else None,
         "child_hash": _row_hash("target-allocation", TargetAllocation, [ta], ("id",))},
        {"binding_kind": "recommendation_run", "ordinal": 0,
         "object_type": RecommendationRun.__tablename__, "object_id": str(run.id),
         "object_version": None,
         "child_hash": _row_hash("recommendation-run", RecommendationRun, [run], ("id",))},
        {"binding_kind": "recommendation_positions", "ordinal": 0,
         "object_type": RecommendationRun.__tablename__, "object_id": str(run.id),
         "object_version": None,
         "child_hash": _row_hash(
             "recommendation-positions", RecommendationPosition, positions, ("product_id", "id"),
         )},
    ]


def _valuation_reason(code: str) -> ReasonCode:
    """Katalogisierter Code eines Bewertungsblockers (statisch aufloesbar)."""
    if code == ReasonCode.CCX_FX_BASIS_MISSING:
        return ReasonCode.CCX_FX_BASIS_MISSING
    if code == ReasonCode.CCX_FX_BASIS_MISMATCH:
        return ReasonCode.CCX_FX_BASIS_MISMATCH
    if code == ReasonCode.CCX_FX_BASIS_STALE:
        return ReasonCode.CCX_FX_BASIS_STALE
    if code == ReasonCode.CCX_VALUATION_STALE:
        return ReasonCode.CCX_VALUATION_STALE
    if code == ReasonCode.CCX_VALUATION_MISSING:
        return ReasonCode.CCX_VALUATION_MISSING
    if code == ReasonCode.CCX_VALUATION_ATTESTATION_REQUIRED:
        return ReasonCode.CCX_VALUATION_ATTESTATION_REQUIRED
    return ReasonCode.CCX_VALUATION_INCOMPLETE


def seal_advisory_envelope(
    db: Session,
    *,
    mandate: Any,
    run: Any,
    user: Any,
    ip_address: str | None = None,
    valuation: Any = None,
    expected_manifest_hash: str | None = None,
) -> AdvisoryDecisionEnvelope:
    """Erzeugt, bindet und versiegelt den Envelope der finalisierten Empfehlung
    ``run`` (Transaktion des Aufrufers; der Commit folgt dort).

    CCX-P3: vor dem Siegel wird der gesamte Bestand verlustfrei bewertet; nur
    ein COMPLETE-Snapshot (alle Preise/Kurse belegt und frisch, eine FX-Basis)
    wird gebunden, sonst endet die Finalisierung mit dem typisierten Code
    (CCX_VALUATION_* / CCX_FX_BASIS_*) und Audit. Je bestehender Depotposition
    wird ein Entscheid KEEP/SELL/REVIEW im Ledger gebunden.


    ``expected_manifest_hash`` (CCX-P2): der beim Start der Berechnung bzw.
    des Requests gelesene Manifest-Hash; weicht er vom Hash beim Siegel ab,
    ist das Ergebnis verspaetet -> ``CCX_RESULT_SUPERSEDED``."""
    tenant_id = mandate_tenant(mandate)
    common = {"user": user, "mandate": mandate, "tenant_id": tenant_id, "ip_address": ip_address}
    if tenant_id is None:
        raise _reject(db, AdvisoryEnvelopeError(
            ReasonCode.CCX_ENVELOPE_UNSEALED,
            "Der Beratungsentscheid kann nicht versiegelt werden: das Mandat ist keiner Firma zugeordnet.",
        ), record_id=run.id, run=run.id, stage="tenant", **common)
    ta = None
    if getattr(run, "target_allocation_id", None):
        ta = db.query(TargetAllocation).filter(
            TargetAllocation.id == str(run.target_allocation_id),
            TargetAllocation.mandate_id == str(mandate.id),
        ).first()
    if ta is None:
        raise _reject(db, AdvisoryEnvelopeError(
            ReasonCode.CCX_BINDING_MISSING,
            "Der Beratungsentscheid kann nicht versiegelt werden: die Empfehlung ist an keine "
            "Soll-Allokation dieses Mandats gebunden.",
        ), record_id=run.id, run=run.id, binding="target_allocation", **common)
    locale = str(getattr(mandate, "advisory_language", None) or "").strip()
    base_currency = str(getattr(mandate, "base_currency", None) or "").strip()
    if not locale or not base_currency:
        raise _reject(db, AdvisoryEnvelopeError(
            ReasonCode.CCX_ENVELOPE_UNSEALED,
            "Der Beratungsentscheid kann nicht versiegelt werden: Beratungssprache oder "
            "Referenzwährung des Mandats fehlt.",
        ), record_id=run.id, run=run.id, stage="identity", **common)

    if valuation is None:
        raise _reject(db, AdvisoryEnvelopeError(
            ReasonCode.CCX_VALUATION_MISSING,
            "Der Beratungsentscheid kann nicht versiegelt werden: es liegt keine Bewertung des "
            "Bestands vor.",
        ), record_id=run.id, run=run.id, stage="valuation", **common)
    projection = valuation.projection
    if not valuation.publishable:
        raise _reject(db, AdvisoryEnvelopeError(
            _valuation_reason(valuation.primary_code),
            "Der Beratungsentscheid kann nicht versiegelt werden: die Bewertung des Bestands ist "
            f"nicht vollständig belegt ({projection.coverage_status}). Bitte fehlende Preise, Kurse, "
            "Stichtage oder Währungen ergänzen.",
            extra={"coverage_status": projection.coverage_status,
                   "blocker_codes": list(projection.blocker_codes),
                   "valuation_snapshot_hash": projection.snapshot_hash},
        ), record_id=run.id, run=run.id, stage="valuation", coverage=projection.coverage_status,
            blockers=",".join(projection.blocker_codes), valuation_hash=projection.snapshot_hash,
            fx_basis_hash=projection.fx_basis_hash, **common)
    ledger_entries = valuation.ledger_entries
    ledger_digest = valuation.ledger_hash
    # CCX P5 (M-2/M-3): ohne kanonischen Parametersatz und ohne zertifizierte
    # Zielkennzahl kein Siegel -- typisiert, auditiert, kein Fallback.
    try:
        p5_hashes = p5_decision_hashes(db, mandate=mandate, ta=ta)
    except ParameterSetMissing as exc:
        raise _reject(db, AdvisoryEnvelopeError(
            ReasonCode.CCX_PARAMETER_SET_MISSING,
            f"Der Beratungsentscheid kann nicht versiegelt werden: {exc}",
        ), record_id=run.id, run=run.id, stage="parameter_set", **common) from exc
    except GoalMetricUncertified as exc:
        raise _reject(db, AdvisoryEnvelopeError(
            ReasonCode.CCX_GOAL_METRIC_UNCERTIFIED,
            f"Der Beratungsentscheid kann nicht versiegelt werden: {exc}",
        ), record_id=run.id, run=run.id, stage="goal_metric", **common) from exc
    # CCX-P2: dieselbe Mandatssperre wie der Mutation Hook (PostgreSQL) --
    # eine parallele Mutation wartet bis zum Commit und invalidiert danach.
    lock_mandate_row(db, str(mandate.id))
    # N-908-01 (b): die gebundenen Referenzzeilen (CMA, Optimizer-/CMA-Policy
    # samt Komponenten/Freigaben, Hausmatrix/Bausteine) FOR SHARE -- eine parallele Aenderung wartet bis zum
    # Siegel-Commit und sieht danach die Kanten (Hook invalidiert).
    lock_bound_reference_rows(db, run=run, target_allocation=ta)
    try:
        before = collect_effective_input_components(db, mandate=mandate, run=run, target_allocation=ta)
        record = build_manifest_record(
            tenant_id=tenant_id, mandate_id=str(mandate.id), components=before, run=run, target_allocation=ta,
        )
        manifest_digest = compute_manifest_hash(record)
    except (CanonicalPayloadError, ValueError) as exc:
        logger.warning("CCX-P1: Manifest nicht bildbar | mandate=%s run=%s: %s", mandate.id, run.id, exc)
        raise _reject(db, AdvisoryEnvelopeError(
            ReasonCode.CCX_INPUT_MANIFEST_MISMATCH,
            "Der Beratungsentscheid kann nicht versiegelt werden: die wirkenden Inputs lassen sich "
            "nicht eindeutig festhalten.",
        ), record_id=run.id, run=run.id, stage="manifest",
            unknown=",".join(getattr(exc, "groups", ())) or None, **common) from exc
    if expected_manifest_hash is not None and expected_manifest_hash != manifest_digest:
        raise _reject(db, AdvisoryEnvelopeError(
            ReasonCode.CCX_RESULT_SUPERSEDED,
            "Die Beratungsdaten wurden seit dem Start der Berechnung geändert; das Ergebnis ist "
            "überholt. Bitte neu berechnen.",
        ), record_id=run.id, run=run.id, stage="result", expected_manifest_hash=expected_manifest_hash,
            manifest_hash=manifest_digest, audit_field=AUDIT_RACE_REJECTED, **common)

    now = utc_now()
    predecessor = current_sealed_envelope(db, tenant_id, str(mandate.id), for_update=True)
    manifest = AdvisoryEffectiveInputManifest(
        id=new_uuid(), tenant_id=tenant_id, mandate_id=str(mandate.id),
        **{name: value for name, value in record.items() if name not in ("schema_version", "tenant_id", "mandate_id")},
        manifest_hash=manifest_digest, created_at=now, created_by=user.id,
    )
    # N-906-02: Kind-Projektion und Root-Hash sind Teil des Gates -- ein nicht
    # projizierbarer Wert endet als katalogisierter Code mit Audit, nie als 500.
    try:
        snapshot = valuation.persist(db, user_id=user.id)
    except IntegrityError as exc:
        db.rollback()
        # F1: CHECK-Verletzung (z. B. COMPLETE ohne Summe) ist 422, sonst Konflikt.
        raise _reject(db, AdvisoryEnvelopeError(
            ReasonCode.CCX_VALUATION_INCOMPLETE,
            "Der Bewertungs-Snapshot konnte nicht festgehalten werden.",
            http_status=422 if is_check_constraint_violation(exc) else None,
        ), record_id=run.id, run=run.id, stage="valuation_persist",
            valuation_hash=projection.snapshot_hash, **common) from exc
    try:
        bindings = _bindings(db, manifest=manifest, ta=ta, run=run,
                             valuation=(snapshot.id, snapshot.snapshot_hash), ledger_hash=ledger_digest,
                             p5_hashes=p5_hashes)
        payload = {
            "schema_version": ADVISORY_ENVELOPE_SCHEMA,
            "tenant_id": tenant_id,
            "mandate_id": str(mandate.id),
            "locale": locale,
            "base_currency": base_currency,
            "rounding_policy_version": ROUNDING_POLICY_VERSION,
            "predecessor_envelope_hash": predecessor.envelope_hash if predecessor is not None else None,
            "effective_input_manifest_hash": manifest_digest,
            "bindings": bindings,
        }
        canonical, digest = compute_envelope_hash(payload)
    except (CanonicalPayloadError, ValueError) as exc:
        logger.warning("CCX-P1: Bindungen nicht bildbar | mandate=%s run=%s: %s", mandate.id, run.id, exc)
        raise _reject(db, AdvisoryEnvelopeError(
            ReasonCode.CCX_BINDING_MISSING,
            "Der Beratungsentscheid kann nicht versiegelt werden: die gebundenen Objekte lassen sich "
            "nicht eindeutig festhalten.",
        ), record_id=run.id, run=run.id, stage="bindings", manifest_hash=manifest_digest, **common) from exc
    envelope_id = new_uuid()
    refs = {"run": run.id, "envelope_hash": digest, "manifest_hash": manifest_digest,
            "predecessor": predecessor.id if predecessor is not None else None}
    try:
        if predecessor is not None:
            superseded = db.query(AdvisoryDecisionEnvelope).filter(
                AdvisoryDecisionEnvelope.id == predecessor.id,
                AdvisoryDecisionEnvelope.status == "SEALED",
                AdvisoryDecisionEnvelope.optimistic_version == predecessor.optimistic_version,
            ).update({
                "status": "SUPERSEDED",
                "optimistic_version": predecessor.optimistic_version + 1,
            }, synchronize_session=False)
            if superseded != 1:
                raise _reject(db, AdvisoryEnvelopeError(
                    ReasonCode.CCX_ENVELOPE_UNSEALED,
                    "Der Beratungsentscheid wurde parallel neu versiegelt. Bitte neu laden.",
                ), record_id=run.id, stage="supersede", **refs, **common)
        db.add(manifest)
        db.add(AdvisoryDecisionEnvelope(
            id=envelope_id, tenant_id=tenant_id, mandate_id=str(mandate.id),
            schema_version=ADVISORY_ENVELOPE_SCHEMA, status="DRAFT", locale=locale,
            base_currency=base_currency, predecessor_id=predecessor.id if predecessor is not None else None,
            created_at=now, created_by=user.id, optimistic_version=1,
        ))
        db.flush()
        for item in bindings:
            db.add(AdvisoryEnvelopeBinding(
                id=new_uuid(), tenant_id=tenant_id, envelope_id=envelope_id, created_at=now,
                created_by=user.id, **item,
            ))
        for entry in ledger_entries:
            db.add(PositionDecisionLedger(
                id=new_uuid(), tenant_id=tenant_id, mandate_id=str(mandate.id), envelope_id=envelope_id,
                source_snapshot_hash=snapshot.snapshot_hash, created_at=now, created_by=user.id, **entry,
            ))
        db.flush()
        if valuation.missing_decisions():
            raise _reject(db, AdvisoryEnvelopeError(
                ReasonCode.CCX_POSITION_DECISION_MISSING,
                "Nicht jede bestehende Position hat einen Entscheid (Halten/Verkaufen/Prüfen).",
            ), record_id=run.id, stage="ledger", **refs, **common)
        # Snapshot-Fence: dieselben Inputs unmittelbar vor dem Siegel erneut.
        after_parts: list = []
        try:
            after = collect_effective_input_components(
                db, mandate=mandate, run=run, target_allocation=ta, parts_out=after_parts,
            )
        except (CanonicalPayloadError, ValueError):
            after = {}  # unbekannt geworden -> nie konsistent (RETRY)
        # CCX-P3: Marktdaten-/Bestandswechsel waehrend des Laufs -> der gebundene
        # Snapshot ist nicht mehr der aktuelle Stand (kein gemischter Stand).
        if not valuation.unchanged(db, mandate):
            raise _reject(db, AdvisoryEnvelopeError(
                ReasonCode.CCX_VALUATION_STALE,
                "Bestand, Preise oder Kurse wurden während der Versiegelung geändert. Bitte erneut "
                "finalisieren.",
            ), record_id=run.id, stage="valuation_fence", valuation_hash=projection.snapshot_hash, **refs,
                **common)
        # CCX-P2: hat der Mutation Hook den entstehenden DRAFT invalidiert,
        # ist das ein Wettlauf Mutation <-> Versiegelung -- kein Siegel.
        if _draft_invalidated(db, envelope_id):
            raise _reject(db, AdvisoryEnvelopeError(
                ReasonCode.CCX_INVALIDATION_RACE,
                "Die Beratungsdaten wurden während der Versiegelung geändert. Bitte erneut finalisieren.",
            ), record_id=run.id, stage="invalidated", audit_field=AUDIT_RACE_REJECTED, **refs, **common)
        if (classify_snapshot_consistency(before, after) == RETRY
                or components_from_parts(after_parts) != before):
            raise _reject(db, AdvisoryEnvelopeError(
                ReasonCode.CCX_INPUT_MANIFEST_MISMATCH,
                "Die Beratungsdaten wurden während der Versiegelung geändert. Bitte erneut finalisieren.",
            ), record_id=run.id, stage="fence", **refs, **common)
        # CCX-P2: Abhaengigkeitskanten derselben Lesung (FRESH nur damit).
        for part in after_parts:
            db.add(AdvisoryDependencyEdge(
                id=new_uuid(), tenant_id=tenant_id, envelope_id=envelope_id,
                dependency_kind=part.kind, dependency_object_id=part.object_id,
                dependency_version=part.version, dependency_hash=part.dependency_hash,
                observed_at=now, created_by=user.id,
            ))
        db.flush()
        sealed = db.query(AdvisoryDecisionEnvelope).filter(
            AdvisoryDecisionEnvelope.id == envelope_id,
            AdvisoryDecisionEnvelope.status == "DRAFT",
            AdvisoryDecisionEnvelope.optimistic_version == 1,
            AdvisoryDecisionEnvelope.freshness_status == FRESHNESS_UNKNOWN,
        ).update({
            "status": "SEALED", "canonical_payload_json": canonical, "envelope_hash": digest,
            "sealed_at": now, "sealed_by": user.id, "optimistic_version": 2,
            # Leere Pflicht-Inputgruppe (z. B. keine Ziele, kein Risikoprofil):
            # versiegelt, aber UNKNOWN -- nie FRESH (unknown != fresh).
            "freshness_status": FRESHNESS_UNKNOWN if empty_required_kinds(after_parts) else FRESHNESS_FRESH,
        }, synchronize_session=False)
        if sealed != 1:
            if _draft_invalidated(db, envelope_id):
                raise _reject(db, AdvisoryEnvelopeError(
                    ReasonCode.CCX_INVALIDATION_RACE,
                    "Die Beratungsdaten wurden während der Versiegelung geändert. Bitte erneut finalisieren.",
                ), record_id=run.id, stage="invalidated", audit_field=AUDIT_RACE_REJECTED, **refs, **common)
            raise _reject(db, AdvisoryEnvelopeError(
                ReasonCode.CCX_ENVELOPE_UNSEALED,
                "Der Beratungsentscheid konnte nicht versiegelt werden. Bitte neu laden.",
            ), record_id=run.id, stage="seal", **refs, **common)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        # N-906-03: auch eine CHECK-Verletzung ist ein auditierter Gate-Fehler
        # (F1: CHECK von UNIQUE unterschieden, kein Konflikt-Text fuer CHECK).
        if is_check_constraint_violation(exc):
            raise _reject(db, AdvisoryEnvelopeError(
                ReasonCode.CCX_ENVELOPE_UNSEALED,
                "Der Beratungsentscheid verletzt eine Datenbankregel und wurde nicht versiegelt.",
                http_status=422,
            ), record_id=run.id, stage="check", **refs, **common) from exc
        if "CCX_INVALIDATION_RACE" in str(exc):
            raise _reject(db, AdvisoryEnvelopeError(
                ReasonCode.CCX_INVALIDATION_RACE,
                "Die Beratungsdaten wurden parallel geändert. Bitte erneut finalisieren.",
            ), record_id=run.id, stage="race", audit_field=AUDIT_RACE_REJECTED, **refs, **common) from exc
        raise _reject(db, AdvisoryEnvelopeError(
            ReasonCode.CCX_ENVELOPE_UNSEALED,
            "Der Beratungsentscheid wurde parallel versiegelt. Bitte neu laden.",
        ), record_id=run.id, stage="race", **refs, **common) from exc
    except AdvisoryEnvelopeError:
        raise
    except DBAPIError as exc:
        db.rollback()
        logger.warning("CCX-P1: Versiegelung von der Datenbank abgelehnt | mandate=%s: %s", mandate.id, exc)
        if "CCX_INVALIDATION_RACE" in str(exc):
            raise _reject(db, AdvisoryEnvelopeError(
                ReasonCode.CCX_INVALIDATION_RACE,
                "Die Beratungsdaten wurden parallel geändert. Bitte erneut finalisieren.",
            ), record_id=run.id, stage="race", audit_field=AUDIT_RACE_REJECTED, **refs, **common) from exc
        if "CCX_FRESHNESS_UNKNOWN" in str(exc):
            raise _reject(db, AdvisoryEnvelopeError(
                ReasonCode.CCX_FRESHNESS_UNKNOWN,
                "Der Beratungsentscheid kann ohne Abhängigkeitskanten nicht als aktuell versiegelt werden.",
            ), record_id=run.id, stage="freshness", **refs, **common) from exc
        raise _reject(db, AdvisoryEnvelopeError(
            ReasonCode.CCX_ENVELOPE_UNSEALED,
            "Der Beratungsentscheid konnte nicht versiegelt werden.",
        ), record_id=run.id, stage="database", **refs, **common) from exc

    user_name = getattr(user, "full_name", None) or getattr(user, "username", "")
    if predecessor is not None:
        log(db, user_id=user.id, user_name=user_name, table_name=AUDIT_TABLE, record_id=predecessor.id,
            action="UPDATE", field_name=AUDIT_SUPERSEDED,
            new_value=_audit_value(envelope_hash=predecessor.envelope_hash, successor=envelope_id,
                                   successor_hash=digest),
            mandate_id=mandate.id, client_id=getattr(mandate, "client_id", None),
            ip_address=ip_address, tenant_id=tenant_id)
    log(db, user_id=user.id, user_name=user_name, table_name=AUDIT_TABLE, record_id=envelope_id,
        action="CREATE", field_name=AUDIT_SEALED,
        new_value=_audit_value(envelope_hash=digest, manifest_hash=manifest_digest, run=run.id,
                               predecessor=predecessor.id if predecessor is not None else None,
                               valuation_hash=snapshot.snapshot_hash, fx_basis_hash=snapshot.fx_basis_hash,
                               coverage=snapshot.coverage_status, ledger_hash=ledger_digest,
                               manual_attested=snapshot.manual_valuation_attested,
                               manual_max_age_days=snapshot.manual_valuation_max_age_days),
        mandate_id=mandate.id, client_id=getattr(mandate, "client_id", None),
        ip_address=ip_address, tenant_id=tenant_id)
    return db.query(AdvisoryDecisionEnvelope).filter(AdvisoryDecisionEnvelope.id == envelope_id).one()


# ── Lesen und pruefen ────────────────────────────────────────────────────────


def envelope_view(envelope: AdvisoryDecisionEnvelope) -> dict[str, Any]:
    payload = parse_canonical(envelope.canonical_payload_json, ENVELOPE_PAYLOAD_SCHEMA)
    return {
        "envelope_id": envelope.id,
        "schema_version": envelope.schema_version,
        "status": envelope.status,
        "mandate_id": envelope.mandate_id,
        "envelope_hash": envelope.envelope_hash,
        "predecessor_id": envelope.predecessor_id,
        "predecessor_envelope_hash": payload["predecessor_envelope_hash"],
        "effective_input_manifest_hash": payload["effective_input_manifest_hash"],
        "rounding_policy_version": payload["rounding_policy_version"],
        "locale": envelope.locale,
        "base_currency": envelope.base_currency,
        "sealed_at": envelope.sealed_at,
        "sealed_by": envelope.sealed_by,
        "optimistic_version": envelope.optimistic_version,
        "freshness_status": envelope.freshness_status,
        "stale_at": envelope.stale_at,
        "stale_reason_code": envelope.stale_reason_code,
        "bindings": [
            {name: item[name] for name in (
                "binding_kind", "ordinal", "object_type", "object_id", "object_version", "child_hash",
            )}
            for item in payload["bindings"]
        ],
    }


def verify_envelope(
    db: Session, envelope: AdvisoryDecisionEnvelope,
) -> tuple[str, str] | None:
    """Integritaet einer Envelope-Zeile samt Bindungen und Manifest."""
    bindings = db.query(AdvisoryEnvelopeBinding).filter(
        AdvisoryEnvelopeBinding.tenant_id == envelope.tenant_id,
        AdvisoryEnvelopeBinding.envelope_id == envelope.id,
    ).all()
    manifest_ids = [b.object_id for b in bindings if b.binding_kind == MANIFEST_BINDING_KIND]
    manifest = None
    if len(manifest_ids) == 1:
        manifest = db.query(AdvisoryEffectiveInputManifest).filter(
            AdvisoryEffectiveInputManifest.tenant_id == envelope.tenant_id,
            AdvisoryEffectiveInputManifest.id == manifest_ids[0],
        ).first()
    return envelope_integrity_defect(envelope, bindings, manifest)


def _integrity_reason(code: str) -> ReasonCode:
    """Katalogisierter Reason-Code eines Integritaetsbefunds (statisch
    aufloesbar fuer den Katalogvertrag)."""
    if code == ReasonCode.CCX_ENVELOPE_UNSEALED:
        return ReasonCode.CCX_ENVELOPE_UNSEALED
    if code == ReasonCode.CCX_ENVELOPE_HASH_MISMATCH:
        return ReasonCode.CCX_ENVELOPE_HASH_MISMATCH
    if code == ReasonCode.CCX_BINDING_MISSING:
        return ReasonCode.CCX_BINDING_MISSING
    return ReasonCode.CCX_INPUT_MANIFEST_MISMATCH


def current_verified_envelope(
    db: Session, *, mandate: Any, user: Any, ip_address: str | None = None,
) -> dict[str, Any]:
    """Aktueller versiegelter Entscheid des Mandats, integritaetsgeprueft.

    Kein Fallback: fehlt er, ist er nicht versiegelt oder bricht eine Kette,
    endet der Aufruf mit dem katalogisierten Reason-Code (Integritaetsbrueche
    zusaetzlich mit Audit ``ccx.envelope.rejected``)."""
    tenant_id = mandate_tenant(mandate)
    envelope = current_sealed_envelope(db, tenant_id, str(mandate.id)) if tenant_id else None
    if envelope is None:
        raise AdvisoryEnvelopeError(
            ReasonCode.CCX_ENVELOPE_MISSING,
            "Für dieses Mandat liegt kein versiegelter Beratungsentscheid vor.",
            http_status=404,
        )
    defect = verify_envelope(db, envelope)
    if defect is not None:
        code, detail = defect
        logger.error("CCX-P1: Envelope-Integrität verletzt | envelope=%s code=%s detail=%s",
                     envelope.id, code, detail)
        raise _reject(db, AdvisoryEnvelopeError(
            _integrity_reason(code),
            "Der versiegelte Beratungsentscheid ist nicht mehr integer und darf nicht verwendet werden.",
            extra={"envelope_id": envelope.id},
        ), user=user, mandate=mandate, tenant_id=tenant_id, ip_address=ip_address, record_id=envelope.id,
            envelope_hash=envelope.envelope_hash, detail=detail)
    assert_envelope_fresh(db, envelope=envelope, mandate=mandate, user=user, ip_address=ip_address)
    return envelope_view(envelope)


# ── CCX-P2: Frische, Wettlauf, Gate ──────────────────────────────────────────


def lock_mandate_row(db: Session, mandate_id: str) -> None:
    """PostgreSQL: Mandatszeile fuer die Transaktion sperren (dieselbe Sperre
    wie Finalisierung und Mutation Hook). SQLite serialisiert Schreiber
    ohnehin; dort ist das ein No-op."""
    bind = db.get_bind()
    if str(getattr(getattr(bind, "dialect", None), "name", "")).startswith("postgresql"):
        db.execute(text("SELECT id FROM mandates WHERE id = :mandate_id FOR UPDATE"), {"mandate_id": mandate_id})


def lock_bound_reference_rows(db: Session, *, run: Any, target_allocation: Any) -> None:
    """PostgreSQL: Referenzzeilen eines entstehenden Entscheids ``FOR SHARE``
    sperren (SQLite: Schreiber serialisiert, No-op)."""
    bind = db.get_bind()
    if not str(getattr(getattr(bind, "dialect", None), "name", "")).startswith("postgresql"):
        return
    cma_id = getattr(run, "capital_market_assumptions_id", None) or getattr(
        target_allocation, "capital_market_assumptions_id", None,
    )
    policy_id = getattr(target_allocation, "policy_id", None) or getattr(run, "policy_id", None)
    cma_policy_id = getattr(run, "cma_policy_row_id", None)
    for sql, value in (
        ("SELECT id FROM capital_market_assumptions WHERE id = :v ORDER BY id FOR SHARE", cma_id),
        ("SELECT id FROM optimizer_policies WHERE id = :v ORDER BY id FOR SHARE", policy_id),
        ("SELECT id FROM house_matrix WHERE policy_id = :v ORDER BY id FOR SHARE", policy_id),
        ("SELECT id FROM building_blocks WHERE policy_id = :v ORDER BY id FOR SHARE", policy_id),
        ("SELECT id FROM cma_policies WHERE id = :v ORDER BY id FOR SHARE", cma_policy_id),
        ("SELECT id FROM cma_policy_components WHERE policy_row_id = :v ORDER BY id FOR SHARE", cma_policy_id),
        ("SELECT id FROM cma_policy_approvals WHERE policy_row_id = :v ORDER BY id FOR SHARE", cma_policy_id),
    ):
        if value:
            db.execute(text(sql), {"v": str(value)})


def _draft_invalidated(db: Session, envelope_id: str) -> bool:
    """True, wenn der Mutation Hook den entstehenden DRAFT invalidiert hat
    (STALE oder Version != 1) oder er verschwunden ist (fail-closed)."""
    row = db.execute(text(
        "SELECT freshness_status, optimistic_version FROM advisory_decision_envelopes WHERE id = :envelope_id"
    ), {"envelope_id": envelope_id}).first()
    return row is None or row[0] == FRESHNESS_STALE or int(row[1]) != 1


def dependency_is_current(bound: str | None, current: str | None) -> bool:
    """Eine gebundene Abhaengigkeit ist nur aktuell, wenn beide Seiten bekannt
    und gleich sind (unknown != current)."""
    return bool(bound) and bool(current) and str(bound) == str(current)


def goal_binding_is_current(envelope: Any, current_goals_hash: str | None) -> bool:
    """CCX-01: eine Zieländerung macht den bisherigen Entscheid nicht-aktuell.

    ``envelope`` traegt den beim Siegel gebundenen Ziel-Hash
    (``goal_schedule_hash`` oder ``goals_hash``); fehlt er oder ist der
    aktuelle Hash unbekannt, ist die Bindung nicht aktuell."""
    bound = None
    if isinstance(envelope, dict):
        bound = envelope.get("goal_schedule_hash") or envelope.get("goals_hash")
    else:
        bound = getattr(envelope, "goal_schedule_hash", None) or getattr(envelope, "goals_hash", None)
    return dependency_is_current(bound, current_goals_hash)


def envelope_freshness_status(envelope: Any) -> dict[str, Any]:
    """Serverstatus der Frische (fuer Anzeige; keine Neuberechnung)."""
    return {
        "envelope_id": envelope.id,
        "envelope_hash": envelope.envelope_hash,
        "freshness_status": envelope.freshness_status,
        "stale_at": envelope.stale_at,
        "stale_reason_code": envelope.stale_reason_code,
        "optimistic_version": envelope.optimistic_version,
    }


def _invalidate_drift(db: Session, envelope: Any, drift: list[tuple[Any, Any]], user: Any) -> None:
    """Pull-Pruefung fand Abweichungen: Ereignisse + STALE im eigenen Commit,
    je Ereignis ``ccx.envelope.invalidated``."""
    connection = db.connection()
    actor = getattr(user, "id", None) or db.info.get(ACTOR_INFO_KEY)
    user_name = getattr(user, "full_name", None) or getattr(user, "username", "") or "system"
    for edge, part in drift:
        sequence = mark_envelope_stale(
            connection, envelope_id=envelope.id, tenant_id=envelope.tenant_id, mandate_id=envelope.mandate_id,
            source_kind=edge.dependency_kind, source_object_id=edge.dependency_object_id,
            old_hash=edge.dependency_hash, new_hash=getattr(part, "dependency_hash", None), actor=actor,
        )
        if sequence is None:
            continue
        log(db, user_id=str(actor or "system"), user_name=user_name, table_name=AUDIT_TABLE,
            record_id=envelope.id, action="UPDATE", field_name=AUDIT_INVALIDATED,
            new_value=_audit_value(
                ReasonCode.CCX_INPUT_STALE, invalidation_sequence=sequence, source_kind=edge.dependency_kind,
                source_object=edge.dependency_object_id, operation="gate_drift",
                old_hash=edge.dependency_hash, new_hash=getattr(part, "dependency_hash", None),
            ),
            mandate_id=envelope.mandate_id, tenant_id=envelope.tenant_id)
    db.commit()


def decision_signed(db: Session, envelope: Any) -> bool:
    """Ist der Entscheid vom Kunden unterzeichnet (signiertes, nicht geloeschtes
    Dokument an seiner Soll-Allokation)? Siehe ``models.snapshots.SIGNED_DECISION_SQL``."""
    return bool(db.execute(text(
        f"SELECT CASE WHEN {signed_decision_sql(db.connection())} THEN 1 ELSE 0 END "
        "FROM advisory_decision_envelopes e WHERE e.id = :envelope_id"
    ), {"envelope_id": envelope.id}).scalar())


def envelope_freshness_defect(
    db: Session, envelope: AdvisoryDecisionEnvelope, *, mandate: Any, user: Any = None, persist: bool = True,
) -> tuple[ReasonCode, str] | None:
    """Wie ``pull_freshness``; mit ``persist`` schreibt eine Abweichung Ereignis
    + STALE (eigener Commit). Konsumenten im Lesepfad (Bericht, Cache,
    Veraltet-Hinweis) pruefen ohne zu schreiben."""
    code, detail, drift = pull_freshness(db, envelope, mandate=mandate)
    if drift and persist:
        _invalidate_drift(db, envelope, drift, user)
    return None if code is None else (code, detail)


def persist_freshness_drift(db: Session, envelope: Any, drift: list, user: Any) -> None:
    """Abweichungen einer zuvor lesenden Pull-Pruefung festschreiben (eigener
    Commit), z. B. nach einer Archiv-Ablehnung."""
    if drift:
        _invalidate_drift(db, envelope, drift, user)


def sealed_envelope_for_allocation(db: Session, *, mandate_id: str, target_allocation_id: str):
    """Versiegelter Entscheid, der genau diese Soll-Allokation bindet."""
    return db.query(AdvisoryDecisionEnvelope).join(
        AdvisoryEnvelopeBinding,
        (AdvisoryEnvelopeBinding.envelope_id == AdvisoryDecisionEnvelope.id)
        & (AdvisoryEnvelopeBinding.tenant_id == AdvisoryDecisionEnvelope.tenant_id),
    ).filter(
        AdvisoryDecisionEnvelope.mandate_id == str(mandate_id),
        AdvisoryDecisionEnvelope.status == "SEALED",
        AdvisoryEnvelopeBinding.binding_kind == "target_allocation",
        AdvisoryEnvelopeBinding.object_id == str(target_allocation_id),
    ).first()


def decision_freshness_for_allocation(
    db: Session, *, mandate: Any, target_allocation_id: str | None,
) -> tuple[ReasonCode | None, Any, list]:
    """N-908-01: Frische des Entscheids zu einer Soll-Allokation inkl. Pull-
    Pruefung der Kanten, ohne zu schreiben. Rueckgabe ``(code, envelope,
    drift)``; ``code`` None = kein Entscheid oder FRESH."""
    if not target_allocation_id:
        return None, None, []
    envelope = sealed_envelope_for_allocation(
        db, mandate_id=str(mandate.id), target_allocation_id=str(target_allocation_id),
    )
    if envelope is None:
        return None, None, []
    code, _detail, drift = pull_freshness(db, envelope, mandate=mandate)
    return code, envelope, drift


def pull_freshness(
    db: Session, envelope: AdvisoryDecisionEnvelope, *, mandate: Any,
) -> tuple[ReasonCode | None, str, list]:
    """Frische eines versiegelten Entscheids vor der Auslieferung.

    STALE -> ``CCX_INPUT_STALE``; UNKNOWN, fehlende Kanten oder eine neue,
    ungebundene Abhaengigkeitsart -> ``CCX_FRESHNESS_UNKNOWN``. FRESH wird
    zusaetzlich gegen die aktuellen Objekte geprueft (zweite Linie hinter dem
    Mutation Hook, z. B. fuer globale Referenzdaten anderer Mandanten): jede
    Abweichung liefert ``CCX_INPUT_STALE`` samt Liste ``drift`` (diese
    Funktion schreibt nichts; ``envelope_freshness_defect``/
    ``persist_freshness_drift`` halten sie als Ereignis + STALE fest). Bei einem
    unterzeichneten Entscheid zaehlen Abweichungen der Hausmeinung (CMA/Policy/
    Benchmark) nicht. Eine Rueckkehr zu A macht einen STALE-Entscheid nie
    wieder FRESH -- dafuer braucht es eine neue Versiegelung."""
    if envelope.freshness_status == FRESHNESS_STALE:
        return ReasonCode.CCX_INPUT_STALE, f"stale_reason={envelope.stale_reason_code}", []
    if envelope.freshness_status != FRESHNESS_FRESH:
        return ReasonCode.CCX_FRESHNESS_UNKNOWN, "freshness=unknown", []
    edges = db.query(AdvisoryDependencyEdge).filter(
        AdvisoryDependencyEdge.tenant_id == envelope.tenant_id,
        AdvisoryDependencyEdge.envelope_id == envelope.id,
    ).all()
    if not edges:
        return ReasonCode.CCX_FRESHNESS_UNKNOWN, "edges=none", []
    bound = {b.binding_kind: b.object_id for b in db.query(AdvisoryEnvelopeBinding).filter(
        AdvisoryEnvelopeBinding.tenant_id == envelope.tenant_id,
        AdvisoryEnvelopeBinding.envelope_id == envelope.id,
    ).all()}
    run = db.query(RecommendationRun).filter(
        RecommendationRun.id == str(bound.get("recommendation_run") or ""),
    ).first()
    ta = db.query(TargetAllocation).filter(
        TargetAllocation.id == str(bound.get("target_allocation") or ""),
    ).first()
    if run is None or ta is None:
        return ReasonCode.CCX_FRESHNESS_UNKNOWN, "bound_objects=missing", []
    current_parts = collect_dependency_parts(db, mandate=mandate, run=run, target_allocation=ta)
    current = {part.kind: part for part in current_parts}
    allow_legacy = legacy_projection_allowed(getattr(envelope, "sealed_at", None))
    edge_kinds = {edge.dependency_kind for edge in edges}
    unbound = sorted(set(current) - edge_kinds)
    drift = [
        (edge, current.get(edge.dependency_kind)) for edge in edges
        if current.get(edge.dependency_kind) is None
        or current[edge.dependency_kind].object_id != edge.dependency_object_id
        # Heutige Projektion oder -- nur fuer Altsiegel (KN4-B N-917R3-06) --
        # Uebergangs-Hash frueherer Projektionen (KN-B Beruf, KN3-B
        # Mandantengrenze); unknown ist nie current.
        or not current[edge.dependency_kind].accepts(edge.dependency_hash, allow_legacy=allow_legacy)
    ]
    if drift and any(edge.dependency_kind in REFERENCE_KINDS for edge, _part in drift) \
            and decision_signed(db, envelope):
        # Unterzeichneter Entscheid: die Hausmeinung (CMA/Policy/Benchmark)
        # wirkt nicht zurueck (Strategietreue, kein Rebalancing).
        drift = [(edge, part) for edge, part in drift if edge.dependency_kind not in REFERENCE_KINDS]
    if drift:
        kinds = ",".join(sorted(edge.dependency_kind for edge, _part in drift))
        return ReasonCode.CCX_INPUT_STALE, f"drift={kinds}", drift
    if unbound:
        return ReasonCode.CCX_FRESHNESS_UNKNOWN, "unbound=" + ",".join(unbound), []
    empty = empty_required_kinds(current_parts)
    if empty:
        return ReasonCode.CCX_FRESHNESS_UNKNOWN, "empty=" + ",".join(empty), []
    return None, "", []


def _freshness_reason(code: str) -> ReasonCode:
    """Katalogisierter Reason-Code eines Frischebefunds (statisch aufloesbar)."""
    if code == ReasonCode.CCX_INPUT_STALE:
        return ReasonCode.CCX_INPUT_STALE
    return ReasonCode.CCX_FRESHNESS_UNKNOWN


def assert_envelope_fresh(
    db: Session,
    *,
    envelope: AdvisoryDecisionEnvelope,
    mandate: Any,
    user: Any,
    ip_address: str | None = None,
    channel: str = "api",
) -> None:
    """Gate: ein nicht FRESHer Entscheid wird nie kundenwirksam ausgeliefert
    (kein Fallback auf einen aelteren). Ablehnung mit Reason-Code und Audit
    ``ccx.envelope.rejected`` (Rollback, Tenant-Kontext wieder gesetzt)."""
    defect = envelope_freshness_defect(db, envelope, mandate=mandate, user=user)
    if defect is None:
        return
    code, detail = defect
    status = envelope_freshness_status(envelope)
    reason = _freshness_reason(code)
    message = (
        "Der Beratungsentscheid ist veraltet: Beratungsdaten wurden seit der Versiegelung geändert. "
        "Bitte neu berechnen und finalisieren."
        if reason == ReasonCode.CCX_INPUT_STALE
        else "Die Aktualität des Beratungsentscheids ist nicht belegt. Bitte neu berechnen und finalisieren."
    )
    raise _reject(db, AdvisoryEnvelopeError(
        reason, message, http_status=409,
        extra={"envelope_id": status["envelope_id"], "freshness_status": status["freshness_status"],
               "stale_at": status["stale_at"], "stale_reason_code": status["stale_reason_code"]},
    ), user=user, mandate=mandate, tenant_id=envelope.tenant_id, ip_address=ip_address,
        record_id=status["envelope_id"], envelope_hash=status["envelope_hash"], channel=channel, detail=detail)


def current_envelope_freshness(db: Session, *, mandate: Any) -> dict[str, Any]:
    """Frische-Status des aktuellen versiegelten Entscheids (Anzeige). Kein
    Fallback; fehlt der Entscheid -> ``CCX_ENVELOPE_MISSING`` (404)."""
    tenant_id = mandate_tenant(mandate)
    envelope = current_sealed_envelope(db, tenant_id, str(mandate.id)) if tenant_id else None
    if envelope is None:
        raise AdvisoryEnvelopeError(
            ReasonCode.CCX_ENVELOPE_MISSING,
            "Für dieses Mandat liegt kein versiegelter Beratungsentscheid vor.",
            http_status=404,
        )
    events = db.query(
        AdvisoryInvalidationEvent.invalidation_sequence, AdvisoryInvalidationEvent.source_kind,
    ).filter(
        AdvisoryInvalidationEvent.tenant_id == envelope.tenant_id,
        AdvisoryInvalidationEvent.envelope_id == envelope.id,
    ).order_by(AdvisoryInvalidationEvent.invalidation_sequence).all()
    sequences = [row[0] for row in events]
    # KN-B / E2E2-05: konkrete Ursache(n) je Abhaengigkeitsart (ohne Duplikate).
    causes: list[dict] = []
    for _sequence, kind in events:
        cause = freshness_cause(str(kind or ""))
        if cause not in causes:
            causes.append(cause)
    return {
        **envelope_freshness_status(envelope),
        "invalidation_count": len(sequences),
        "last_invalidation_sequence": max(sequences) if sequences else None,
        "causes": causes,
    }


def current_input_manifest_hash(db: Session, *, mandate: Any, run: Any) -> str:
    """Manifest-Hash der aktuell wirkenden Inputs eines Laufs -- der beim
    Start einer Berechnung festzuhaltende Wert fuer ``expected_manifest_hash``
    (CCX-P2: ein verspaetetes Ergebnis wird nur publiziert, wenn er beim
    Commit unveraendert ist)."""
    tenant_id = mandate_tenant(mandate)
    ta = db.query(TargetAllocation).filter(
        TargetAllocation.id == str(getattr(run, "target_allocation_id", "") or ""),
        TargetAllocation.mandate_id == str(mandate.id),
    ).first()
    components = collect_effective_input_components(db, mandate=mandate, run=run, target_allocation=ta)
    return compute_manifest_hash(build_manifest_record(
        tenant_id=tenant_id or "unbound", mandate_id=str(mandate.id), components=components, run=run,
        target_allocation=ta,
    ))


def _invalidation_audit_sink(session: Session, pending: list[dict[str, Any]]) -> None:
    """``ccx.envelope.invalidated`` je Ereignis des Mutation Hooks, im selben
    Commit (nur IDs, Codes, Hashes)."""
    for item in pending:
        log(session, user_id=item["actor"], user_name=item["actor"], table_name=AUDIT_TABLE,
            record_id=item["envelope_id"], action="UPDATE", field_name=AUDIT_INVALIDATED,
            new_value=_audit_value(
                ReasonCode.CCX_INPUT_STALE, invalidation_sequence=item["invalidation_sequence"],
                source_kind=item["source_kind"], source_table=item["source_table"],
                source_object=item["source_object_id"], operation=item["operation"],
                old_hash=item["old_hash"], new_hash=item["new_hash"],
            ),
            mandate_id=item["mandate_id"], tenant_id=item["tenant_id"])


register_invalidation_audit_sink(_invalidation_audit_sink)


def rollback_keeping_tenant(db: Session) -> None:
    """Rollback und Tenant-Kontext wieder setzen (N-884-09) -- dieselbe Regel
    wie im Siegel; Fassade fuer den P4-Publish-Gate (ohne eigene Kante auf
    ``services.tenant_context``)."""
    restore_tenant_after_rollback(db, set_tenant_context)


def reapply_tenant_context(db: Session) -> None:
    """Den Mandantenkontext der Session erneut setzen (z. B. nach einem
    Commit, wenn die PostgreSQL-Verbindung zurueckgesetzt wurde)."""
    set_tenant_context(db, db.info.get("tenant_id"))


__all__ = [
    "reapply_tenant_context",
    "rollback_keeping_tenant",
    "AUDIT_INVALIDATED",
    "AUDIT_RACE_REJECTED",
    "AUDIT_REJECTED",
    "AUDIT_SEALED",
    "AUDIT_SUPERSEDED",
    "AdvisoryEnvelopeError",
    "advisory_report_cache_scope",
    "assert_envelope_fresh",
    "current_envelope_freshness",
    "current_input_manifest_hash",
    "current_sealed_envelope",
    "current_verified_envelope",
    "decision_freshness_for_allocation",
    "decision_signed",
    "lock_bound_reference_rows",
    "persist_freshness_drift",
    "pull_freshness",
    "sealed_envelope_for_allocation",
    "dependency_is_current",
    "envelope_freshness_defect",
    "envelope_freshness_status",
    "envelope_view",
    "goal_binding_is_current",
    "lock_mandate_row",
    "mandate_tenant",
    "seal_advisory_envelope",
    "verify_envelope",
]
