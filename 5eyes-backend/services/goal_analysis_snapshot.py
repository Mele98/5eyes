"""GOAL-ANALYSIS-INTEGRITY-001: die persistierte Zielanalyse als gebundenes Ergebnis.

Codex-Zeuge zu PR #659: ``TargetAllocation.goal_achievability_json`` (je Ziel
Wahrscheinlichkeit, Status und die Ursachenverteilung
``failure_event_distribution``) lag ausserhalb des ``allocation_context_hash``.
Die Zeile liess sich nachtraeglich aendern, ohne dass ein Verifier es merkte.

Vertrag (``GoalAnalysisSnapshotV1``):

* Generate serialisiert die Zielanalyse genau einmal
  (``serialize_goal_achievability``) und bindet den SHA-256 dieser Bytes als
  Referenz ``{"version", "hash"}`` unter ``CONSTRAINTS_KEY`` in
  ``effective_constraints``. Derselbe Hash geht als expliziter
  ``analysis_result_hash`` in den Context-Hash (Form v2). Gehasht wird ein
  Ergebnis-Hash, nicht das veraenderliche JSON selbst: Eingabe- und
  Ergebnisvertrag bleiben getrennt.
* Das Integritaets-Gate prueft die gespeicherten Bytes gegen die Referenz.
* Bestand ohne Referenz bleibt bei der v1-Form und wird nie umgehasht
  (``legacy_unbound``: lesbar wie bisher, aber nicht als gebunden ausgewiesen).
* Die Lifecycle-Invalidierung setzt die Zielanalyse auf NULL
  (``goal_lifecycle_transitions.invalidate_goal_achievability_evidence``).
  Das entfernt eine Aussage, statt eine zu erfinden, und gilt als
  ``invalidated`` -- nicht als Manipulation.

Lesende Kanaele holen die Zielanalyse ueber ``bound_goal_achievability_json``:
bei verletzter Bindung liefert er ``None`` (fail-closed, keine Zielzeilen).

Reine Evidenz: keine Rechnung und kein Optimizer-Entscheid aendert sich.
"""
from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger(__name__)

GOAL_ANALYSIS_SNAPSHOT_VERSION = "goal_analysis_snapshot_v1"
# Schluessel der Referenz in effective_constraints (-> allocation_context_hash).
CONSTRAINTS_KEY = "goal_analysis_snapshot"

STATUS_VERIFIED = "verified"
STATUS_INVALIDATED = "invalidated"
STATUS_LEGACY_UNBOUND = "legacy_unbound"
STATUS_NOT_APPLICABLE = "not_applicable"


def serialize_goal_achievability(goal_achievability) -> str | None:
    """Die eine persistierte Form der Zielanalyse (Bytes = Hash-Grundlage)."""
    if not goal_achievability:
        return None
    try:
        return json.dumps(goal_achievability, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning("Goal-achievability JSON-serialization failed: %s", exc)
        return None


def goal_analysis_hash(goal_achievability_json: str) -> str:
    return hashlib.sha256(goal_achievability_json.encode("utf-8")).hexdigest()


def goal_analysis_reference(goal_achievability_json: str | None) -> dict | None:
    """Referenz fuer ``effective_constraints``; None ohne Zielanalyse."""
    if goal_achievability_json is None:
        return None
    return {
        "version": GOAL_ANALYSIS_SNAPSHOT_VERSION,
        "hash": goal_analysis_hash(goal_achievability_json),
    }


def goal_analysis_constraints(goal_achievability_json: str | None) -> dict:
    """``{CONSTRAINTS_KEY: Referenz}`` oder ``{}`` (ohne Zielanalyse bleibt der
    Constraint-Block und damit der Context-Hash wie bisher)."""
    reference = goal_analysis_reference(goal_achievability_json)
    return {CONSTRAINTS_KEY: reference} if reference is not None else {}


def bound_analysis_result_hash(effective_constraints: dict | None) -> str | None:
    """``analysis_result_hash`` fuer den Context-Hash (None -> v1-Form).

    Wirft ``ValueError`` bei einer Referenz in unbekannter Form: eine solche
    Referenz darf nie still als "kein Ergebnis" (v1) gelesen werden.
    """
    if not isinstance(effective_constraints, dict):
        return None
    reference = effective_constraints.get(CONSTRAINTS_KEY)
    if reference is None:
        return None
    if (
        not isinstance(reference, dict)
        or set(reference) != {"version", "hash"}
        or reference.get("version") != GOAL_ANALYSIS_SNAPSHOT_VERSION
        or not isinstance(reference.get("hash"), str)
        or len(reference["hash"]) != 64
    ):
        raise ValueError(
            "Persistierte Zielanalyse-Referenz hat eine unbekannte Form."
        )
    return reference["hash"]


def verify_goal_analysis(allocation, effective_constraints: dict | None) -> str:
    """Status der Zielanalyse; ``ValueError`` bei verletzter Bindung.

    Setzt einen bereits per Context-Hash verifizierten Constraint-Block voraus
    (Aufruf aus dem Integritaets-Gate).
    """
    bound_hash = bound_analysis_result_hash(effective_constraints)
    raw = getattr(allocation, "goal_achievability_json", None)
    if bound_hash is None:
        return STATUS_LEGACY_UNBOUND if raw else STATUS_NOT_APPLICABLE
    if raw is None:
        return STATUS_INVALIDATED
    if not isinstance(raw, str) or goal_analysis_hash(raw) != bound_hash:
        raise ValueError(
            "Persistierte Zielanalyse (Zielerreichung/Ursachenverteilung) "
            "weicht vom gebundenen Ergebnis-Hash ab."
        )
    return STATUS_VERIFIED


def goal_analysis_status(allocation, effective_constraints: dict | None) -> str:
    """Wie ``verify_goal_analysis``, aber ohne Ausnahme (Statusanzeige)."""
    try:
        return verify_goal_analysis(allocation, effective_constraints)
    except ValueError:
        return "integrity_mismatch"


def bound_goal_achievability_json(allocation) -> str | None:
    """Gespeicherte Zielanalyse fuer lesende Kanaele, nur wenn gebunden.

    Bestand ohne Referenz: unveraendert wie bisher. Mit Referenz: volles
    Integritaets-Gate (Context-Hash + Ergebnis-Hash); jede Verletzung liefert
    ``None`` -- kein Kanal publiziert dann Zielzeilen.
    """
    if allocation is None:
        return None
    raw = getattr(allocation, "goal_achievability_json", None)
    if not raw:
        return None
    try:
        constraints = json.loads(getattr(allocation, "effective_constraints_json", None) or "null")
    except (TypeError, ValueError):
        constraints = None
    if not isinstance(constraints, dict) or constraints.get(CONSTRAINTS_KEY) is None:
        return raw
    from services.portfolio_engine import BUCKET_FIELDS
    from services.portfolio_engine_allocation_integrity import (
        _verified_persisted_allocation_context,
    )

    try:
        _verified_persisted_allocation_context(
            allocation,
            targets={b: int(getattr(allocation, f"target_{b}_bps")) for b in BUCKET_FIELDS},
            minimums={b: int(getattr(allocation, f"band_{b}_min_bps") or 0) for b in BUCKET_FIELDS},
            maximums={b: int(getattr(allocation, f"band_{b}_max_bps") or 0) for b in BUCKET_FIELDS},
        )
    except (AttributeError, TypeError, ValueError) as exc:
        logger.warning(
            "Zielanalyse der Allokation %s nicht publiziert (Integritaet): %s",
            getattr(allocation, "id", "?"), exc,
        )
        return None
    return raw


__all__ = [
    "CONSTRAINTS_KEY",
    "GOAL_ANALYSIS_SNAPSHOT_VERSION",
    "STATUS_INVALIDATED",
    "STATUS_LEGACY_UNBOUND",
    "STATUS_NOT_APPLICABLE",
    "STATUS_VERIFIED",
    "bound_analysis_result_hash",
    "bound_goal_achievability_json",
    "goal_analysis_constraints",
    "goal_analysis_hash",
    "goal_analysis_reference",
    "goal_analysis_status",
    "serialize_goal_achievability",
    "verify_goal_analysis",
]
