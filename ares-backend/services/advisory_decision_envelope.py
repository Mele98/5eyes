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

Jede Ablehnung verwirft die offene Transaktion, setzt den Tenant-Kontext der
Session wieder (H7-Muster, N-884-09) und schreibt einen tenant- und
mandatsgebundenen Audit-Eintrag ``ccx.envelope.rejected`` (IDs und Hashes,
nie Payload); erfolgreiche Versiegelung schreibt ``ccx.envelope.sealed`` und
fuer den Vorgaenger ``ccx.envelope.superseded``. Es gibt keinen Fallback auf
einen aelteren oder unvollstaendigen Entscheid.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

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
    AdvisoryDecisionEnvelope,
    AdvisoryEffectiveInputManifest,
    AdvisoryEnvelopeBinding,
    HoldingsValuationSnapshot,
    PositionDecisionLedger,
)
from services.advisory_cache_scope import advisory_cache_key
from services.advisory_envelope_integrity import MANIFEST_BINDING_KIND, envelope_integrity_defect
from services.advisory_snapshot_transaction import RETRY, classify_snapshot_consistency
from services.audit import log, restore_tenant_after_rollback
from services.effective_input_manifest import build_manifest_record, collect_effective_input_components
from services.tenant_context import set_tenant_context

logger = logging.getLogger(__name__)

AUDIT_TABLE = "advisory_decision_envelopes"
AUDIT_SEALED = "ccx.envelope.sealed"
AUDIT_REJECTED = "ccx.envelope.rejected"
AUDIT_SUPERSEDED = "ccx.envelope.superseded"

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
    """CCX-10: Cache-Scope (tenant, mandate, envelope_hash) des Advisory-Reports."""
    tenant_id = mandate_tenant(mandate) or "unbound"
    row = db.query(AdvisoryDecisionEnvelope.envelope_hash).filter(
        AdvisoryDecisionEnvelope.tenant_id == tenant_id,
        AdvisoryDecisionEnvelope.mandate_id == str(mandate.id),
        AdvisoryDecisionEnvelope.status == "SEALED",
    ).first()
    return advisory_cache_key(tenant_id, str(mandate.id), row[0] if row else None)


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
    **refs: Any,
) -> AdvisoryEnvelopeError:
    """Verwirft offene Aenderungen, setzt den Tenant-Kontext wieder, schreibt
    und committet ``ccx.envelope.rejected`` -- danach wirft der Aufrufer."""
    restore_tenant_after_rollback(db, set_tenant_context)
    log(
        db, user_id=user.id, user_name=getattr(user, "full_name", None) or getattr(user, "username", ""),
        table_name=AUDIT_TABLE, record_id=str(record_id or getattr(mandate, "id", "") or "-"),
        action="CREATE", field_name=AUDIT_REJECTED,
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


# ── Versiegeln ───────────────────────────────────────────────────────────────


VALUATION_BINDING_KIND = "holdings_valuation_snapshot"
LEDGER_BINDING_KIND = "position_decision_ledger"


def _bindings(
    db: Session, *, manifest: AdvisoryEffectiveInputManifest, ta: Any, run: Any,
    valuation: tuple[str, str] | None = None, ledger_hash: str | None = None,
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
    return p3 + [
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
) -> AdvisoryDecisionEnvelope:
    """Erzeugt, bindet und versiegelt den Envelope der finalisierten Empfehlung
    ``run`` (Transaktion des Aufrufers; der Commit folgt dort).

    CCX-P3: vor dem Siegel wird der gesamte Bestand verlustfrei bewertet; nur
    ein COMPLETE-Snapshot (alle Preise/Kurse belegt und frisch, eine FX-Basis)
    wird gebunden, sonst endet die Finalisierung mit dem typisierten Code
    (CCX_VALUATION_* / CCX_FX_BASIS_*) und Audit. Je bestehender Depotposition
    wird ein Entscheid KEEP/SELL/REVIEW im Ledger gebunden."""
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
            "Referenzwaehrung des Mandats fehlt.",
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
            f"nicht vollstaendig belegt ({projection.coverage_status}). Bitte fehlende Preise, Kurse, "
            "Stichtage oder Waehrungen ergaenzen.",
            extra={"coverage_status": projection.coverage_status,
                   "blocker_codes": list(projection.blocker_codes),
                   "valuation_snapshot_hash": projection.snapshot_hash},
        ), record_id=run.id, run=run.id, stage="valuation", coverage=projection.coverage_status,
            blockers=",".join(projection.blocker_codes), valuation_hash=projection.snapshot_hash,
            fx_basis_hash=projection.fx_basis_hash, **common)
    ledger_entries = valuation.ledger_entries
    ledger_digest = valuation.ledger_hash
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
                             valuation=(snapshot.id, snapshot.snapshot_hash), ledger_hash=ledger_digest)
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
                "Nicht jede bestehende Position hat einen Entscheid (Halten/Verkaufen/Pruefen).",
            ), record_id=run.id, stage="ledger", **refs, **common)
        # Snapshot-Fence: dieselben Inputs unmittelbar vor dem Siegel erneut.
        try:
            after = collect_effective_input_components(db, mandate=mandate, run=run, target_allocation=ta)
        except (CanonicalPayloadError, ValueError):
            after = {}  # unbekannt geworden -> nie konsistent (RETRY)
        # CCX-P3: Marktdaten-/Bestandswechsel waehrend des Laufs -> der gebundene
        # Snapshot ist nicht mehr der aktuelle Stand (kein gemischter Stand).
        if not valuation.unchanged(db, mandate):
            raise _reject(db, AdvisoryEnvelopeError(
                ReasonCode.CCX_VALUATION_STALE,
                "Bestand, Preise oder Kurse wurden waehrend der Versiegelung geaendert. Bitte erneut "
                "finalisieren.",
            ), record_id=run.id, stage="valuation_fence", valuation_hash=projection.snapshot_hash, **refs,
                **common)
        if classify_snapshot_consistency(before, after) == RETRY:
            raise _reject(db, AdvisoryEnvelopeError(
                ReasonCode.CCX_INPUT_MANIFEST_MISMATCH,
                "Die Beratungsdaten wurden waehrend der Versiegelung geaendert. Bitte erneut finalisieren.",
            ), record_id=run.id, stage="fence", **refs, **common)
        sealed = db.query(AdvisoryDecisionEnvelope).filter(
            AdvisoryDecisionEnvelope.id == envelope_id,
            AdvisoryDecisionEnvelope.status == "DRAFT",
            AdvisoryDecisionEnvelope.optimistic_version == 1,
        ).update({
            "status": "SEALED", "canonical_payload_json": canonical, "envelope_hash": digest,
            "sealed_at": now, "sealed_by": user.id, "optimistic_version": 2,
        }, synchronize_session=False)
        if sealed != 1:
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
        raise _reject(db, AdvisoryEnvelopeError(
            ReasonCode.CCX_ENVELOPE_UNSEALED,
            "Der Beratungsentscheid wurde parallel versiegelt. Bitte neu laden.",
        ), record_id=run.id, stage="race", **refs, **common) from exc
    except AdvisoryEnvelopeError:
        raise
    except DBAPIError as exc:
        db.rollback()
        logger.warning("CCX-P1: Versiegelung von der Datenbank abgelehnt | mandate=%s: %s", mandate.id, exc)
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
            "Fuer dieses Mandat liegt kein versiegelter Beratungsentscheid vor.",
            http_status=404,
        )
    defect = verify_envelope(db, envelope)
    if defect is not None:
        code, detail = defect
        logger.error("CCX-P1: Envelope-Integritaet verletzt | envelope=%s code=%s detail=%s",
                     envelope.id, code, detail)
        raise _reject(db, AdvisoryEnvelopeError(
            _integrity_reason(code),
            "Der versiegelte Beratungsentscheid ist nicht mehr integer und darf nicht verwendet werden.",
            extra={"envelope_id": envelope.id},
        ), user=user, mandate=mandate, tenant_id=tenant_id, ip_address=ip_address, record_id=envelope.id,
            envelope_hash=envelope.envelope_hash, detail=detail)
    return envelope_view(envelope)


__all__ = [
    "AUDIT_REJECTED",
    "AUDIT_SEALED",
    "AUDIT_SUPERSEDED",
    "AdvisoryEnvelopeError",
    "advisory_report_cache_scope",
    "current_sealed_envelope",
    "current_verified_envelope",
    "envelope_view",
    "mandate_tenant",
    "seal_advisory_envelope",
    "verify_envelope",
]
