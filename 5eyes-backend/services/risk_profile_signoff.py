"""RiskProfileSignoffV1 -- append-only, gehashter Nachweis jeder Signatur des
Risikoprofils (RISK-PROFILE-SIGNOFF-001, Codex-Closure-Review zu PR #657 vom
2026-10-20, docs/audits/2026-10-20-risk-override-signoff-pr657-closure-
review.md).

Vorher setzte ``sign_risk_profile()`` nur ``client_signed_at/_method/_ref``
direkt am Assessment:

* ein spaeterer Override/Re-Override aenderte das wirksame Profil, liess die
  alte Signatur aber stehen (Restbefund A);
* die Signatur pruefte die aktuelle Override-Decision nicht und band weder
  Decision-ID noch -Hash -- das Audit-Event trug nur den String
  ``advisor_recorded`` (Restbefund B).

Jetzt:

* jede Signatur = eine unveraenderliche Zeile in ``risk_profile_signoffs``
  mit Assessment-Version, wirksamem Score/Profil, verifizierter Decision
  (ID + Hash) bzw. ausdruecklich ``no_override``, Input-Hash, optional
  Dokument-Hash, Akteur, Methode/Beweisniveau, Zeitpunkt, Regelversion und
  SHA-256 ueber den kanonischen Snapshot;
* der Signaturpfad prueft Decision-Evidence fail-closed (409 vor jeder
  Mutation, jedem Audit-Eintrag und jeder Cache-Invalidierung) und schreibt
  per Compare-and-Swap auf Assessment-Version, Decision- und Signoff-Pointer;
* ein Override/Re-Override setzt im selben CAS die Signatur-Projektion
  zurueck und ``signoff_status='signature_required'`` (siehe
  ``invalidation_values()``); der alte Signoff bleibt als historische
  Evidence stehen;
* Response, Audit, AdvisoryLog, Strategie-Meldung, Risikoprofil- und
  Beratungsprotokoll-PDF lesen dieselbe Referenz (``build_signoff_view``).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from services.audit import log

SCHEMA_VERSION = "RiskProfileSignoffV1"
RULES_VERSION = "RISK-PROFILE-SIGNOFF-001@2026-10-20"

STATUS_SIGNED = "signed"
STATUS_SIGNATURE_REQUIRED = "signature_required"
STATUS_LEGACY_UNBOUND = "legacy_unbound"
# Abgeleitete Zustaende (nie persistiert):
STATE_UNSIGNED = "unsigned"
STATE_REMEDIATION_REQUIRED = "remediation_required"

BINDING_DECISION = "decision"
BINDING_NO_OVERRIDE = "no_override"

METHOD_ADVISOR = "advisor_recorded"
METHOD_PORTAL = "portal"
EVIDENCE_BY_METHOD = {
    METHOD_ADVISOR: "advisor_attested",
    METHOD_PORTAL: "client_portal",
}
METHOD_LABELS = {
    METHOD_ADVISOR: "vom Berater erfasst (keine elektronische Kundensignatur)",
    METHOD_PORTAL: "vom Kunden im Kundenportal bestaetigt",
}

STATE_LABELS = {
    STATUS_SIGNED: "Signiert",
    STATUS_SIGNATURE_REQUIRED: "Neue Signatur erforderlich",
    STATUS_LEGACY_UNBOUND: "Altsignatur, nicht an Decision gebunden",
    STATE_UNSIGNED: "Noch nicht signiert",
    STATE_REMEDIATION_REQUIRED: "Signatur gesperrt -- Override ohne verifizierbaren Decision-Nachweis",
}

# Genau diese Felder gehen in den Hash ein. Neue Felder nur mit neuer
# SCHEMA_VERSION (sonst gelten alte Signoffs faelschlich als manipuliert).
HASHED_FIELDS: tuple[str, ...] = (
    "id",
    "schema_version",
    "assessment_id",
    "mandate_id",
    "client_id",
    "assessment_version",
    "sequence_no",
    "previous_signoff_id",
    "effective_score_x10",
    "effective_profile",
    "final_score_x10",
    "final_profile",
    "is_overridden",
    "override_binding",
    "override_decision_id",
    "override_decision_hash",
    "override_rules_version",
    "assessment_input_hash",
    "document_id",
    "document_hash",
    "method",
    "evidence_level",
    "actor_id",
    "actor_role",
    "note",
    "signed_at",
    "rules_version",
)

# Fragebogen-/Ergebnisfelder, die der Input-Hash bindet.
_INPUT_FIELDS: tuple[str, ...] = (
    "id",
    "version",
    "q_income_points",
    "q_obligations_points",
    "q_savings_points",
    "q_wealth_points",
    "risk_capacity_total",
    "risk_capacity_profile",
    "investment_horizon_years",
    "investment_horizon_label",
    "risk_capacity_score_x10",
    "q_investment_goal_points",
    "q_risk_preference_points",
    "q_risk_behavior_points",
    "risk_willingness_total",
    "risk_willingness_profile",
    "risk_willingness_score_x10",
    "final_score_x10",
    "final_profile",
    "knowledge_services_json",
    "knowledge_instruments_json",
    "income_sources_json",
    "assessed_at",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _value(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _sha256(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Hash / Snapshot
# ---------------------------------------------------------------------------


def signoff_payload(signoff: Any) -> dict[str, Any]:
    return {name: _value(signoff, name) for name in HASHED_FIELDS}


def compute_signoff_hash(signoff: Any) -> str:
    return _sha256(signoff_payload(signoff))


def verify_signoff(signoff: Any) -> bool:
    stored = _value(signoff, "signoff_hash")
    return bool(stored) and stored == compute_signoff_hash(signoff)


def signoff_snapshot(signoff: Any, *, decision_verified: bool | None) -> dict[str, Any]:
    """Replaybarer Audit-Snapshot: Payload + signoff_id/-hash + Decision-
    Verifikationsergebnis zum Signaturzeitpunkt."""
    payload = signoff_payload(signoff)
    snapshot: dict[str, Any] = {
        "signoff_id": payload["id"],
        "signoff_hash": _value(signoff, "signoff_hash"),
        "signoff_status": STATUS_SIGNED,
        "effective_profile": payload["effective_profile"],
        "effective_score_x10": payload["effective_score_x10"],
        "override_binding": payload["override_binding"],
        "override_decision_id": payload["override_decision_id"],
        "override_decision_hash": payload["override_decision_hash"],
        "override_decision_verified": decision_verified,
    }
    for key in sorted(payload):
        snapshot.setdefault(key, payload[key])
    return snapshot


def signoff_reference(signoff_id: str | None, signoff_hash: str | None) -> str:
    """Kurzreferenz ``<id> (SHA-256 <erste 12 Hex>)`` -- gleiches Format wie
    services.risk_override_decision.decision_reference."""
    if not signoff_id:
        return ""
    if not signoff_hash:
        return str(signoff_id)
    return f"{signoff_id} (SHA-256 {str(signoff_hash)[:12]})"


def assessment_input_hash(db, assessment: Any) -> str:
    """SHA-256 ueber Fragebogen-Inputs, Ergebnis und Antworten des Assessments."""
    payload: dict[str, Any] = {name: _value(assessment, name) for name in _INPUT_FIELDS}
    answers: list[list[Any]] = []
    if db is not None and _value(assessment, "id"):
        from models.profiling import RiskAssessmentAnswer

        rows = (
            db.query(RiskAssessmentAnswer)
            .filter(RiskAssessmentAnswer.assessment_id == _value(assessment, "id"))
            .all()
        )
        answers = sorted(
            [int(r.question_number or 0), str(r.question_section or ""),
             str(r.answer_label or ""), int(r.answer_points or 0)]
            for r in rows
        )
    payload["answers"] = answers
    return _sha256(payload)


# ---------------------------------------------------------------------------
# Zustand
# ---------------------------------------------------------------------------


def signoff_state(assessment: Any) -> str:
    """Fachlicher Signoff-Zustand eines Assessments (rein, ohne DB).

    signed               -- aktueller RiskProfileSignoffV1 gebunden
    signature_required   -- nach Override/Re-Override neu zu signieren
    legacy_unbound       -- Altsignatur ohne Snapshot (sichtbar, ungebunden)
    remediation_required -- Override ohne Decision-Nachweis; nicht signierbar
    unsigned             -- nie signiert
    """
    status = _value(assessment, "signoff_status")
    if status == STATUS_SIGNED and _value(assessment, "signoff_id"):
        return STATUS_SIGNED
    if status == STATUS_SIGNATURE_REQUIRED:
        return STATUS_SIGNATURE_REQUIRED
    if _value(assessment, "client_signed_at") and not _value(assessment, "signoff_id"):
        return STATUS_LEGACY_UNBOUND
    if int(_value(assessment, "is_overridden") or 0) == 1 and not _value(assessment, "override_decision_id"):
        return STATE_REMEDIATION_REQUIRED
    return STATE_UNSIGNED


def invalidation_values(now: str) -> dict[str, Any]:
    """Werte, mit denen der Override-CAS die aktuelle Signatur atomar
    zuruecksetzt (Schluessel = Spaltenname)."""
    return {
        "client_signed_at": None,
        "client_signed_method": None,
        "client_signed_ref": None,
        "signoff_id": None,
        "signoff_hash": None,
        "signoff_status": STATUS_SIGNATURE_REQUIRED,
    }


def had_signature(assessment: Any) -> bool:
    return bool(_value(assessment, "client_signed_at") or _value(assessment, "signoff_id"))


def invalidation_audit_value(assessment: Any, *, decision_id: str, decision_hash: str) -> str:
    """Audit-Snapshot der Invalidierung inkl. der bisherigen (Alt-)Signatur,
    damit auch eine Altsignatur ohne Snapshot nicht spurlos verschwindet."""
    return json.dumps({
        "signoff_status": STATUS_SIGNATURE_REQUIRED,
        "reason": "override_changed_effective_profile",
        "invalidated_signoff_id": _value(assessment, "signoff_id"),
        "invalidated_signoff_hash": _value(assessment, "signoff_hash"),
        "invalidated_client_signed_at": _value(assessment, "client_signed_at"),
        "invalidated_client_signed_method": _value(assessment, "client_signed_method"),
        "invalidated_client_signed_ref": _value(assessment, "client_signed_ref"),
        "override_decision_id": decision_id,
        "override_decision_hash": decision_hash,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Lesen / Verifizieren
# ---------------------------------------------------------------------------


def resolve_assessment_signoff(db, assessment: Any) -> tuple[str | None, str | None, bool | None, Any]:
    """(signoff_id, signoff_hash, verified, row) fuer den aktuellen Signoff.

    verified ist nur True, wenn die Zeile existiert, zum Assessment gehoert,
    ihr neu berechneter Hash dem gespeicherten UND dem Pointer entspricht und
    sie an dieselbe Assessment-Version und denselben Decision-Pointer
    gebunden ist, den das Assessment jetzt traegt."""
    signoff_id = _value(assessment, "signoff_id")
    pointer_hash = _value(assessment, "signoff_hash")
    if not signoff_id:
        return None, None, None, None
    from models.profiling import RiskProfileSignoff

    row = db.get(RiskProfileSignoff, signoff_id) if db is not None else None
    verified = bool(
        row is not None
        and row.assessment_id == _value(assessment, "id")
        and row.signoff_hash == pointer_hash
        and verify_signoff(row)
        and int(row.assessment_version or 0) == int(_value(assessment, "version") or 0)
        and (row.override_decision_id or None) == (_value(assessment, "override_decision_id") or None)
        and (row.override_decision_hash or None) == (_value(assessment, "override_decision_hash") or None)
    )
    return signoff_id, pointer_hash, verified, row


def build_signoff_view(db, assessment: Any) -> dict[str, Any]:
    """Eine Darstellung fuer API, PDFs und Strategie-Meldung."""
    from services.risk_override_decision import decision_reference, resolve_assessment_decision

    if assessment is None:
        return {"state": STATE_UNSIGNED, "state_label": STATE_LABELS[STATE_UNSIGNED]}
    state = signoff_state(assessment)
    decision_id = decision_hash = None
    decision_verified = None
    if db is not None:
        decision_id, decision_hash, decision_verified = resolve_assessment_decision(db, assessment)
    else:
        decision_id = _value(assessment, "override_decision_id")
        decision_hash = _value(assessment, "override_decision_hash")
    view: dict[str, Any] = {
        "state": state,
        "state_label": STATE_LABELS.get(state, state),
        "assessment_id": _value(assessment, "id"),
        "assessment_version": _value(assessment, "version"),
        "signoff_id": None,
        "signoff_hash": None,
        "signoff_verified": None,
        "signoff_reference": "",
        "signed_at": None,
        "method": None,
        "method_label": None,
        "evidence_level": None,
        "override_binding": None,
        "override_decision_id": None,
        "override_decision_hash": None,
        "decision_reference": "",
        "current_override_decision_id": decision_id,
        "current_override_decision_hash": decision_hash,
        "current_override_decision_verified": decision_verified,
        "legacy_signed_at": None,
        "legacy_method": None,
    }
    if state == STATUS_SIGNED:
        signoff_id, signoff_hash, verified, row = resolve_assessment_signoff(db, assessment)
        view.update({
            "signoff_id": signoff_id,
            "signoff_hash": signoff_hash,
            "signoff_verified": verified,
            "signoff_reference": signoff_reference(signoff_id, signoff_hash),
            "signed_at": _value(assessment, "client_signed_at"),
            "method": _value(assessment, "client_signed_method"),
        })
        if row is not None:
            view.update({
                "signed_at": row.signed_at,
                "method": row.method,
                "evidence_level": row.evidence_level,
                "override_binding": row.override_binding,
                "override_decision_id": row.override_decision_id,
                "override_decision_hash": row.override_decision_hash,
                "decision_reference": decision_reference(
                    row.override_decision_id, row.override_decision_hash,
                ),
            })
        view["method_label"] = METHOD_LABELS.get(view["method"], view["method"])
    elif state == STATUS_LEGACY_UNBOUND:
        view["legacy_signed_at"] = _value(assessment, "client_signed_at")
        view["legacy_method"] = _value(assessment, "client_signed_method")
        view["method_label"] = METHOD_LABELS.get(view["legacy_method"], view["legacy_method"])
    return view


def signoff_view_lines(view: dict[str, Any]) -> list[tuple[str, str]]:
    """(Label, Text)-Zeilen -- identisch in Risikoprofil- und
    Beratungsprotokoll-PDF."""
    state = view.get("state") or STATE_UNSIGNED
    lines: list[tuple[str, str]] = [("Signatur-Status", STATE_LABELS.get(state, state))]
    if state == STATUS_SIGNED:
        signed = str(view.get("signed_at") or "")[:10] or "-"
        lines.append(("Signiert am", f"{signed} · {view.get('method_label') or '-'}"))
        status = (
            "Hash verifiziert"
            if view.get("signoff_verified")
            else "Hash NICHT verifiziert -- Signoff-Nachweis pruefen"
        )
        lines.append((
            "Signoff-Referenz",
            f"{view.get('signoff_id')} · SHA-256 {view.get('signoff_hash') or '-'} · {status}",
        ))
        if view.get("override_binding") == BINDING_DECISION:
            lines.append((
                "Gebundener Override-Entscheid",
                f"{view.get('override_decision_id')} · SHA-256 {view.get('override_decision_hash') or '-'}",
            ))
        else:
            lines.append((
                "Gebundener Override-Entscheid",
                "Kein Override (Fragebogenergebnis signiert)",
            ))
    elif state == STATUS_SIGNATURE_REQUIRED:
        ref = view.get("current_override_decision_id")
        lines.append((
            "Hinweis",
            "Das wirksame Risikoprofil wurde nach der letzten Signatur uebersteuert; "
            "die fruehere Signatur gilt nicht fuer das aktuelle Profil. Eine neue "
            "Signatur ist erforderlich"
            + (f" (Override-Entscheid {ref} · SHA-256 {view.get('current_override_decision_hash') or '-'})."
               if ref else "."),
        ))
    elif state == STATUS_LEGACY_UNBOUND:
        signed = str(view.get("legacy_signed_at") or "")[:10] or "-"
        lines.append((
            "Hinweis",
            f"Altsignatur vom {signed} ({view.get('method_label') or '-'}) ohne "
            "RiskProfileSignoffV1-Snapshot -- nicht an eine Override-Decision gebunden.",
        ))
    elif state == STATE_REMEDIATION_REQUIRED:
        lines.append((
            "Hinweis",
            "Override ohne verifizierbaren Decision-Nachweis (Altbestand). Bitte den "
            "Override neu erfassen, bevor das Risikoprofil signiert wird.",
        ))
    return lines


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------


def _conflict(reason_code: str, message: str, **context) -> None:
    raise HTTPException(
        status_code=409,
        detail={"reason_code": reason_code, "message": message, **context},
    )


def _eq_or_null(column, value):
    return column.is_(None) if value is None else column == value


def record_signoff(
    db,
    *,
    mandate,
    actor,
    method: str,
    note: str | None,
    ip_address: str | None,
    document_id: str | None = None,
    expected_assessment_version: int | None = None,
    expect_override_decision: bool = False,
    expected_override_decision_id: str | None = None,
    expect_signoff: bool = False,
    expected_signoff_id: str | None = None,
) -> dict[str, Any]:
    """Erfasst einen RiskProfileSignoffV1 fuer das aktuelle Assessment.

    Fail-closed: jede Unstimmigkeit (fremde/fehlende/manipulierte Decision,
    Projektion weicht ab, veraltete Erwartungswerte, paralleler Override)
    -> 409 VOR Mutation, Audit-Eintrag und AdvisoryLog. Der Aufrufer
    invalidiert den Report-Cache erst nach erfolgreicher Rueckkehr."""
    from models.clients import Client
    from models.profiling import RiskAssessment, RiskProfileSignoff
    from services.portfolio_engine import _current_risk_assessment_or_none
    from services.risk_assessment_semantics import OVERRIDE_DOCUMENTATION_RULES_VERSION
    from services.risk_override_decision import resolve_assessment_decision

    if method not in EVIDENCE_BY_METHOD:
        raise ValueError(f"Unbekannte Signaturmethode {method!r}")
    mandate_id = mandate.id
    try:
        ra = _current_risk_assessment_or_none(db, mandate_id, for_update=True)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not ra:
        raise HTTPException(status_code=404, detail="Keine aktuelle Risikoprofilierung gefunden")

    assessment_version = int(ra.version or 0)
    if expected_assessment_version is not None and int(expected_assessment_version) != assessment_version:
        _conflict(
            "RISK_ASSESSMENT_VERSION_CONFLICT",
            "Das Risikoprofil wurde inzwischen neu erfasst -- bitte Seite neu laden.",
            assessment_id=ra.id, current_assessment_version=assessment_version,
        )
    if expect_override_decision and expected_override_decision_id != ra.override_decision_id:
        _conflict(
            "RISK_OVERRIDE_DECISION_CONFLICT",
            "Der Override wurde inzwischen geaendert -- bitte Seite neu laden und das "
            "aktuelle Risikoprofil signieren.",
            assessment_id=ra.id, current_override_decision_id=ra.override_decision_id,
        )
    if expect_signoff and expected_signoff_id != ra.signoff_id:
        _conflict(
            "RISK_PROFILE_SIGNOFF_CONFLICT",
            "Die Signatur wurde inzwischen von jemand anderem erfasst -- bitte Seite neu laden.",
            assessment_id=ra.id, current_signoff_id=ra.signoff_id,
        )

    is_overridden = int(ra.is_overridden or 0) == 1
    decision_id, decision_hash, decision_verified = resolve_assessment_decision(db, ra)
    if is_overridden:
        if not decision_id:
            _conflict(
                "RISK_OVERRIDE_DECISION_UNVERIFIABLE",
                "Der Override hat keinen Decision-Nachweis (Altbestand) und kann nicht "
                "signiert werden. Bitte den Override neu erfassen (remediation_required).",
                assessment_id=ra.id, signoff_state=STATE_REMEDIATION_REQUIRED,
            )
        if decision_verified is not True:
            _conflict(
                "RISK_OVERRIDE_DECISION_UNVERIFIABLE",
                "Der Override-Entscheid ist nicht verifizierbar (fehlend, fremd, "
                "manipuliert oder weicht vom wirksamen Profil ab). Keine Signatur erfasst.",
                assessment_id=ra.id, override_decision_id=decision_id,
            )
        if ra.override_score_x10 is None or not ra.override_profile:
            _conflict(
                "RISK_OVERRIDE_DECISION_UNVERIFIABLE",
                "Override-Projektion unvollstaendig -- keine Signatur erfasst.",
                assessment_id=ra.id,
            )
        effective_score = int(ra.override_score_x10)
        effective_profile = str(ra.override_profile)
        binding = BINDING_DECISION
    else:
        if decision_id or ra.override_decision_hash:
            _conflict(
                "RISK_OVERRIDE_DECISION_UNVERIFIABLE",
                "Decision-Pointer ohne aktiven Override -- inkonsistentes Risikoprofil, "
                "keine Signatur erfasst.",
                assessment_id=ra.id, override_decision_id=decision_id,
            )
        effective_score = int(ra.final_score_x10 or 0)
        effective_profile = str(ra.final_profile or "")
        binding = BINDING_NO_OVERRIDE
        decision_id = decision_hash = None
        decision_verified = None

    document_hash = None
    if document_id:
        from models.review import ContractDocument

        doc = db.query(ContractDocument).filter(
            ContractDocument.id == document_id,
            ContractDocument.mandate_id == mandate_id,
            ContractDocument.deleted_at.is_(None),
        ).first()
        if doc is None:
            raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
        document_hash = doc.checksum_sha256 or doc.content_hash
        if not document_hash:
            raise HTTPException(
                status_code=422,
                detail="Das Dokument hat keinen Hash und kann nicht an die Signatur gebunden werden.",
            )

    now = _now()
    previous_signoff_id = ra.signoff_id
    previous_signoff_hash = ra.signoff_hash
    sequence_no = int(
        db.query(func.max(RiskProfileSignoff.sequence_no))
        .filter(RiskProfileSignoff.assessment_id == ra.id)
        .scalar() or 0
    ) + 1
    from database import new_uuid

    signoff = RiskProfileSignoff(
        id=new_uuid(),
        schema_version=SCHEMA_VERSION,
        assessment_id=ra.id,
        mandate_id=mandate_id,
        client_id=mandate.client_id,
        assessment_version=assessment_version,
        sequence_no=sequence_no,
        previous_signoff_id=previous_signoff_id,
        effective_score_x10=effective_score,
        effective_profile=effective_profile,
        final_score_x10=int(ra.final_score_x10 or 0),
        final_profile=ra.final_profile,
        is_overridden=1 if is_overridden else 0,
        override_binding=binding,
        override_decision_id=decision_id,
        override_decision_hash=decision_hash,
        override_rules_version=OVERRIDE_DOCUMENTATION_RULES_VERSION if is_overridden else None,
        assessment_input_hash=assessment_input_hash(db, ra),
        document_id=document_id,
        document_hash=document_hash,
        method=method,
        evidence_level=EVIDENCE_BY_METHOD[method],
        actor_id=actor.id,
        actor_role=getattr(actor, "role", None),
        note=note,
        signed_at=now,
        rules_version=RULES_VERSION,
        created_at=now,
    )
    signoff.signoff_hash = compute_signoff_hash(signoff)
    signed_ref = actor.id if method == METHOD_PORTAL else note

    # Compare-and-Swap auf Version, is_current, Override-Projektion,
    # Decision- und Signoff-Pointer: ein paralleler Override/Re-Override oder
    # eine parallele Signatur zwischen Laden und Schreiben -> 409.
    updated = db.query(RiskAssessment).filter(
        RiskAssessment.id == ra.id,
        RiskAssessment.mandate_id == mandate_id,
        RiskAssessment.deleted_at.is_(None),
        RiskAssessment.is_current == 1,
        RiskAssessment.version == assessment_version,
        RiskAssessment.is_overridden == (1 if is_overridden else 0),
        _eq_or_null(RiskAssessment.override_decision_id, decision_id),
        _eq_or_null(RiskAssessment.override_decision_hash, decision_hash),
        _eq_or_null(RiskAssessment.override_score_x10, ra.override_score_x10),
        _eq_or_null(RiskAssessment.override_profile, ra.override_profile),
        _eq_or_null(RiskAssessment.signoff_id, previous_signoff_id),
        _eq_or_null(RiskAssessment.signoff_hash, previous_signoff_hash),
    ).update({
        RiskAssessment.client_signed_at: now,
        RiskAssessment.client_signed_method: method,
        RiskAssessment.client_signed_ref: signed_ref,
        RiskAssessment.signoff_id: signoff.id,
        RiskAssessment.signoff_hash: signoff.signoff_hash,
        RiskAssessment.signoff_status: STATUS_SIGNED,
        RiskAssessment.updated_at: now,
    }, synchronize_session=False)
    if updated != 1:
        db.rollback()
        _conflict(
            "RISK_PROFILE_SIGNOFF_CONCURRENT_MODIFICATION",
            "Das Risikoprofil wurde waehrend der Signatur geaendert -- bitte Seite neu "
            "laden und das aktuelle Profil signieren.",
            assessment_id=ra.id,
        )

    snapshot = signoff_snapshot(signoff, decision_verified=decision_verified)
    advisory_log_id = None
    try:
        db.add(signoff)
        log(db, user_id=actor.id, user_name=getattr(actor, "full_name", None) or actor.id,
            table_name="risk_assessments", record_id=ra.id, action="UPDATE",
            field_name="client_signed",
            old_value=json.dumps({
                "signoff_id": previous_signoff_id,
                "signoff_hash": previous_signoff_hash,
                "signoff_state": signoff_state(ra),
            }, ensure_ascii=False),
            new_value=json.dumps(snapshot, ensure_ascii=False),
            mandate_id=mandate_id, client_id=mandate.client_id,
            ip_address=ip_address)
        advisor_id = actor.id
        if method == METHOD_PORTAL:
            client = db.get(Client, mandate.client_id)
            advisor_id = getattr(client, "advisor_id", None) or actor.id
        entry = _advisory_log_entry(
            db, mandate=mandate, advisor_id=advisor_id, signoff=signoff,
        )
        advisory_log_id = entry.id
        db.commit()
        db.refresh(ra)
    except IntegrityError:
        db.rollback()
        _conflict(
            "RISK_PROFILE_SIGNOFF_CONCURRENT_MODIFICATION",
            "Eine andere Signatur wurde gleichzeitig gespeichert -- bitte Seite neu laden.",
            assessment_id=ra.id,
        )

    return {
        "risk_assessment_id": ra.id,
        "assessment_version": assessment_version,
        "client_signed_at": now,
        "client_signed_method": method,
        "signoff_id": signoff.id,
        "signoff_hash": signoff.signoff_hash,
        "signoff_status": STATUS_SIGNED,
        "signoff_state": STATUS_SIGNED,
        "signoff_reference": signoff_reference(signoff.id, signoff.signoff_hash),
        "evidence_level": signoff.evidence_level,
        "method_label": METHOD_LABELS[method],
        "effective_profile": effective_profile,
        "effective_score_x10": effective_score,
        "override_binding": binding,
        "override_decision_id": decision_id,
        "override_decision_hash": decision_hash,
        "override_decision_verified": decision_verified,
        "previous_signoff_id": previous_signoff_id,
        "advisory_log_id": advisory_log_id,
    }


def advisory_log_description(signoff: Any) -> str:
    decision_text = (
        f"Override-Entscheid {signoff.override_decision_id} (SHA-256 {signoff.override_decision_hash})"
        if signoff.override_binding == BINDING_DECISION
        else "kein Override (Fragebogenergebnis signiert)"
    )
    return (
        "Systemeintrag RiskProfileSignoffV1: Signatur des Risikoprofils "
        f"'{signoff.effective_profile}' (Assessment {signoff.assessment_id}, "
        f"Version {signoff.assessment_version}) erfasst -- "
        f"{METHOD_LABELS.get(signoff.method, signoff.method)}. "
        f"Signoff {signoff.id} (SHA-256 {signoff.signoff_hash}). "
        f"Gebunden: {decision_text}."
    )


def _advisory_log_entry(db, *, mandate, advisor_id: str, signoff: Any):
    """Beratungsprotokoll-Eintrag mit derselben Signoff-/Decision-Referenz.

    Bewusst ohne erfundene Gespraechsdauer/-kanal (None): der Eintrag
    dokumentiert die erfasste Bestaetigung, kein Beratungsgespraech. Nur eine
    Portal-Bestaetigung zaehlt als Kundensignatur (client_signed=1)."""
    from services.advisory_log_service import create_advisory_log

    is_portal = signoff.method == METHOD_PORTAL
    payload = SimpleNamespace(
        entry_type="Eignungsprüfung",
        title=f"Risikoprofil-Signoff (Version {signoff.assessment_version})",
        description=advisory_log_description(signoff),
        decision=None,
        trigger_id=None,
        recommendation_run_id=None,
        status="Empfohlen",
        client_signed=is_portal,
        client_signed_at=signoff.signed_at if is_portal else None,
        document_id=signoff.document_id,
        entry_date=None,
        entry_datetime=signoff.signed_at,
        duration_minutes=None,
        communication_channel="schriftlich" if is_portal else None,
        language="de",
        location=None,
        participants=[],
        topics=["Risikoprofil", "Eignungsprüfung"],
        risk_warnings_given=[],
        cost_disclosure_given=False,
        conflict_disclosure_ids=[],
        suitability_check_id=None,
    )
    advisor = SimpleNamespace(id=advisor_id)
    return create_advisory_log(db, mandate_id=mandate.id, advisor=advisor, payload=payload)
