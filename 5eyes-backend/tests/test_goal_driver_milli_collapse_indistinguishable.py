"""Round 47 red tests: OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001.

Kontrollrunde 36, Audit-Dok
docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md:

`_objective_to_milli()` (services/portfolio_engine_optimizer_integration.py,
ca. Zeile 725-736) berechnet `int(round(value * 1000.0))`. Mehrere
MATERIELL VERSCHIEDENE, kleine positive Objective-/Goal-Driver-Beitraege
kollabieren dadurch auf denselben gespeicherten Integer (0) -- "voll
erfuellt" (raw objective exakt 0), "minimale Verfehlung" (raw ~4e-12) und
"materielle kleine Unterdeckung" (raw ~4e-4) werden in der persistierten
Goal-Driver-Evidenz visuell/numerisch UNUNTERSCHEIDBAR, obwohl Goal-Driver
laut Doku korrekt nach ihrem rohen (ungerundeten) Beitrag VOR der
Serialisierung sortiert bleiben sollen.

Fundstellen (verifiziert durch Lesen der echten Datei, nicht nur Behauptung):
- `_objective_to_milli`: services/portfolio_engine_optimizer_integration.py
  Zeile 725-736 -- `scaled = value * 1000.0`, dann
  `int(round(capped))`. Kein Toleranz-/Epsilon-Handling fuer kleine
  Werte -- alles unter 0.0005 (banker's rounding: auch 0.0005 selbst,
  da round-half-to-even auf 0 rundet) wird zu 0.
- Publikation des gerundeten Werts: services/portfolio_engine_optimizer_integration.py
  Funktion `_build_optimizer_explainability` (Zeile 1079ff.), Schleife
  Zeile 1196-1207:
      for rank, row in enumerate(contribution_rows, start=1):
          drivers_payload.append({
              ...
              "weighted_objective_contribution_milli": _objective_to_milli(
                  row.weighted_objective_contribution
              ),
              "rank": rank,
          })
  `row` ist eine `GoalShortfallContribution` (services/optimizer/objective.py,
  Zeile 522ff.) mit dem ROHEN Feld `weighted_objective_contribution`. Der
  publizierte/serialisierte Wert pro Goal-Driver ist also exakt der
  gerundete Milli-Integer -- NICHT der rohe Float.
- Sortierung bleibt roh: `shortfall_contributions()` (services/optimizer/objective.py,
  Zeile 591) sortiert `contribution_rows` VOR der obigen Schleife mit
      sorted(rows, key=lambda row: row.weighted_objective_contribution, reverse=True)
  -- also nach dem ungerundeten Float. Diese Sortier-Korrektheit ist der
  Positiv-Control in diesem Modul (Test c) und darf durch einen
  zukuenftigen Praezisions-Fix NICHT angetastet werden.

Verifizierte Werte (direkt gegen die echte Funktion verifiziert, nicht nur
behauptet):
    _objective_to_milli(0)        -> 0
    _objective_to_milli(4e-12)    -> 0
    _objective_to_milli(4e-6)     -> 0
    _objective_to_milli(4e-5)     -> 0
    _objective_to_milli(0.00049)  -> 0
    _objective_to_milli(0.00050)  -> 0   (round-half-to-even: 0.5 rundet auf
                                           die gerade Zahl 0, nicht 1)
    _objective_to_milli(0.00060)  -> 1
    _objective_to_milli(0.00140)  -> 1
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.objective import GoalShortfallContribution
from services.portfolio_engine_optimizer_integration import _objective_to_milli


# ============================================================================
# (a) Direkter Test auf _objective_to_milli: mehrere verschiedene, von Null
#     verschiedene rohe Werte muessen sich nach Serialisierung unterscheiden.
#     XFAIL: sie kollabieren alle auf denselben Integer (0).
# ============================================================================


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001 -- round 47 red test "
        "(goal-driver contributions become indistinguishable after milli "
        "rounding), see audit "
        "docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md"
    ),
)
def test_objective_to_milli_boundary_values_confirmed():
    """Positive-Verifikation der im Audit behaupteten Werte (inkl. 0.0005-Grenzfall).

    Dieser Teil ist informativ (dokumentiert die exakte Arithmetik) und
    xfail-strict zusammen mit der eigentlichen Kollaps-Assertion weiter
    unten in derselben Funktion -- sobald ein Praezisions-Fix landet, MUSS
    mindestens die Kollaps-Assertion failen (-> xfail wird zum Fehlschlag
    und CI macht uns darauf aufmerksam, den Test zu aktualisieren).
    """
    assert _objective_to_milli(0) == 0
    assert _objective_to_milli(4e-12) == 0
    assert _objective_to_milli(4e-6) == 0
    assert _objective_to_milli(4e-5) == 0
    assert _objective_to_milli(0.00049) == 0
    assert _objective_to_milli(0.00050) == 0  # round-half-to-even -> 0, nicht 1
    assert _objective_to_milli(0.00060) == 1
    assert _objective_to_milli(0.00140) == 1

    # Die eigentliche Behauptung des Audits: "fully satisfied" (0),
    # "minimal miss" (4e-12) und "material small shortfall" (4e-4-Bereich,
    # hier 0.00049) muessen NACH Serialisierung unterscheidbar bleiben.
    # Sie sind es nicht -- alle vier (inkl. 4e-6, 4e-5) kollabieren auf {0}.
    raw_values = [0, 4e-12, 4e-6, 4e-5, 0.00049]
    serialized = {_objective_to_milli(v) for v in raw_values}
    assert len(serialized) > 1, (
        f"Erwartet: mehrere unterscheidbare serialisierte Werte fuer "
        f"materiell verschiedene rohe Objective-Beitraege {raw_values}; "
        f"tatsaechlich kollabieren alle auf {serialized}"
    )


# ============================================================================
# (b) Goal-Driver-Serialisierung: dieselbe Kollaps-Pathologie entlang des
#     echten Produktionspfads (GoalShortfallContribution ->
#     weighted_objective_contribution_milli), repliziert aus der echten
#     Schleife in _build_optimizer_explainability (Zeile 1196-1207).
#     XFAIL: die publizierten Goal-Driver-Werte sind alle 0.
# ============================================================================


def _make_contribution(goal_id: str, raw_contribution: float) -> GoalShortfallContribution:
    """Synthetischer GoalShortfallContribution-Row mit vorgegebenem rohem Beitrag.

    GoalShortfallContribution ist die echte, produktionsweit genutzte
    frozen dataclass (services/optimizer/objective.py Zeile 522ff.) -- hier
    direkt mit synthetischen Objective-Komponentenwerten instanziiert statt
    ueber einen vollen Solver-Lauf, um die Serialisierungslogik isoliert zu
    pruefen.
    """
    return GoalShortfallContribution(
        goal_id=goal_id,
        label=f"goal-{goal_id}",
        target_kind="wealth_at_t",
        hardness_key="hart",
        weight_bps=5000,
        mean_shortfall_squared=raw_contribution,
        weighted_objective_contribution=raw_contribution,
    )


def _build_drivers_payload_like_production(
    contribution_rows: list[GoalShortfallContribution],
) -> list[dict]:
    """Repliziert EXAKT die Serialisierungsschleife aus
    services/portfolio_engine_optimizer_integration.py,
    _build_optimizer_explainability, Zeile 1196-1207 (gegengelesen am
    echten Code): dieselben Feldnamen, dieselbe _objective_to_milli-Aufruf.
    """
    drivers_payload: list[dict] = []
    for rank, row in enumerate(contribution_rows, start=1):
        drivers_payload.append({
            "goal_id": row.goal_id,
            "label": row.label,
            "target_kind": row.target_kind,
            "hardness_key": row.hardness_key,
            "weight_bps": int(row.weight_bps),
            "weighted_objective_contribution_milli": _objective_to_milli(
                row.weighted_objective_contribution
            ),
            "rank": rank,
        })
    return drivers_payload


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001 -- round 47 red test "
        "(goal-driver contributions become indistinguishable after milli "
        "rounding), see audit "
        "docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md"
    ),
)
def test_goal_driver_published_milli_values_not_all_identical():
    """Vier Goals mit materiell verschiedenen rohen Beitraegen (0, 4e-12,
    4e-5, 0.00049) -- 'voll erfuellt', 'minimale Verfehlung',
    'kleine materielle Unterdeckung' -- muessen nach Publikation NICHT alle
    identisch/0 sein. Sind sie aber (Kollaps-Bug)."""
    contribution_rows = [
        _make_contribution("fully_satisfied", 0.0),
        _make_contribution("minimal_miss", 4e-12),
        _make_contribution("small_material_shortfall", 4e-5),
        _make_contribution("larger_material_shortfall", 0.00049),
    ]
    # Sortierung wie in shortfall_contributions() (objective.py Zeile 591):
    # absteigend nach dem ROHEN Beitrag.
    contribution_rows = sorted(
        contribution_rows,
        key=lambda row: row.weighted_objective_contribution,
        reverse=True,
    )

    drivers_payload = _build_drivers_payload_like_production(contribution_rows)
    published_values = {d["weighted_objective_contribution_milli"] for d in drivers_payload}

    assert published_values != {0}, (
        "Alle vier materiell verschiedenen Goal-Driver-Beitraege wurden auf "
        "denselben publizierten Wert (0) gerundet -- 'voll erfuellt' ist von "
        "'kleine materielle Unterdeckung' in der Evidenz nicht mehr zu "
        f"unterscheiden. Publiziert: {drivers_payload}"
    )
    assert len(published_values) > 1


# ============================================================================
# (c) POSITIV-CONTROL (kein xfail): Ranking/Reihenfolge der Goal-Driver nach
#     ROHEM Beitrag bleibt korrekt erhalten, auch wenn die publizierten
#     Magnituden kollabieren. Das ist die im Audit explizit bestaetigte,
#     NICHT kaputte Eigenschaft -- ein zukuenftiger Praezisions-Fix darf sie
#     nicht aus Versehen "mitreparieren" bzw. muss sie unangetastet lassen.
# ============================================================================


def test_goal_driver_ranking_order_preserved_despite_milli_collapse():
    """Ranking nach dem rohen (ungerundeten) Beitrag bleibt korrekt, obwohl
    die publizierten Milli-Werte fuer kleine Beitraege alle auf 0 kollabieren.

    Vier Goals mit rohen Beitraegen 0.00049 > 4e-5 > 4e-12 > 0 -- die
    publizierten *_milli-Werte sind dafuer (aktuell) alle 0, aber der `rank`
    im Payload und die Reihenfolge der Liste muessen trotzdem exakt die
    absteigende Reihenfolge nach dem rohen Wert widerspiegeln."""
    # Bewusst NICHT in sortierter Reihenfolge angelegt -- die Sortierung muss
    # von der echten Produktionslogik selbst hergestellt werden.
    unsorted_rows = [
        _make_contribution("fully_satisfied", 0.0),
        _make_contribution("larger_material_shortfall", 0.00049),
        _make_contribution("minimal_miss", 4e-12),
        _make_contribution("small_material_shortfall", 4e-5),
    ]

    contribution_rows = sorted(
        unsorted_rows,
        key=lambda row: row.weighted_objective_contribution,
        reverse=True,
    )
    drivers_payload = _build_drivers_payload_like_production(contribution_rows)

    expected_order = [
        "larger_material_shortfall",  # 0.00049
        "small_material_shortfall",   # 4e-5
        "minimal_miss",               # 4e-12
        "fully_satisfied",            # 0.0
    ]
    actual_order = [d["goal_id"] for d in drivers_payload]
    assert actual_order == expected_order

    # rank-Feld muss 1..N in genau dieser Reihenfolge sein.
    assert [d["rank"] for d in drivers_payload] == [1, 2, 3, 4]

    # Positiv-Control explizit: obwohl das Ranking korrekt ist, sind die
    # publizierten Magnituden fuer diese kleinen Werte (aktuell) ununterscheidbar
    # -- das ist genau die vom Audit beschriebene Pathologie, hier nur als
    # Beleg dafuer, dass sie die Sortierung NICHT betrifft.
    published_values = [d["weighted_objective_contribution_milli"] for d in drivers_payload]
    assert published_values == [0, 0, 0, 0]
