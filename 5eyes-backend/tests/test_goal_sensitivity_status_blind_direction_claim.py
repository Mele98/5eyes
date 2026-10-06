"""Red test fuer GOAL-SENSITIVITY-PUBLICATION-001 (Kontrollrunde 36).

Befund (externes Audit, siehe
docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md):
Der Goal-Sensitivity-Endpoint (POST /mandates/{id}/target-allocation/sensitivity,
Service-Funktion ``evaluate_goal_sensitivity`` in services/portfolio_engine.py)
berechnet ``delta_objective_pct`` ausschliesslich aus
``baseline_result.objective_value`` und ``modified_result.objective_value``
(services/portfolio_engine.py, kurz vor dem Return-Dict von
``evaluate_goal_sensitivity``) -- OHNE jemals ``modified_result.status`` (oder
``baseline_result.status``) zu pruefen. Der Router
(routers/allocation.py, ``goal_target_sensitivity``) gibt das Ergebnis
unveraendert mit HTTP 200 zurueck, ebenfalls ohne Status-Gate.

Ein bereits existierender Test
(test_endpoint_happy_path_returns_200, tests/test_optimizer_phase6.py)
akzeptiert "diverged"/"diverged_infeasible"/"fallback_house_matrix" explizit
als gueltige status_new-Werte im 200-Erfolgsfall -- das ist der dokumentierte,
gewollte Vertrag dieses Endpoints. Das Problem ist, dass die gerichtete
"besser/schlechter erreichbar"-Aussage (delta_objective_pct) diesen Status
niemals liest: ein Berater sieht z.B. "+100% Zielerreichung" obwohl der
Counterfactual-Solver-Lauf gar nicht konvergiert / infeasible war.

Dieser Test erzwingt status_new="diverged_infeasible" ueber einen Monkeypatch
von ``services.optimizer.solver.run_solver`` (dieselbe Technik wie
``_capture_sensitivity_solver_calls`` in test_optimizer_phase6.py, nur mit
unterschiedlichem Status/Objective pro Aufruf: 1. Aufruf = Baseline
"converged", 2. Aufruf = Counterfactual "diverged_infeasible") und zeigt, dass
``delta_objective_pct`` trotzdem eine normale, gerichtete Zahl bleibt statt
None/gegated zu sein.

xfail(strict=True): dokumentiert den Bug bis GOAL-SENSITIVITY-PUBLICATION-001
gefixt ist.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import services.portfolio_engine as pe
from models.users import User
from tests.test_optimizer_phase6 import (
    _client_with_user,
    _seed_mandate,
    cleanup_overrides,  # noqa: F401 -- pytest fixture, used via name injection
    session_factory,  # noqa: F401 -- pytest fixture, used via name injection
)


def _force_diverged_infeasible_counterfactual(monkeypatch) -> None:
    """Baseline-Solver-Lauf (1. run_solver-Aufruf in evaluate_goal_sensitivity)
    konvergiert normal; der Counterfactual-Lauf (2. Aufruf) kommt als
    ``diverged_infeasible`` zurueck -- mit einem klar unterschiedlichen,
    gueltigen ``objective_value`` (kein NaN/inf), damit ein etwaiges Gating
    eindeutig durch den *Status* ausgeloest werden muesste, nicht durch einen
    Sonderfall in der Zahl selbst.
    """
    import services.optimizer.solver as optimizer_solver

    calls: list[int] = []

    def fake_run_solver(**kwargs):
        calls.append(1)
        is_baseline_call = len(calls) == 1
        return SimpleNamespace(
            objective_value=1.0 if is_baseline_call else 2.0,
            weights_bps={
                "liquidity": 2000,
                "bonds": 3000,
                "equities": 4000,
                "real_estate": 500,
                "alternatives": 500,
            },
            status="converged" if is_baseline_call else "diverged_infeasible",
        )

    monkeypatch.setattr(optimizer_solver, "run_solver", fake_run_solver)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-SENSITIVITY-PUBLICATION-001 -- round 47 red test (diverged/"
        "infeasible solver status does not gate sensitivity direction "
        "claim), see audit docs/audits/2026-09-28-mixed-goal-sensitivity-"
        "objective-evidence-integrity-audit.md"
    ),
)
def test_sensitivity_endpoint_must_not_publish_delta_when_counterfactual_diverged_infeasible(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Wenn der Counterfactual-Solver-Lauf diverged_infeasible ist, darf der
    Endpoint keine gerichtete ``delta_objective_pct``-Zahl veroeffentlichen --
    sie muss None sein (oder die Response braucht ein explizites
    Verfuegbarkeits-/Gating-Feld, das vor Veroeffentlichung geprueft wird).

    AKTUELL (Bug): delta_objective_pct ist weiterhin eine ganz normale Zahl
    (+100.0%), und der Endpoint liefert trotzdem unveraendert HTTP 200.
    """
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    _force_diverged_infeasible_counterfactual(monkeypatch)
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)

    resp = client.post(
        f"/mandates/{mid}/target-allocation/sensitivity",
        json={"goal_id": gid, "target_delta_pct": -10},
    )

    # Reproduziert den dokumentierten Bestandsvertrag: HTTP 200 trotz
    # diverged_infeasible (siehe test_endpoint_happy_path_returns_200).
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status_new"] == "diverged_infeasible"
    assert body["status_baseline"] == "converged"

    # Befund GOAL-SENSITIVITY-PUBLICATION-001: Die gerichtete Aussage darf
    # nicht veroeffentlicht werden, wenn der Counterfactual-Lauf nicht
    # konvergiert / infeasible ist. Aktuell ignoriert der Code den Status
    # vollstaendig und liefert eine normale, gerichtete Prozentzahl.
    assert body["delta_objective_pct"] is None, (
        "Endpoint published a directional delta_objective_pct "
        f"({body['delta_objective_pct']!r}) even though status_new="
        f"{body['status_new']!r} -- the solver's non-convergence/"
        "infeasibility must gate this directional claim, not be silently "
        "ignored (GOAL-SENSITIVITY-PUBLICATION-001)."
    )
