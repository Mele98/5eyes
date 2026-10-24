"""Round 47 red tests — OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001.

Kontrollrunde 36, Repro B: der primaere Shortfall-Objective-Wert wird auf
einen dimensionslosen Float normalisiert, aber Persistenz/Serialisierung
nutzt weiterhin die historische Konvertierung ``int(round(value * 1000))``
("milli"-Skalierung). Fuer sehr kleine, aber fachlich unterschiedliche
Objective-Werte kollabiert das auf denselben (oder auf 0) gespeicherten
Integer, wodurch jede Sensitivity-/Vergleichs-Delta-Berechnung, die auf den
PERSISTIERTEN Integern (statt auf den rohen Floats) aufsetzt, falsche oder
undefinierte Deltas produziert.

Siehe docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md

Test (a) belegt den Praezisionsverlust direkt an
``_objective_to_milli`` (services/portfolio_engine_optimizer_integration.py).

Test (b) belegt, dass der Praezisionsverlust tatsaechlich in einen falschen
publizierten Delta-Wert durchschlaegt: ``evaluate_goal_sensitivity`` in
services/portfolio_engine.py berechnet ``delta_objective_pct`` NICHT aus den
rohen Solver-Objective-Floats, sondern aus den bereits auf "milli"
gerundeten Integern (lokale Closure ``_obj_milli``, Zeilen ~5632-5646):

    obj_base = _obj_milli(baseline_result.objective_value)
    obj_new = _obj_milli(modified_result.objective_value)
    delta_pct = round((obj_new - obj_base) / abs(obj_base) * 100.0, 2)

Wir patchen den Solver (services.optimizer.solver.run_solver), damit Baseline
und Modified kontrollierte, sehr kleine Objective-Werte liefern (0.0006 und
0.0014 — eines der im Audit bestaetigten Repro-Paare), und rufen danach die
ECHTE Produktionsfunktion ``evaluate_goal_sensitivity`` auf. Die wahre
Verbesserung ist +133.33%; das persistierte/publizierte Delta ist 0.00%,
weil beide Werte auf denselben milli-Integer (1) runden.
"""
from __future__ import annotations

import pytest

from services.portfolio_engine_optimizer_integration import _objective_to_milli

# Wiederverwendung der bestehenden Mandate-Seed-Fixture (volle DB-Session,
# Risikoprofil, Goals, Wealth-Position) statt Duplizierung — siehe
# tests/test_optimizer_phase6.py fuer den vollstaendigen Kontext.
from tests.test_optimizer_phase6 import _seed_mandate, session_factory  # noqa: F401


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001 — round 47 red test "
        "(milli-rappen serialization collapses dimensionless objective "
        "precision), see docs/audits/"
        "2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md"
    ),
)
def test_objective_to_milli_preserves_distinguishable_small_values():
    """_objective_to_milli muss fachlich unterschiedliche kleine Werte
    unterscheidbar speichern -- tut es aber nicht (Kontrollrunde 36, Repro B).
    """
    # Paar 1: 0.0001 -> 0.0002 ist eine Verdoppelung (+100%), aber beide
    # runden auf denselben gespeicherten Integer (0).
    milli_a1 = _objective_to_milli(0.0001)
    milli_a2 = _objective_to_milli(0.0002)
    assert milli_a1 == 0
    assert milli_a2 == 0
    assert milli_a1 != 0 or milli_a2 != milli_a1, (
        "Erwartet: _objective_to_milli unterscheidet 0.0001 von 0.0002 "
        f"(true delta +100%), tatsaechlich kollabieren beide auf {milli_a1}."
    )

    # Paar 2: 0.0006 -> 0.0014 ist +133.33%, aber beide runden auf denselben
    # gespeicherten Integer (1).
    milli_b1 = _objective_to_milli(0.0006)
    milli_b2 = _objective_to_milli(0.0014)
    assert milli_b1 == 1
    assert milli_b2 == 1
    assert milli_b1 != milli_b2, (
        "Erwartet: _objective_to_milli unterscheidet 0.0006 von 0.0014 "
        f"(true delta +133.33%), tatsaechlich kollabieren beide auf {milli_b1}."
    )


def test_evaluate_goal_sensitivity_delta_objective_pct_uses_collapsed_integers(
    session_factory, monkeypatch,
):
    """evaluate_goal_sensitivity() (services/portfolio_engine.py) berechnet
    ``delta_objective_pct`` aus den bereits gerundeten milli-Integern statt
    aus den rohen Solver-Floats. Mit Baseline-Objective=0.0006 und
    Modified-Objective=0.0014 (wahre Verbesserung +133.33%) liefert die
    ECHTE Produktionsfunktion stattdessen 0.00%, weil beide Werte auf den
    gleichen milli-Integer (1) runden.
    """
    import services.portfolio_engine as pe
    from models.mandates import Mandate
    from services.optimizer.solver import OptimizerResult

    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")

    advisor_id, _cid, mid, _aid, goal_id = _seed_mandate(session_factory)

    # Kontrollierte, sehr kleine Objective-Werte -- genau das im Audit
    # bestaetigte Repro-Paar (0.0006 -> 0.0014, wahre Verbesserung +133.33%).
    # Call-Reihenfolge in evaluate_goal_sensitivity: erst Baseline, dann
    # Modified (siehe services/portfolio_engine.py ~Zeile 5621-5630).
    objective_values = iter([0.0006, 0.0014])

    def _fake_run_solver(**kwargs):
        objective_value = next(objective_values)
        weights_bps = {
            "equities": 4000, "bonds": 3000, "real_estate": 0,
            "liquidity": 2000, "alternatives": 1000,
        }
        return OptimizerResult(
            weights_bps=weights_bps,
            objective_value=objective_value,
            iterations=1,
            seed=int(kwargs.get("seed") or 0),
            status="converged",
            method="stochastic",
        )

    monkeypatch.setattr(
        "services.optimizer.solver.run_solver", _fake_run_solver,
    )

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        out = pe.evaluate_goal_sensitivity(
            db=s, mandate=mandate, user_id=advisor_id,
            goal_id=goal_id, target_delta_pct=0,
        )

    # Rohe Solver-Objective-Werte ergeben eine wahre Verbesserung von
    # +133.33% ((0.0014 - 0.0006) / 0.0006 * 100).
    true_delta_pct = round((0.0014 - 0.0006) / 0.0006 * 100.0, 2)
    assert true_delta_pct == pytest.approx(133.33, abs=0.01)

    # Die Produktionsfunktion berechnet das Delta stattdessen aus den
    # gerundeten milli-Integern (beide runden auf 1) -> 0.00% statt +133.33%.
    assert out["objective_value_milli_baseline"] == 1
    assert out["objective_value_milli_new"] == 1
    published_delta_pct = out["delta_objective_pct"]
    assert published_delta_pct == pytest.approx(true_delta_pct, abs=0.5), (
        "Erwartet: delta_objective_pct spiegelt die wahre Verbesserung von "
        f"+{true_delta_pct}% wider, tatsaechlich liefert die Produktions-"
        f"funktion {published_delta_pct}% (berechnet aus den auf milli "
        "gerundeten Integern 1 -> 1 statt aus den rohen Floats 0.0006 -> "
        "0.0014)."
    )
