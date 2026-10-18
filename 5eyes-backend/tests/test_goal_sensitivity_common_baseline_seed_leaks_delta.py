"""GOAL-SENSITIVITY-COMMON-BASELINE-001 -- gemeinsamer Szenarioraum pro Slider.

Ursprung: docs/audits/2026-10-04-goal-sensitivity-common-baseline-and-publication-integrity-audit.md

Befund
------
Der Seed der Sensitivitaets-Analyse wurde gebaut als

    deterministic_seed(
        cma_id, goal_ids, score_x10, horizon, _OPTIMIZER_N_PATHS_DEFAULT,
        "sensitivity", target_goal.id, target_delta_pct, horizon_delta_years,
    )

``deterministic_seed`` ist ein reiner SHA-256 ueber alle Positionen, also bekam
jeder Slider-Schritt einen anderen Seed -- und damit einen anderen
Monte-Carlo-Cube fuer seinen BASELINE-Lauf, obwohl die wirtschaftliche
Baseline (CMA, Ziele, Score, Horizont) ueber alle Schritte byte-identisch ist.

Eine Sensitivitaetsanalyse soll genau einen Parameter isolieren. Sitzt jeder
Schritt auf einem eigenen Szenarioraum, enthaelt die ausgewiesene Kurve den
Parametereffekt UND Monte-Carlo-Rauschen, ohne dass die beiden trennbar sind --
eine Verletzung von Common Random Numbers.

Warum der Fix zwei Teile braucht
--------------------------------
Das Delta aus dem Seed zu entfernen genuegt NICHT. Der Szenario-Horizont war
``max(baseline, modified_run_horizon)``, haengt also ebenfalls vom Delta des
jeweiligen Schritts ab -- und ein mit identischem Seed, aber anderem
Szenario-Horizont gebauter Cube liefert nicht dasselbe Praefix. Das ist hier
gemessen (``test_cube_prefix_is_not_stable_across_scenario_horizons``), und
der bereits bestehende Praefix-Test deckt es nicht ab: er pinnt die
Praefix-Eigenschaft nur bei GLEICHEM Szenario-Horizont und unterschiedlichem
LAUF-Horizont.

Teil 1 allein haette also den Betrags-Slider gefixt und den Horizont-Slider
still kaputt gelassen -- mit einem gruenen Reproducer als Beleg fuer eine
Loesung, die nur halb traegt.

Teil 2 setzt den Szenario-Horizont deshalb auf ``baseline + MAX_DELTA``: die
API begrenzt das Horizont-Delta, also ist das die kleinste Obergrenze, die
fuer jeden zulaessigen Schritt reicht und fuer alle dieselbe ist.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from schemas.allocation import MAX_SENSITIVITY_HORIZON_DELTA_YEARS
from tests.test_optimizer_phase6 import (  # noqa: F401 -- als Fixture re-exportiert
    session_factory,
    _seed_mandate,
)


# ---------------------------------------------------------------------------
# Capture: den ECHTEN Szenario-Cube aufzeichnen
# ---------------------------------------------------------------------------


def _capture_baseline_cubes(monkeypatch) -> list[dict]:
    """Zeichnet pro Solver-Aufruf den tatsaechlich gebauten Szenario-Cube auf.

    Der gemeinsame Helfer ``_capture_sensitivity_solver_calls`` liest
    ``context.return_paths`` aus einem ``optimizer_context``-Argument. Der
    Sensitivitaetspfad uebergibt aber Rohdaten und laesst ``run_solver`` den
    Kontext intern bauen -- dort ist das Argument None, und der
    Integrationstest uebersprang sich selbst ("solver context did not expose
    return_paths in this build"). Damit lief genau der Test nicht, der den
    Befund wirklich belegt.

    Hier wird deshalb ``build_optimizer_context`` umwickelt: der echte Kontext
    wird gebaut (und damit der echte Cube gezogen), aufgezeichnet, und der
    teure Solve durch einen Stub ersetzt.
    """
    import services.optimizer.solver as optimizer_solver

    calls: list[dict] = []
    real_build = optimizer_solver.build_optimizer_context
    accepted = set(inspect.signature(real_build).parameters)

    def fake_run_solver(**kwargs):
        context = real_build(
            **{key: value for key, value in kwargs.items() if key in accepted}
        )
        calls.append(
            {
                "seed": int(context.seed),
                "horizon_years": int(context.horizon_years),
                "scenario_horizon_years": int(
                    getattr(context, "scenario_horizon_years", context.horizon_years)
                ),
                "return_paths": np.array(context.return_paths, copy=True),
            }
        )
        from services.optimizer.solver import OptimizerResult

        return OptimizerResult(
            weights_bps={
                "equities": 4000, "bonds": 4000, "real_estate": 1000,
                "alternatives": 500, "liquidity": 500,
            },
            objective_value=1.0,
            iterations=1,
            seed=int(context.seed),
            status="converged",
            method="stochastic",
            constraint_violations=[],
            reasoning=[],
            n_paths=int(context.n_paths),
            n_starts_attempted=1,
            goal_achievability=[],
            context=context,
        )

    monkeypatch.setattr(optimizer_solver, "run_solver", fake_run_solver)
    return calls


def _run_sensitivity(session_factory, advisor_id, mandate_id, goal_id, **deltas):
    import services.portfolio_engine as pe
    from models.mandates import Mandate
    from services.portfolio_engine import evaluate_goal_sensitivity

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).first()
        return evaluate_goal_sensitivity(
            db=session,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=goal_id,
            **deltas,
        )


# ---------------------------------------------------------------------------
# Die gemessene Tatsache, auf der Teil 2 beruht
# ---------------------------------------------------------------------------


def test_cube_prefix_is_not_stable_across_scenario_horizons() -> None:
    """Gleicher Seed, anderer Szenario-Horizont -> ANDERER Cube.

    Diese Messung ist der Grund, warum Teil 1 (Delta aus dem Seed) allein
    nicht genuegt. Der bestehende Test
    ``test_common_scenario_horizon_produces_exact_path_prefix`` pinnt die
    Praefix-Eigenschaft nur bei gleichem Szenario-Horizont -- er haette hier
    nichts gefangen.

    Faellt dieser Test eines Tages, weil die Pfadgenerierung
    horizont-unabhaengig wird, dann ist Teil 2 nicht mehr noetig und der
    Szenario-Horizont darf wieder schritt-abhaengig sein.
    """
    from tests.test_optimizer_context import _ctx

    short_cube = _ctx(
        horizon_years=10, scenario_horizon_years=10,
        cashflow_series_rappen=[20_000_00] * 10, n_paths=64, seed=4242,
    ).return_paths
    long_cube = _ctx(
        horizon_years=10, scenario_horizon_years=30,
        cashflow_series_rappen=[20_000_00] * 10, n_paths=64, seed=4242,
    ).return_paths

    assert not np.array_equal(short_cube, long_cube[:, :10, :]), (
        "Die Pfadgenerierung ist horizont-unabhaengig geworden -- dann ist "
        "der schritt-unabhaengige Szenario-Horizont (Teil 2) nicht mehr "
        "notwendig und kann zurueckgenommen werden."
    )


# ---------------------------------------------------------------------------
# Teil 1: der Seed haengt nicht mehr am Delta
# ---------------------------------------------------------------------------


def test_production_seed_call_does_not_include_the_deltas() -> None:
    """Struktureller Schutz gegen Rueckfall an der Aufrufstelle.

    Der frueher hier stehende Test spiegelte die Produktions-Aufrufform
    haendisch und rief ``deterministic_seed`` direkt mit den Deltas auf -- er
    konnte per Konstruktion nie gruen werden, denn eine reine Hashfunktion
    SOLL bei verschiedenen Argumenten verschiedene Seeds liefern. Der Defekt
    lag nie in der Hashfunktion, sondern in der Aufrufstelle.

    Geprueft wird deshalb die Aufrufstelle selbst. Seit
    SAA-RESAMPLED-STABILITY-001 ist es der Inhalts-Seed
    (``sensitivity_content_seed``) -- die Deltas duerfen auch dort nicht
    hinein, und Datenbank-IDs (``target_goal.id``) ebensowenig.
    """
    source = (BACKEND_ROOT / "services" / "portfolio_engine.py").read_text(
        encoding="utf-8"
    )
    marker = 'pinned_seed = sensitivity_content_seed('
    assert marker in source
    call = source[source.index(marker) : source.index(marker) + 400]
    call = call[: call.index(")")]
    for leaked in ("target_delta_pct", "horizon_delta_years", ".id"):
        assert leaked not in call, (
            f"{leaked} ist wieder im Sensitivitaets-Seed -- jeder "
            "Slider-Schritt bekaeme einen eigenen Baseline-Szenarioraum: "
            f"{call!r}"
        )


def test_baseline_cube_is_identical_across_target_delta_steps(
    session_factory, monkeypatch
) -> None:
    """Der Betrags-Slider: alle Schritte teilen den Baseline-Szenarioraum.

    Das ist die Integrationsfassung des Befundes -- sie laeuft jetzt
    tatsaechlich, statt sich zu ueberspringen.
    """
    import services.portfolio_engine as pe

    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mandate_id, _aid, goal_id = _seed_mandate(session_factory)

    cubes = []
    for delta in (-20, 0, 20):
        calls = _capture_baseline_cubes(monkeypatch)
        _run_sensitivity(
            session_factory, advisor_id, mandate_id, goal_id,
            target_delta_pct=delta, horizon_delta_years=0,
        )
        assert calls, f"kein Solver-Aufruf bei Delta {delta}"
        cubes.append((delta, calls[0]["return_paths"], calls[0]["seed"]))

    first_delta, first_cube, first_seed = cubes[0]
    for delta, cube, seed in cubes[1:]:
        assert seed == first_seed, (
            f"Baseline-Seed unterscheidet sich zwischen Delta {first_delta} "
            f"und {delta}: {first_seed} vs {seed}"
        )
        assert np.array_equal(cube, first_cube), (
            f"Baseline-Szenarioraum unterscheidet sich zwischen Delta "
            f"{first_delta} und {delta} -- die ausgewiesene Sensitivitaet "
            "enthaelt Szenario-Rauschen statt nur den Parametereffekt"
        )


# ---------------------------------------------------------------------------
# Teil 2: der Szenario-Horizont haengt nicht mehr am Delta
# ---------------------------------------------------------------------------


def test_baseline_cube_is_identical_across_horizon_delta_steps(
    session_factory, monkeypatch
) -> None:
    """Der Horizont-Slider -- der Fall, den Teil 1 allein NICHT loest.

    Ohne den schritt-unabhaengigen Szenario-Horizont saessen diese Schritte
    auf verschieden langen Cubes und damit auf verschiedenen Zahlen, obwohl
    der Seed identisch ist.
    """
    import services.portfolio_engine as pe

    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mandate_id, _aid, goal_id = _seed_mandate(session_factory)

    captured = []
    for horizon_delta in (-5, 0, 5):
        calls = _capture_baseline_cubes(monkeypatch)
        _run_sensitivity(
            session_factory, advisor_id, mandate_id, goal_id,
            target_delta_pct=0, horizon_delta_years=horizon_delta,
        )
        assert calls, f"kein Solver-Aufruf bei Horizont-Delta {horizon_delta}"
        captured.append((horizon_delta, calls[0]))

    first_delta, first = captured[0]
    for horizon_delta, call in captured[1:]:
        assert call["scenario_horizon_years"] == first["scenario_horizon_years"], (
            f"Szenario-Horizont haengt am Schritt: {first_delta} -> "
            f"{first['scenario_horizon_years']}, {horizon_delta} -> "
            f"{call['scenario_horizon_years']}"
        )
        assert np.array_equal(call["return_paths"], first["return_paths"]), (
            f"Baseline-Szenarioraum unterscheidet sich zwischen "
            f"Horizont-Delta {first_delta} und {horizon_delta}"
        )


def test_scenario_horizon_leaves_room_for_the_largest_allowed_delta(
    session_factory, monkeypatch
) -> None:
    """Der gemeinsame Cube reicht auch fuer den groessten zulaessigen Schritt.

    Sonst waere der schritt-unabhaengige Horizont eine Scheinlosung: der
    aeusserste Slider-Schritt wuerde ihn sprengen und die Engine muesste doch
    wieder verlaengern.
    """
    import services.portfolio_engine as pe

    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mandate_id, _aid, goal_id = _seed_mandate(session_factory)

    calls = _capture_baseline_cubes(monkeypatch)
    _run_sensitivity(
        session_factory, advisor_id, mandate_id, goal_id,
        target_delta_pct=0,
        horizon_delta_years=MAX_SENSITIVITY_HORIZON_DELTA_YEARS,
    )
    assert len(calls) == 2, "Baseline- und modifizierter Lauf erwartet"
    baseline, modified = calls
    assert modified["horizon_years"] <= baseline["scenario_horizon_years"], (
        f"Der modifizierte Lauf braucht {modified['horizon_years']} Jahre, der "
        f"gemeinsame Cube deckt nur {baseline['scenario_horizon_years']} ab"
    )
    # Und beide sitzen auf demselben Cube-Praefix.
    shared_years = min(
        baseline["return_paths"].shape[1], modified["return_paths"].shape[1]
    )
    assert np.array_equal(
        baseline["return_paths"][:, :shared_years, :],
        modified["return_paths"][:, :shared_years, :],
    )


def test_schema_bound_and_engine_constant_cannot_drift() -> None:
    """Die Eingabepruefung und der Cube-Horizont nutzen dieselbe Konstante.

    Driften sie auseinander, akzeptiert die API ein Delta, fuer das der
    gemeinsame Cube zu kurz ist -- und der Horizont-Slider wuerde wieder pro
    Schritt neu geseedet. Die Engine prueft das zur Laufzeit fail-closed; hier
    wird festgehalten, dass die Grenze nur an EINER Stelle definiert ist.
    """
    from schemas.allocation import AllocationSensitivityRequest

    limit = MAX_SENSITIVITY_HORIZON_DELTA_YEARS
    AllocationSensitivityRequest(
        goal_id="g", target_delta_pct=0, horizon_delta_years=limit
    )
    AllocationSensitivityRequest(
        goal_id="g", target_delta_pct=0, horizon_delta_years=-limit
    )
    with pytest.raises(ValueError, match="horizon_delta_years"):
        AllocationSensitivityRequest(
            goal_id="g", target_delta_pct=0, horizon_delta_years=limit + 1
        )

    schema_source = (BACKEND_ROOT / "schemas" / "allocation.py").read_text(
        encoding="utf-8"
    )
    assert "MAX_SENSITIVITY_HORIZON_DELTA_YEARS" in schema_source
    engine_source = (BACKEND_ROOT / "services" / "portfolio_engine.py").read_text(
        encoding="utf-8"
    )
    assert (
        "baseline_solver_horizon + MAX_SENSITIVITY_HORIZON_DELTA_YEARS"
        in engine_source
    ), "Der Cube-Horizont leitet sich nicht mehr aus der Schema-Grenze ab"
