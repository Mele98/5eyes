"""CCX P5: Kanal-Gate ueber den versiegelten Beratungsentscheid (Vertrag §8).

Jede kundengerichtete Zahl (Kunden-PDF, Signatur, Vor-Ort-Signatur, Handoff)
kommt aus genau EINEM versiegelten Envelope. Ein Kanal darf nur ausliefern,
wenn

1. die aktuelle Soll-Allokation gueltig publiziert ist -- P4 tief: Envelope
   SEALED, Hash, Integritaet, P2-Frische (``active_publication_state``);
2. die FX-Basis des gebundenen Bewertungs-Snapshots JETZT noch belegt und
   frisch ist (Tenant-Frist; kein Ersatzkurs) -- eine fruehere Ausnahme fuer
   versiegelte Laeufe gibt es nicht mehr (§8.3: ein Live-Neurender prueft
   strikt);
3. der Envelope Parametersatz (M-2) und Zielkennzahl (M-3) bindet und beide
   Hashes heute aus der Soll-Allokation reproduzierbar sind.

Sonst ``409`` mit katalogisiertem Code, verstaendlicher Ursache und Audit
``ccx.channel.blocked`` (Tenant-Kontext nach Rollback wieder gesetzt). Kein
Fallback auf einen aelteren Entscheid.

``record_channel_publication`` schreibt je ausgeliefertem Artefakt die
append-only Kanalzeile (``advisory_channel_publications``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from core.reason_codes import DomainError, ReasonCode
from database import CHANNEL_PUBLICATION_SCHEMA, new_uuid
from models.snapshots import (
    AdvisoryChannelPublication,
    AdvisoryDecisionEnvelope,
    AdvisoryEnvelopeBinding,
    HoldingsValuationSnapshot,
)

CHANNEL_API = "API"
CHANNEL_PDF = "PDF"
CHANNEL_ADVISOR_SIGNATURE = "ADVISOR_SIGNATURE"
CHANNEL_ONSITE_SIGNATURE = "ONSITE_SIGNATURE"
CHANNEL_HANDOFF = "HANDOFF"
CHANNEL_ARCHIVE = "ARCHIVE"
CHANNELS = ("API", "CLASSIC", "REACT", "PDF", "ADVISOR_SIGNATURE", "ONSITE_SIGNATURE", "HANDOFF", "ARCHIVE")
AUDIT_CHANNEL_BLOCKED = "ccx.channel.blocked"
AUDIT_CHANNEL_PUBLISHED = "ccx.channel.published"
CHANNEL_STATUS_PUBLISHED = "PUBLISHED"

_CAUSES: dict[str, str] = {
    ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE.value:
        "Die aktuelle Soll-Allokation ist nicht als Beratungsentscheid publiziert. Bitte finalisieren und publizieren.",
    ReasonCode.CCX_INPUT_STALE.value:
        "Beratungsdaten wurden seit der Versiegelung geändert. Bitte neu berechnen, finalisieren und publizieren.",
    ReasonCode.CCX_FRESHNESS_UNKNOWN.value:
        "Die Aktualität des Beratungsentscheids ist nicht belegt. Bitte neu finalisieren.",
    ReasonCode.CCX_FX_BASIS_STALE.value:
        "Ein Wechselkurs des versiegelten Entscheids ist veraltet. Bitte einen aktuellen Kurs erfassen.",
    ReasonCode.CCX_FX_BASIS_MISSING.value:
        "Für eine Währung des versiegelten Entscheids fehlt ein belegter Wechselkurs. Bitte einen Kurs erfassen.",
    ReasonCode.CCX_FX_BASIS_MISMATCH.value:
        "Der Wechselkurs liegt nach dem Stichtag des Entscheids. Bitte neu finalisieren.",
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
             ReasonCode.CCX_FX_BASIS_MISMATCH.value}


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
    drift: tuple = field(default=(), repr=False, compare=False)

    @property
    def ok(self) -> bool:
        return self.applicable and self.reason_code is None

    @property
    def cause(self) -> str:
        return _CAUSES.get(str(self.reason_code or ""), "Der Beratungsentscheid ist nicht auslieferbar.")

    def footer_ref(self) -> dict[str, str] | None:
        """Envelope-Hash/Version fuer den Fuss jedes Kunden-PDFs."""
        if not self.ok:
            return None
        version = str(self.schema_version or "").rsplit("/", 1)[-1]
        return {"envelope_hash": str(self.envelope_hash), "schema_version": str(self.schema_version),
                "fassung": version}


def _blocked(code: Any, **kw: Any) -> ChannelDecision:
    return ChannelDecision(applicable=True, reason_code=str(getattr(code, "value", code)), **kw)


def evaluate_channel_envelope(db: Session, mandate: Any) -> ChannelDecision:
    """Kanal-Pruefung ohne Schreibwirkung (Reihenfolge: P4, FX, P5-Bindung)."""
    from services.advisory_decision_envelope import (
        GOAL_METRIC_BINDING_KIND,
        PARAMETER_SET_BINDING_KIND,
        VALUATION_BINDING_KIND,
        p5_decision_hashes,
    )
    from services.allocation_publication_gate import (
        _current_fx_findings,
        _fx_basis_findings,
        active_publication_state,
        current_target_allocation,
    )
    from services.goal_metric_contract import GoalMetricUncertified
    from services.risk_parameter_set import ParameterSetMissing

    try:
        ta = current_target_allocation(db, str(mandate.id))
    except ValueError:
        return _blocked(ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE)
    if ta is None:
        return ChannelDecision(applicable=False)
    state = active_publication_state(db, mandate)
    if not state.published:
        code = state.reason_code or ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE
        if str(code) not in _CAUSES:
            code = ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE
        return _blocked(code, envelope_id=state.envelope_id, target_allocation_id=str(ta.id), drift=state.drift)
    envelope = db.get(AdvisoryDecisionEnvelope, str(state.envelope_id))
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
        return _blocked(ReasonCode.CCX_FX_BASIS_MISSING, **base)
    fx = _fx_basis_findings(snapshot) or _current_fx_findings(db, snapshot, envelope.tenant_id)
    if fx:
        return _blocked(fx[0], **base)
    bound_parameter = bindings.get(PARAMETER_SET_BINDING_KIND)
    bound_goal = bindings.get(GOAL_METRIC_BINDING_KIND)
    if bound_parameter is None or bound_goal is None:
        return _blocked(ReasonCode.CCX_CHANNEL_BINDING_MISSING, **base)
    try:
        parameter_hash, goal_hash = p5_decision_hashes(db, mandate=mandate, ta=ta)
    except ParameterSetMissing:
        return _blocked(ReasonCode.CCX_PARAMETER_SET_MISSING, **base)
    except GoalMetricUncertified:
        return _blocked(ReasonCode.CCX_GOAL_METRIC_UNCERTIFIED, **base)
    if parameter_hash != bound_parameter.child_hash:
        return _blocked(ReasonCode.CCX_CHANNEL_HASH_MISMATCH, **base)
    if goal_hash != bound_goal.child_hash:
        return _blocked(ReasonCode.CCX_GOAL_METRIC_MISMATCH, **base)
    try:
        rounding = json.loads(envelope.canonical_payload_json or "{}").get("rounding_policy_version")
    except (TypeError, ValueError):
        rounding = None
    return ChannelDecision(applicable=True, rounding_policy_version=rounding,
                           parameter_set_hash=parameter_hash, goal_metric_payload_hash=goal_hash, **base)


def _audit(db: Session, *, user: Any, mandate: Any, ip_address: str | None, field_name: str,
           record_id: str, **values: Any) -> None:
    from services.advisory_decision_envelope import mandate_tenant
    from services.audit import log

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
            decision = _blocked(ReasonCode.CCX_ALLOCATION_NOT_PUBLISHABLE)
        else:
            return decision
    from services.advisory_decision_envelope import persist_freshness_drift, rollback_keeping_tenant

    blocker = str(decision.reason_code)
    code: str = blocker
    if outdated_code is not None and blocker not in _FX_CODES:
        code = outdated_code.value
    rollback_keeping_tenant(db)
    if decision.drift and decision.envelope_id:
        envelope = db.get(AdvisoryDecisionEnvelope, decision.envelope_id)
        if envelope is not None:
            persist_freshness_drift(db, envelope, list(decision.drift), user)
    _audit(db, user=user, mandate=mandate, ip_address=ip_address, field_name=AUDIT_CHANNEL_BLOCKED,
           record_id=decision.envelope_id or str(mandate.id), reason_code=code, blocker_code=blocker,
           channel=channel, envelope_hash=decision.envelope_hash)
    db.commit()
    raise DomainError(
        code,
        f"Auslieferung gesperrt ({channel}): {decision.cause}",
        http_status=409,
        extra={"channel": channel, "blocker_code": blocker, "cause": decision.cause,
               "envelope_hash": decision.envelope_hash},
    )


def record_channel_publication(
    db: Session, decision: ChannelDecision, *, mandate: Any, channel: str, artifact_id: str,
    channel_payload_hash: str, render_hash: str | None, user: Any,
) -> AdvisoryChannelPublication:
    """Append-only Kanalzeile (idempotent je ``(envelope, channel, artifact)``)."""
    from core.advisory_envelope_codec import utc_now
    from services.goal_metric_contract import GOAL_METRIC_CONTRACT_VERSION
    from services.risk_parameter_set import PARAMETER_CONTRACT_VERSION

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
    from services.advisory_decision_envelope import mandate_tenant

    row = AdvisoryChannelPublication(
        id=new_uuid(), tenant_id=mandate_tenant(mandate), mandate_id=str(mandate.id),
        envelope_id=decision.envelope_id, channel=channel, artifact_id=str(artifact_id),
        schema_version=CHANNEL_PUBLICATION_SCHEMA, channel_payload_hash=channel_payload_hash,
        render_hash=render_hash, rounding_policy_version=str(decision.rounding_policy_version or ""),
        bound_envelope_hash=decision.envelope_hash, parameter_contract_version=PARAMETER_CONTRACT_VERSION,
        parameter_set_hash=decision.parameter_set_hash, goal_metric_contract_version=GOAL_METRIC_CONTRACT_VERSION,
        goal_metric_payload_hash=decision.goal_metric_payload_hash, status=CHANNEL_STATUS_PUBLISHED,
        created_at=utc_now(), created_by=getattr(user, "id", None),
    )
    db.add(row)
    db.flush()
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
        from services.advisory_decision_envelope import rollback_keeping_tenant

        rollback_keeping_tenant(db)
        _audit(db, user=user, mandate=mandate, ip_address=ip_address, field_name=AUDIT_CHANNEL_BLOCKED,
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
    from services.recommendation_release_gate import RECOMMENDATION_DOCUMENT_TYPES

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


__all__ = [
    "DECISION_ARTIFACT_DOCUMENT_TYPES",
    "require_signature_envelope",
    "AUDIT_CHANNEL_BLOCKED",
    "CHANNELS",
    "CHANNEL_ADVISOR_SIGNATURE",
    "CHANNEL_API",
    "CHANNEL_ARCHIVE",
    "CHANNEL_HANDOFF",
    "CHANNEL_ONSITE_SIGNATURE",
    "CHANNEL_PDF",
    "ChannelDecision",
    "artifact_publication",
    "evaluate_channel_envelope",
    "record_channel_publication",
    "require_channel_envelope",
    "require_signable_decision_artifact",
]
