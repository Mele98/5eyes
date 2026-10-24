"""GOAL-HIERARCHY-ALL-OBJECTIVES-001 (CIO-Entscheid, Engine ``saa_resampled_v15``).

Befund (Reproducer ``test_2026_10_18_objective_normalization_adversarial.py``,
Teil "harte Untergrenze"): in den Risikomass-Varianten (``max_return``,
``min_volatility``, ``max_drawdown``, ``cvar_return``) war die
Ziel-Untergrenze eines harten Ziels nur ein verrechenbarer Strafterm. Ein
Renditeplus von 20 % (``-0.2``) ueberbot den VOLLSTAENDIGEN Ausfall eines
harten Ziels von 10 % des Vermoegens (``0.8 * 0.1^2 = 0.008``). Die
Stufe-1-Zielhierarchie (``solver._goal_protection_stage``) lief bis v14 nur
im Modus ``goal_shortfall``.

Soll-Invariante (CIO Option A): ein hartes oder primaeres Ziel darf in KEINEM
Modus durch Rendite oder Risiko ausgekauft werden. Stufe 1 bestimmt je
Wuerfel ``G1* = min_w G1(w)`` (G1 = Fehlbetrag + Chance-Strafe der
harten/primaeren Ziele, modusunabhaengig); Stufe 2 minimiert die
Zielfunktion des Modus nur unter ``G1(w) <= G1* + eps``.

Oracle: das Stufe-1-Niveau der gewaehlten Allokation, unabhaengig nachgerechnet
(``_protected_level_from_inputs``), liegt unter der Schranke. Positivkontrolle
je Szenario: mit abgeschalteter Stufe 1 (Stand v14) waehlt dieselbe Variante
eine Allokation UEBER der Schranke -- der Test misst also eine echte
Versuchung, nicht einen Fall, in dem Rendite/Risiko und Ziel ohnehin
gleichgerichtet sind.

Die Skalarfunktion ``combined_objective_two_phase`` bleibt absichtlich
verrechenbar (Abschnitt 1): die Untergrenze ist eine Nebenbedingung des
Solvers, kein Gewicht im Skalar. Der Reproducer-Satz wird deshalb auf der
Ebene geprueft, auf der die Entscheidung faellt (Auswahl je Wuerfel und
voller Lauf).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import services.optimizer.solver as solver_module  # noqa: E402
from services.optimizer.goal_liabilities import GoalLiability  # noqa: E402
from services.optimizer.objective import (  # noqa: E402
    combined_objective_two_phase,
    protected_goal_level,
)
from services.optimizer.objective_contract import (  # noqa: E402
    implemented_objective_policy,
)
from services.optimizer.resampling import ResamplingConfig  # noqa: E402
from test_engine_reference_mandates import _make_goal  # noqa: E402
from test_maximize_goal_and_hardness import _inputs, _wealth_goal  # noqa: E402

RISK_MEASURE_MODES = ("max_return", "min_volatility", "max_drawdown", "cvar_return")


@pytest.fixture(autouse=True)
def _default_goal_weighting(monkeypatch):
    monkeypatch.delenv("OPTIMIZER_GOAL_WEIGHTING", raising=False)


def _context(monkeypatch, mode: str, goals, horizon: int, *, seed: int = 11):
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", mode)
    context = solver_module.build_optimizer_context(seed=seed, **_inputs(goals, horizon))
    assert context.objective_contract.objective_mode == mode
    return context


def _near_hard_goal():
    """CHF 480'000 in 2 Jahren aus CHF 500'000: mit Obligationen sicher,
    mit maximalem Aktienanteil auf rund jedem fuenften Pfad verfehlt."""
    return _make_goal(
        goal_id="vz", label="VZ", hardness="Hart", goal_type="Vermoegensziel",
        target_rappen=480_000_00, target_date_offset_days=365 * 2,
    )


def _level(context, w) -> float:
    return solver_module._protected_level_from_inputs(
        context, solver_module._evaluation_inputs(context, np.asarray(w, dtype=float)),
    )[0]


def _selection_without_stage_one(context, monkeypatch):
    """Stand v14 in den Varianten: Stufe 1 abgeschaltet (Positivkontrolle)."""
    with monkeypatch.context() as patch:
        patch.setattr(solver_module, "_goal_protection_stage", lambda *a, **k: None)
        return solver_module._select_cube_candidate(context, max_iter=50, ftol=1e-6)


# ---------------------------------------------------------------------------
# 1. Reproducer-Zahlen: der Skalar allein ist verrechenbar
# ---------------------------------------------------------------------------


def _repro_goal(*, target: int, hardness: str) -> GoalLiability:
    return GoalLiability(
        goal_id="goal", label="Goal", goal_type="Vermögensziel",
        target_kind="wealth_at_t", target_amount_rappen=target,
        target_year_index=1, liability_path_rappen=[], hardness_key=hardness,
        weight_bps=10_000, success_probability_min_x100=8_000,
    )


def test_reproducer_numbers_scalar_is_tradable_but_stage_one_separates_them():
    """Reproducer-Zahlen (hartes Ziel = 10 % von W0, Renditeplus 20 %): der
    Skalar zieht den vollstaendigen Ausfall vor -- deshalb darf er die
    Untergrenze nicht allein tragen. Stufe 1 trennt die beiden Allokationen
    strikt (G1 = 0 gegen G1 > 0); unter ``G1 <= G1* + eps`` ist der Ausfall
    nicht zulaessig, sobald die Erfuellung gefunden wurde."""
    n_paths = 2_000
    goal = _repro_goal(target=10, hardness="hart")
    reaches = np.column_stack([np.full(n_paths, 100.0), np.full(n_paths, 10.0)])
    misses = np.column_stack([np.full(n_paths, 100.0), np.zeros(n_paths)])
    common = {
        "initial_wealth_rappen": 100, "horizon_years": 1,
        "objective_mode": "max_return", "goal_weighting_mode": "equal",
    }
    reaches_loss = combined_objective_two_phase(
        [goal], reaches, portfolio_return_factors=np.ones((n_paths, 1)), **common,
    )
    misses_loss = combined_objective_two_phase(
        [goal], misses, portfolio_return_factors=np.full((n_paths, 1), 1.20), **common,
    )
    assert misses_loss < reaches_loss  # der Befund auf Skalar-Ebene, bewusst

    kwargs = {"initial_wealth_rappen": 100, "horizon_years": 1,
              "goal_weighting_mode": "equal"}
    level_reaches = protected_goal_level([goal], reaches, **kwargs)[0]
    level_misses = protected_goal_level([goal], misses, **kwargs)[0]
    assert level_reaches == 0.0
    assert level_misses > 0.0


# ---------------------------------------------------------------------------
# 2. Reproducer-Vertrag auf Entscheidungsebene (rot auf v14)
# ---------------------------------------------------------------------------


def test_hard_goal_floor_must_not_be_outbid_by_max_return(monkeypatch):
    """Reproducer "harte Untergrenze": max_return darf ein hartes Ziel nicht
    gegen Rendite tauschen."""
    context = _context(monkeypatch, "max_return", [_near_hard_goal()], 3)
    selection = solver_module._select_cube_candidate(context, max_iter=50, ftol=1e-6)
    audit = selection.goal_protection
    assert audit is not None, "Stufe 1 fehlt im Modus max_return"
    assert audit["protected_goal_ids"] == ["vz"]
    assert _level(context, selection.weights) <= audit["bound"] * (1.0 + 1e-9)

    # Positivkontrolle: ohne Stufe 1 kauft die Rendite die Zielerosion.
    unprotected = _selection_without_stage_one(context, monkeypatch)
    assert _level(context, unprotected.weights) > audit["bound"]


def test_hard_goal_floor_must_not_be_outbid_by_lower_volatility(monkeypatch):
    """Gegenrichtung: min_volatility darf ein hartes Wachstumsziel nicht
    gegen tiefere Volatilitaet tauschen (CHF 1.2 Mio in 25 Jahren)."""
    context = _context(
        monkeypatch, "min_volatility", [_wealth_goal(1_200_000_00, "Hart")], 25,
    )
    selection = solver_module._select_cube_candidate(context, max_iter=50, ftol=1e-6)
    audit = selection.goal_protection
    assert audit is not None, "Stufe 1 fehlt im Modus min_volatility"
    assert _level(context, selection.weights) <= audit["bound"] * (1.0 + 1e-9)

    unprotected = _selection_without_stage_one(context, monkeypatch)
    assert _level(context, unprotected.weights) > audit["bound"]


@pytest.mark.parametrize("mode", RISK_MEASURE_MODES)
@pytest.mark.parametrize("hardness", ["Hart", "Primär"])
def test_stage_one_is_active_in_every_risk_measure_variant(monkeypatch, mode, hardness):
    """Jede Variante, harte UND primaere Ziele: Stufe-1-Audit vorhanden,
    gewaehlte Allokation innerhalb der Schranke (unabhaengig nachgerechnet)."""
    context = _context(monkeypatch, mode, [_wealth_goal(1_200_000_00, hardness)], 25)
    selection = solver_module._select_cube_candidate(context, max_iter=50, ftol=1e-6)
    audit = selection.goal_protection
    assert audit is not None
    assert audit["protected_goal_ids"] == ["vz"]
    assert audit["final_level"] == pytest.approx(
        _level(context, selection.weights), rel=1e-9,
    )
    assert audit["final_level"] <= audit["bound"] * (1.0 + 1e-9)
    # Ohne Haus-Prior in den Varianten: Toleranz aus dem Stufe-1-Punkt.
    assert audit["tolerance_basis"] == "stage1_point"


@pytest.mark.parametrize("mode", RISK_MEASURE_MODES)
def test_opportunistic_goal_stays_without_stage_one_in_variants(monkeypatch, mode):
    """Wunschziele sind auch in den Varianten nicht Stufe 1 (weicher Term)."""
    context = _context(
        monkeypatch, mode, [_wealth_goal(1_200_000_00, "Opportunistisch")], 25,
    )
    selection = solver_module._select_cube_candidate(context, max_iter=50, ftol=1e-6)
    assert selection.goal_protection is None


def test_full_variant_run_carries_stage_one_in_every_bag(monkeypatch):
    """Voller resampelter Lauf (max_return): jeder Bag traegt den Stufe-1-
    Audit und haelt seine Schranke."""
    goals = [_near_hard_goal()]
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", "max_return")
    inputs = _inputs(goals, 3)
    result = solver_module.run_solver(
        **inputs, resampling=ResamplingConfig(n_bags=4, bag_n_paths=300),
    )
    bags = result.resampling["bags"]
    assert bags
    for bag in bags:
        audit = bag["goal_protection"]
        assert audit is not None
        assert audit["final_level"] <= audit["bound"] * (1.0 + 1e-9)


def test_objective_contract_names_the_hierarchy_scope():
    assert implemented_objective_policy()["goal_hierarchy_scope"] == "all_objectives"
