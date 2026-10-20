"""MC-CONTEXT-001 (Codex-Review PR #645): Staleness-Preflight fuer Report-
Projektionen einer gespeicherten Soll-Allokation.

Befund: Der kanonische Allocation-Payload
(``services.portfolio_engine.build_target_payload_from_allocation``) verweigert
eine Soll-Allokation, deren Risikoprofil-Anker nicht mehr dem aktuellen
Risikoprofil entspricht oder deren Inputs sich geaendert haben. Die
Advisory-Report-Monte-Carlo-Sektion lud dagegen die alte Allokation direkt
und rechnete deren Gewichte unter dem NEUEN Risikoprofil-Horizont -- ein
Diagramm mit zwei Entscheidungsstaenden, ausgewiesen als aktuell.

Dieser Helper erfindet KEINE eigene Staleness-Regel. Er buendelt exakt die
Pruefungen, die Depot-Check (Sektionen 7/8/13) und Payload bereits nutzen:

* ``target_allocation_predates_current_assessment`` (Risikoprofil-ID-Drift
  bzw. Override nach der Allokation, identisch zum Payload-Gate);
* ``allocation_inputs_stale`` (ruft den Payload-Pfad mit
  ``input_snapshot_check_only=True`` auf, d.h. denselben Input-Hash);
* fuer moderne Allokationen eine aktuelle Optimizer-Policy (wie
  ``GET .../target-allocation/current/payload``).

Ergebnis ist ein Status statt einer Exception, damit der Report fail-closed,
aber erzeugbar bleibt: ``current`` (projizieren erlaubt), ``stale`` (Anker
veraltet), ``blocked`` (Anker nicht pruefbar) oder ``no_allocation``.

Die CMA-Aufloesung (Snapshot-CMA der Allokation statt global aktueller CMA)
liegt bewusst in ``services.monte_carlo_paths.resolve_allocation_cma`` --
dort, wo die CMA tatsaechlich verbraucht wird.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy.orm import Session

STATUS_CURRENT = "current"
STATUS_STALE = "stale"
STATUS_BLOCKED = "blocked"
STATUS_NO_ALLOCATION = "no_allocation"

RECOMPUTE_HINT = "Bitte Strategie neu berechnen."

_NOTE_ASSESSMENT_STALE = (
    "Die Soll-Allokation basiert auf einem frueheren, nicht mehr aktuellen "
    "Risikoprofil. Prognosen dieser Strategie werden deshalb nicht angezeigt. "
    + RECOMPUTE_HINT
)
_NOTE_INPUTS_STALE = (
    "Vermoegen, Cashflows oder Ziele haben sich seit der Berechnung der "
    "Soll-Allokation geaendert. Prognosen dieser Strategie werden deshalb "
    "nicht angezeigt. " + RECOMPUTE_HINT
)
# MC-CONTEXT-001 (Codex-Closure-Review PR #652): Berater-Kurzhinweis je
# Gate-Grund. Wird in jeder ausgeblendeten Projektionssektion (Key-Metrics,
# Zielerreichung, MC, Stress, Soll-Sektionen 7-10/13, PDF) gleich angezeigt.
HINT_NO_ASSESSMENT = "Kein aktuelles Risikoprofil – Projektionen ausgeblendet."
HINT_POLICY_NOT_CURRENT = (
    "Keine aktuelle Optimizer-Policy – Projektionen ausgeblendet."
)
HINT_GATE_ERROR = (
    "Projektionskontext nicht pruefbar – Projektionen ausgeblendet."
)
HINT_STALE = "Soll-Allokation veraltet – Projektionen ausgeblendet."
HINT_GENERIC = "Projektionen ausgeblendet."

_NOTE_NO_ASSESSMENT = (
    HINT_NO_ASSESSMENT + " Die Soll-Allokation kann nicht gegen ein "
    "eindeutiges aktuelles Risikoprofil geprueft werden. Bitte Risikoprofil "
    "erfassen und Strategie neu berechnen."
)
_NOTE_POLICY_NOT_CURRENT = (
    "Die Soll-Allokation referenziert keine aktuelle Optimizer-Policy. "
    + RECOMPUTE_HINT
)
_NOTE_GATE_ERROR = (
    "Der Projektionskontext der Soll-Allokation konnte nicht geprueft "
    "werden. Prognosen dieser Strategie werden deshalb nicht angezeigt. "
    + RECOMPUTE_HINT
)

# Status, unter denen Projektionen der Soll-Allokation publiziert werden
# duerfen. ``no_allocation``: es gibt nichts zu projizieren (Sektionen
# liefern ohnehin ihre Leerform). Jeder andere -- auch ein kuenftig neuer,
# hier unbekannter -- Status blendet aus (fail-closed).
_PUBLISHABLE_STATUSES = frozenset({STATUS_CURRENT, STATUS_NO_ALLOCATION})


@dataclass(frozen=True)
class ProjectionGate:
    status: str
    reason: str
    note: str

    @property
    def is_current(self) -> bool:
        return self.status == STATUS_CURRENT

    @property
    def is_hidden(self) -> bool:
        """Kanonischer Ausblende-Entscheid fuer ALLE Projektionskanaele des
        Reports (MC-CONTEXT-001, Codex-Closure-Review PR #652): ``stale``
        UND ``blocked`` -- fehlende Verifizierbarkeit ist der strengere
        Zustand, nicht der schwaechere. Unbekannte Status: fail-closed."""
        return self.status not in _PUBLISHABLE_STATUSES

    @property
    def is_stale_or_blocked(self) -> bool:
        # Rueckwaertskompatibler Alias -- gleiche (fail-closed) Semantik.
        return self.is_hidden

    @property
    def hint(self) -> str | None:
        """Kurzer Berater-Hinweis fuer ausgeblendete Projektionen."""
        if not self.is_hidden:
            return None
        if self.status == STATUS_STALE:
            return HINT_STALE
        return {
            "no_assessment": HINT_NO_ASSESSMENT,
            "policy_not_current": HINT_POLICY_NOT_CURRENT,
            "gate_error": HINT_GATE_ERROR,
        }.get(self.reason, HINT_GENERIC)

    def to_payload(self) -> dict[str, Any]:
        """Maschinenlesbarer Gate-Kontext fuer API/Web/PDF."""
        return {
            "status": self.status,
            "reason_code": self.reason or None,
            "projections_hidden": self.is_hidden,
            "hinweis": self.hint,
            "note": self.note or None,
        }


def gate_error() -> ProjectionGate:
    """Fail-closed-Urteil, wenn die Gate-Pruefung selbst scheitert."""
    return ProjectionGate(STATUS_BLOCKED, "gate_error", _NOTE_GATE_ERROR)


def resolve_report_projection_gate(
    db: Session,
    mandate: Any,
    allocation: Any,
    *,
    depot_check: Mapping[str, Any] | None = None,
    assessment: Any = None,
    assessment_preloaded: bool = False,
) -> ProjectionGate:
    """Urteilt einmal, ob Werte der aktuellen Soll-Allokation projiziert
    werden duerfen.

    ``depot_check``: optional das bereits berechnete Ergebnis von
    ``services.depot_check.compute_depot_check`` (dieselben zwei Pruefungen);
    erspart im Report die zweite Input-Hash-Rekonstruktion und garantiert,
    dass Sektion 7/8/13 und die Projektionssektionen identisch urteilen.
    """
    if allocation is None:
        return ProjectionGate(STATUS_NO_ALLOCATION, "no_allocation", "")

    from services.portfolio_engine import _current_risk_assessment_or_none
    from services.risk_assessment_semantics import (
        target_allocation_predates_current_assessment,
    )

    # ``assessment_preloaded``: der Report hat das aktuelle Risikoprofil bereits
    # einmal (gecacht, is_current=1 + nicht geloescht) geladen -- keine zweite
    # Query (Aggregator-N+1-Budget, test_aggregator_n1_baseline).
    if not assessment_preloaded:
        try:
            assessment = _current_risk_assessment_or_none(db, mandate.id)
        except ValueError:
            assessment = None
    if assessment is None:
        return ProjectionGate(STATUS_BLOCKED, "no_assessment", _NOTE_NO_ASSESSMENT)

    if depot_check is not None and "target_allocation_stale" in depot_check:
        stale = bool(depot_check.get("target_allocation_stale"))
        inputs_stale = bool(depot_check.get("target_allocation_inputs_stale"))
    else:
        stale = target_allocation_predates_current_assessment(
            allocation, assessment.id, assessment,
        )
        inputs_stale = False
        if not stale:
            from services.allocation_input_staleness import allocation_inputs_stale

            inputs_stale = allocation_inputs_stale(
                db, mandate, allocation, assessment=assessment,
            )
            stale = inputs_stale
    if stale:
        if inputs_stale:
            return ProjectionGate(STATUS_STALE, "inputs", _NOTE_INPUTS_STALE)
        return ProjectionGate(STATUS_STALE, "assessment", _NOTE_ASSESSMENT_STALE)

    modern_context = int(
        getattr(allocation, "context_artifacts_required", 0) or 0
    ) == 1
    if modern_context:
        from models.allocation import OptimizerPolicy

        policy_id = str(getattr(allocation, "policy_id", "") or "").strip()
        policy = (
            db.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_id).first()
            if policy_id
            else None
        )
        if policy is None or int(getattr(policy, "is_current", 0) or 0) != 1:
            return ProjectionGate(
                STATUS_BLOCKED, "policy_not_current", _NOTE_POLICY_NOT_CURRENT,
            )
    return ProjectionGate(STATUS_CURRENT, "", "")
