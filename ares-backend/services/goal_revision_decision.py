"""GoalRevisionDecisionV1 -- explizite, replaybare Berater-Entscheidung, ein
Ziel als nachrangiges Wunschziel einzustufen (GOAL-REVISION-DECISION-001,
CIO-Entscheid 2026-10-21 nach Codex-Closure-Review zu PR #655,
docs/audits/2026-10-20-goal-reachability-certificate-pr655-closure-
review.md).

Befund: ein lokales Optimum (Multi-Start-SLSQP) ist kein globaler
Unmoeglichkeitsnachweis. Engine v9/v10 stufte ein hartes Ziel trotzdem
automatisch aus Stufe 1 herab, sobald keine lokale Suche eine Allokation mit
ausreichender Sicherheit fand -- auch wenn eine schmale, zulaessige
Erfolgsinsel zwischen allen Startpunkten lag.

Seit Engine ``saa_resampled_v11``:

* die Engine stuft NIE automatisch herab; ein lokaler Such-Miss ist
  ``not_found_reachable_locally`` (Hinweis + Vorschlag an den Berater);
* herabgestuft (Wunschziel-Gewicht 0.2 + W0-Deckel, nicht Stufe 1) wird
  ausschliesslich ein Ziel mit einer gueltigen GoalRevisionDecisionV1:
  Hash verifiziert, gehoert zum Ziel, und der Ziel-Snapshot-Hash der
  Decision entspricht dem AKTUELLEN Ziel. Jede Zielaenderung (Betrag,
  Termin, Haertegrad, Rang, ...) macht die Decision unwirksam -- das Ziel
  ist wieder ein normales Ziel mit seinem Haertegrad;
* append-only (Trigger gegen UPDATE/DELETE), kein harter FK auf goals/
  mandates (Purge-fest wie risk_override_decisions).

Dieses Modul ist rein (keine DB) bis auf die ausdruecklich markierten
Lade-/Schreibfunktionen am Ende.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from core.evidence import canonical_json, evidence_hash

SCHEMA_VERSION = "GoalRevisionDecisionV1"
RULES_VERSION = "GOAL-REVISION-DECISION-001@2026-10-21"

# Einziger Zielzustand einer Decision (V1). Eine Rueckstufung erfolgt durch
# eine Zielaenderung (Snapshot-Hash wechselt) -- nie durch UPDATE/DELETE.
NEW_STATUS_SUBORDINATE_WISH = "nachrangiges_wunschziel"
NEW_STATUS_LABEL = "nachrangiges Wunschziel"

# Attribut, unter dem ``attach_goal_revision_decisions`` den Decision-
# Snapshot an das (geladene) Ziel haengt; die Engine liest nur dieses.
GOAL_ATTRIBUTE = "goal_revision_decision"

# Genau diese Zielfelder bestimmen den Ziel-Snapshot (wirtschaftliche
# Definition des Ziels; Bezeichnung/Notizen/Scores nicht).
GOAL_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "id",
    "goal_family",
    "goal_type",
    "rank",
    "weight_bps",
    "goal_scope",
    "value_mode",
    "target_amount_rappen",
    "target_wealth_rappen",
    "target_return_bps",
    "success_probability_min_x100",
    "start_date",
    "horizon_years",
    "target_date",
    "is_ongoing",
    "frequency",
    "hardness",
    "probability_pct",
    "pension_pillar",
    "linked_position_id",
    "is_included",
    "lifecycle_decision",
)

# Genau diese Felder gehen in den Decision-Hash ein. Neue Felder nur mit neuer
# SCHEMA_VERSION (sonst gelten alte Decisions faelschlich als manipuliert).
HASHED_FIELDS: tuple[str, ...] = (
    "id",
    "schema_version",
    "goal_id",
    "mandate_id",
    "client_id",
    "sequence_no",
    "previous_decision_id",
    "goal_snapshot_hash",
    "goal_snapshot_json",
    "previous_hardness",
    "new_status",
    "reason",
    "evidence_status",
    "evidence_best_probability_bps",
    "evidence_wilson_upper_bps",
    "evidence_tau_bps",
    "evidence_engine_version",
    "evidence_allocation_id",
    "evidence_screening_cube_hash",
    "actor_id",
    "decided_at",
    "rules_version",
)


def _value(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _sha256(payload: Any) -> str:
    return evidence_hash(payload)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------------------
# Ziel-Snapshot
# ---------------------------------------------------------------------------


def goal_snapshot(goal: Any) -> dict[str, Any]:
    """Kanonischer Snapshot der wirtschaftlichen Zieldefinition."""
    snapshot: dict[str, Any] = {}
    for name in GOAL_SNAPSHOT_FIELDS:
        value = _value(goal, name)
        if isinstance(value, bool):
            value = int(value)
        snapshot[name] = None if value is None else (
            value if isinstance(value, (int, float)) else str(value)
        )
    return snapshot


def goal_snapshot_hash(goal: Any) -> str:
    return _sha256(goal_snapshot(goal))


# ---------------------------------------------------------------------------
# Decision-Hash
# ---------------------------------------------------------------------------


def decision_payload(decision: Any) -> dict[str, Any]:
    return {name: _value(decision, name) for name in HASHED_FIELDS}


def compute_decision_hash(decision: Any) -> str:
    return _sha256(decision_payload(decision))


def verify_decision(decision: Any) -> bool:
    stored = _value(decision, "decision_hash")
    return bool(stored) and stored == compute_decision_hash(decision)


def decision_snapshot(decision: Any) -> dict[str, Any]:
    """Replaybarer Snapshot: Payload + decision_hash (Audit-Log, Engine)."""
    snapshot = decision_payload(decision)
    snapshot["decision_hash"] = _value(decision, "decision_hash")
    return snapshot


def decision_reference(decision_id: str | None, decision_hash: str | None) -> str:
    """Kurzreferenz ``<id> (SHA-256 <erste 12 Hex>)``."""
    if not decision_id:
        return ""
    if not decision_hash:
        return str(decision_id)
    return f"{decision_id} (SHA-256 {str(decision_hash)[:12]})"


def decision_validity(goal: Any, decision: Any) -> str:
    """``valid`` oder der Grund, warum die Decision fuer DIESES Ziel nicht wirkt.

    * ``hash_mismatch`` -- gespeicherter Hash passt nicht zum Inhalt;
    * ``goal_mismatch`` -- Decision gehoert zu einem anderen Ziel;
    * ``status_unsupported`` -- unbekannter Zielzustand;
    * ``goal_changed`` -- das Ziel wurde seit der Entscheidung geaendert.
    """
    if decision is None:
        return "missing"
    if not verify_decision(decision):
        return "hash_mismatch"
    if str(_value(decision, "goal_id")) != str(_value(goal, "id")):
        return "goal_mismatch"
    if _value(decision, "new_status") != NEW_STATUS_SUBORDINATE_WISH:
        return "status_unsupported"
    if _value(decision, "goal_snapshot_hash") != goal_snapshot_hash(goal):
        return "goal_changed"
    return "valid"


def valid_revision_decisions(goals: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """``goal_id -> Decision-Snapshot`` fuer jedes Ziel mit GUELTIGER Decision.

    Die Engine ruft das mit den Zielobjekten des Laufs auf; die Decision
    haengt (von ``attach_goal_revision_decisions``) unter ``GOAL_ATTRIBUTE``
    am Ziel. Fehlt sie oder ist sie ungueltig, bleibt das Ziel normal.
    """
    out: dict[str, dict[str, Any]] = {}
    for goal in goals or ():
        decision = getattr(goal, GOAL_ATTRIBUTE, None)
        if decision is None:
            continue
        if decision_validity(goal, decision) == "valid":
            out[str(_value(goal, "id"))] = dict(decision)
    return out


def apply_to_liabilities(goals: Iterable[Any], liabilities: list) -> list:
    """Engine-Seite: Ziel-Snapshot-Hash an jede Liability; ``demoted`` nur
    fuer Ziele mit GUELTIGER Decision (Hash, Ziel, Snapshot).

    Wird von ``solver.build_optimizer_context`` direkt nach
    ``goals_to_liabilities`` aufgerufen -- Bags, Validierung, Sensitivitaet
    und Publikation erben die Markierung ueber den Context."""
    from dataclasses import replace

    goals = list(goals or ())
    snapshots = {str(_value(g, "id")): goal_snapshot_hash(g) for g in goals}
    decisions = valid_revision_decisions(goals)
    out = []
    for liab in liabilities:
        gid = str(liab.goal_id)
        decision = decisions.get(gid)
        out.append(replace(
            liab,
            goal_snapshot_hash=snapshots.get(gid),
            demoted=decision is not None,
            revision_decision_id=None if decision is None else decision.get("id"),
            revision_decision_hash=None if decision is None else decision.get("decision_hash"),
        ))
    return out


# ---------------------------------------------------------------------------
# DB: Laden / Anhaengen / Schreiben
# ---------------------------------------------------------------------------


def latest_decisions_for_goals(db, goal_ids: Iterable[str]) -> dict[str, Any]:
    """Juengste Decision (hoechste sequence_no) je Ziel."""
    ids = [str(g) for g in goal_ids if g is not None]
    if not ids or db is None:
        return {}
    from models.wealth import GoalRevisionDecision

    rows = (
        db.query(GoalRevisionDecision)
        .filter(GoalRevisionDecision.goal_id.in_(ids))
        .order_by(GoalRevisionDecision.goal_id, GoalRevisionDecision.sequence_no)
        .all()
    )
    latest: dict[str, Any] = {}
    for row in rows:
        latest[str(row.goal_id)] = row
    return latest


def attach_goal_revision_decisions(db, goals: list) -> list:
    """Haengt an jedes Ziel den Snapshot seiner juengsten Decision.

    Die Gueltigkeit (Hash, Ziel-Snapshot) prueft die Engine selbst
    (``valid_revision_decisions``); hier wird nur geladen."""
    latest = latest_decisions_for_goals(db, (_value(g, "id") for g in goals))
    for goal in goals:
        row = latest.get(str(_value(goal, "id")))
        try:
            setattr(goal, GOAL_ATTRIBUTE, decision_snapshot(row) if row is not None else None)
        except AttributeError:  # pragma: no cover - unveraenderliche Testobjekte
            pass
    return goals


def goal_revision_hash_part(goal: Any) -> dict[str, str]:
    """Beitrag der angehaengten Decision zum Input-Snapshot-Hash der
    Strategie (``portfolio_engine._compute_input_snapshot_hash``, v4).

    Leer ohne Decision -- bestehende Hashes bleiben unveraendert. Mit
    Decision wird die aktuelle Allokation veraltet (Neuberechnung noetig),
    sonst wuerde REGENERATE-IDEMPOTENT-001 die Allokation ohne Herabstufung
    wiederverwenden."""
    decision = getattr(goal, GOAL_ATTRIBUTE, None)
    if not decision:
        return {}
    return {
        "goal_revision_decision": f"{_value(decision, 'id')}:{_value(decision, 'decision_hash')}",
    }


def included_goals_with_revisions(db, goals: list) -> list:
    """CASHFLOW-GOAL-INCLUDE-TOGGLE-001 (nur einbezogene Ziele) +
    GOAL-REVISION-DECISION-001 (Decision am Ziel)."""
    included = [g for g in goals if getattr(g, "is_included", 1) == 1]
    return attach_goal_revision_decisions(db, included)


def goal_revision_view(goal: Any, decision: Any, db=None) -> dict[str, Any] | None:
    """Anzeige-/API-Sicht der juengsten Decision eines Ziels (oder None)."""
    if decision is None:
        return None
    validity = decision_validity(goal, decision)
    return {
        "decision_id": _value(decision, "id"),
        "decision_hash": _value(decision, "decision_hash"),
        "new_status": _value(decision, "new_status"),
        "new_status_label": NEW_STATUS_LABEL,
        "previous_hardness": _value(decision, "previous_hardness"),
        "reason": display_reason(db, _value(decision, "reason")),
        "decided_at": _value(decision, "decided_at"),
        "actor_id": _value(decision, "actor_id"),
        "validity": validity,
        "active": validity == "valid",
        "reference": decision_reference(_value(decision, "id"), _value(decision, "decision_hash")),
    }


def _bps(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value) * 10000.0))
    except (TypeError, ValueError):
        return None


def engine_evidence_for_goal(allocation: Any, goal_id: str) -> dict[str, Any] | None:
    """Reachability-Evidenz der aktuellen Allokation fuer ein Ziel.

    Quelle: die publizierten Zielzeilen (``goal_achievability_json``; im
    Shadow-Modus ``shadow_optimization_json.achievability``), Feld
    ``goal_revision`` (``goal_reachability.annotate_rows``). Beide nur, wenn
    sie an den Integritaetsnachweis gebunden sind (#793 / SHADOW-ANALYSIS-
    INTEGRITY-001). Der Shadow-Schluessel hiess hier bisher faelschlich
    ``goal_achievability``; die Shadow-Evidenz kam dadurch nie an."""
    if allocation is None:
        return None
    from services.portfolio_engine_allocation_integrity import (
        bound_goal_achievability_json,
        bound_shadow_optimization_json,
    )

    sources: list[list] = []
    raw = bound_goal_achievability_json(allocation)  # GOAL-ANALYSIS-INTEGRITY-001
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                sources.append(parsed)
        except (TypeError, ValueError):
            pass
    shadow = bound_shadow_optimization_json(allocation)
    if shadow:
        try:
            parsed = json.loads(shadow)
            rows = parsed.get("achievability") if isinstance(parsed, dict) else None
            if isinstance(rows, list):
                sources.append(rows)
        except (TypeError, ValueError, AttributeError):
            pass
    for rows in sources:
        for row in rows:
            if not isinstance(row, dict) or str(row.get("goal_id")) != str(goal_id):
                continue
            evidence = row.get("goal_revision")
            if isinstance(evidence, dict):
                return evidence
    return None


# ---------------------------------------------------------------------------
# DSG (DSG-ERASURE-NEW-EVIDENCE-001, Nachzug zu #681): der Freitext ``reason``
# liegt in einer append-only Tabelle und laesst sich bei einer DSG-Loeschung
# nicht entfernen. Er wird deshalb VOR dem Hashen pro Kunde versiegelt
# (services/pii_vault.py); Decision-Hash und audit_log-Snapshot binden den
# Umschlag (wie risk_override_decisions.reason). Die Erasure vernichtet den
# Kundenschluessel -> Hash bleibt verifizierbar, Klartext ist weg.
# ---------------------------------------------------------------------------


def stored_reason(db, client_id: str | None, reason: str) -> str:
    """Versiegelter Wert fuer ``goal_revision_decisions.reason`` (wird so
    gespeichert und gehasht). Fail-closed: ``PiiVaultError`` ohne Kunde oder
    fuer einen DSG-geloeschten Kunden -- nie Klartext."""
    from services.pii_vault import seal_for_client

    return seal_for_client(db, client_id, reason)


def display_reason(db, value: Any) -> Any:
    """Anzeigewert einer gespeicherten Begruendung: Klartext ueber den Vault;
    nach DSG-Loeschung (Schluessel vernichtet) der Redaktions-Platzhalter."""
    from services.pii_vault import is_sealed, reveal

    if not is_sealed(value):
        return value  # Altbestand (Klartext) oder leer
    plain = reveal(db, value) if db is not None else None
    if plain is None:
        from services.client_erasure import REDACTION_MARKER

        return REDACTION_MARKER
    return plain


class GoalRevisionError(ValueError):
    def __init__(self, message: str, *, reason_code: str, status_code: int = 409):
        super().__init__(message)
        self.reason_code = reason_code
        self.status_code = status_code


def record_goal_revision_decision(
    db,
    *,
    goal: Any,
    mandate: Any,
    allocation: Any,
    actor_id: str,
    reason: str,
    new_uuid,
) -> Any:
    """Schreibt EINE neue GoalRevisionDecisionV1 (append-only).

    Fail-closed (``GoalRevisionError``, vor jeder Mutation):
    * Begruendung erfuellt die Override-Reason-Qualitaet (422);
    * Engine-Evidenz der aktuellen Allokation fuer dieses Ziel vorhanden,
      zum AKTUELLEN Ziel (Snapshot-Hash) berechnet und mit Vorschlag
      ``revision_suggested`` (sonst 409: neu berechnen / kein Vorschlag);
    * keine bereits wirksame Decision fuer denselben Zielstand (409, vor
      der Evidenz geprueft: eine Decision invalidiert die gespeicherte
      Zielerreichung der Allokation).
    """
    from models.wealth import GoalRevisionDecision
    from services.pii_vault import PiiVaultError
    from services.override_reason_quality import (
        OverrideReasonQualityError,
        validate_override_reason_quality,
    )

    try:
        validate_override_reason_quality(reason)
    except OverrideReasonQualityError as exc:
        raise GoalRevisionError(
            str(exc).replace("override_reason", "Begruendung"),
            reason_code=f"reason_{exc.reason_code}", status_code=422,
        ) from exc

    latest = latest_decisions_for_goals(db, [str(goal.id)]).get(str(goal.id))
    if latest is not None and decision_validity(goal, latest) == "valid":
        raise GoalRevisionError(
            "Das Ziel ist bereits als nachrangiges Wunschziel eingestuft.",
            reason_code="already_active",
        )
    snapshot_hash = goal_snapshot_hash(goal)
    evidence = engine_evidence_for_goal(allocation, str(goal.id))
    if evidence is None:
        raise GoalRevisionError(
            "Fuer dieses Ziel liegt keine Engine-Auswertung der aktuellen "
            "Strategie vor. Bitte die Strategie neu berechnen.",
            reason_code="evidence_missing",
        )
    if evidence.get("goal_snapshot_hash") != snapshot_hash:
        raise GoalRevisionError(
            "Das Ziel wurde seit der letzten Strategie-Berechnung geaendert. "
            "Bitte die Strategie neu berechnen.",
            reason_code="evidence_stale",
        )
    if not evidence.get("revision_suggested"):
        raise GoalRevisionError(
            "Die Engine schlaegt fuer dieses Ziel keine Einstufung als "
            "nachrangiges Wunschziel vor.",
            reason_code="not_suggested",
        )

    try:
        sealed_reason = stored_reason(db, getattr(mandate, "client_id", None), str(reason).strip())
    except PiiVaultError as exc:
        raise GoalRevisionError(str(exc), reason_code="client_erased") from exc

    now = _now()
    decision = GoalRevisionDecision(
        id=new_uuid(),
        schema_version=SCHEMA_VERSION,
        goal_id=str(goal.id),
        mandate_id=str(mandate.id),
        client_id=getattr(mandate, "client_id", None),
        sequence_no=(int(latest.sequence_no) + 1) if latest is not None else 1,
        previous_decision_id=latest.id if latest is not None else None,
        goal_snapshot_hash=snapshot_hash,
        goal_snapshot_json=canonical_json(goal_snapshot(goal)),
        previous_hardness=str(getattr(goal, "hardness", "") or ""),
        new_status=NEW_STATUS_SUBORDINATE_WISH,
        reason=sealed_reason,
        evidence_status=str(evidence.get("status") or ""),
        evidence_best_probability_bps=_bps(evidence.get("best_probability")),
        evidence_wilson_upper_bps=_bps(evidence.get("wilson_upper_bound")),
        evidence_tau_bps=_bps(evidence.get("tau")),
        evidence_engine_version=str(evidence.get("engine_version") or ""),
        evidence_allocation_id=getattr(allocation, "id", None),
        evidence_screening_cube_hash=evidence.get("screening_cube_hash"),
        actor_id=str(actor_id),
        decided_at=now,
        rules_version=RULES_VERSION,
        created_at=now,
    )
    decision.decision_hash = compute_decision_hash(decision)
    db.add(decision)
    return decision
