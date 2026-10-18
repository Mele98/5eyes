"""OPTIMIZER-DRAWDOWN-CERTIFICATION-001 -- Drawdown-Zertifizierung aller Finalisten.

Befund (letzter offener P1 aus der Objective-Varianten-Runde): der Modus
``max_drawdown`` optimiert auf dem Jahresgitter-Proxy. Die Nachrechnung auf
dem verfeinerten Zeitgitter (Brownsche Bruecke, PR #577) lief

  * auf dem TRAININGS-Cube (dem Cube, auf dem selektiert wurde) und
  * nur fuer den GEWINNER.

Damit liess sich weder selektionsfrei zertifizieren noch beantworten, ob die
Proxy-Verzerrung die Entscheidung bewegt hat.

Owner-Entscheid (2026-10-14): ALLE zulaessigen Multi-Start-Finalisten werden
auf dem unabhaengigen VALIDIERUNGS-Cube mit dem verfeinerten Drawdown neu
bewertet und nach dem validierten Objective gerankt. Der Audit haelt fest, ob
Rangfolge und Gewinner sich geaendert haben. Deterministisch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _path in (BACKEND_ROOT, TESTS_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from services.optimizer import solver as solver_module
from services.optimizer.objective_variants import (
    OBJECTIVE_GOAL_SHORTFALL,
    OBJECTIVE_MAX_DRAWDOWN,
    refined_drawdown_check_for_winner,
)
from services.optimizer.solver import (
    VALIDATION_SEED_OFFSET,
    build_optimizer_context,
    run_solver,
)

from test_optimizer_context import _cma, _house_matrix, _pension_goal  # noqa: E402

SEED = 20261014
N_PATHS = 400
HORIZON = 10
WEALTH = 500_000_00


def _kwargs(**overrides) -> dict:
    base = dict(
        cma=_cma(),
        goals=[_pension_goal()],
        house_matrix_row=_house_matrix(),
        score_x10=70,
        advisory_wealth_rappen=WEALTH,
        cashflow_series_rappen=[20_000_00] * HORIZON,
        horizon_years=HORIZON,
        n_paths=N_PATHS,
        seed=SEED,
    )
    base.update(overrides)
    return base


def _solve(monkeypatch, mode: str = OBJECTIVE_MAX_DRAWDOWN, **overrides):
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", mode)
    return run_solver(**_kwargs(**overrides))


# ---------------------------------------------------------------------------
# Reine Rerank-Logik
# ---------------------------------------------------------------------------


def _rerank(values):
    from services.optimizer.drawdown_certification import rerank_by_validated_objective

    return rerank_by_validated_objective([{"validated_objective": v} for v in values])


def test_rerank_keeps_training_winner_when_validation_agrees():
    outcome = _rerank([0.10, 0.12, 0.15])
    assert outcome["validated_winner_index"] == 0
    assert outcome["winner_changed"] is False
    assert outcome["ranking_changed"] is False


def test_rerank_records_a_moved_decision():
    outcome = _rerank([0.14, 0.11, 0.15])
    assert outcome["validated_winner_index"] == 1
    assert outcome["winner_changed"] is True
    assert outcome["ranking_changed"] is True
    assert outcome["validated_order"] == [1, 0, 2]


def test_rerank_records_a_reorder_below_an_unchanged_winner():
    outcome = _rerank([0.10, 0.15, 0.12])
    assert outcome["winner_changed"] is False
    assert outcome["ranking_changed"] is True


def test_rerank_numeric_tie_keeps_training_order():
    outcome = _rerank([0.1, 0.1 * (1 + 1e-15), 0.1])
    assert outcome["validated_order"] == [0, 1, 2]
    assert outcome["winner_changed"] is False


# ---------------------------------------------------------------------------
# Produktionspfad
# ---------------------------------------------------------------------------


def test_max_drawdown_run_certifies_all_finalists_on_the_validation_cube(monkeypatch):
    from services.optimizer.resampling import SINGLE_CUBE

    # Einzelwuerfel-Pfad: Multi-Start-Finalisten (der Resampling-Pfad hat
    # eigene Tests unten).
    result = _solve(monkeypatch, resampling=SINGLE_CUBE)
    if result.status == "fallback_house_matrix":
        pytest.skip("Solver-Fallback; keine Finalisten.")
    audit = getattr(result, "drawdown_certification", None)
    assert audit is not None, "max_drawdown-Lauf ohne Drawdown-Zertifizierung"
    assert audit["certified"] is True
    # Validierungs-Cube, nicht Trainings-Cube -- derselbe Cube wie die
    # Goal-Nachzertifizierung.
    assert audit["validation_seed"] == SEED + VALIDATION_SEED_OFFSET
    assert audit["validation_seed"] != result.seed
    assert audit["validation_cube_hash"] == result.validation_cube_hash
    assert audit["n_candidates"] == len(audit["candidates"]) >= 1
    assert isinstance(audit["ranking_changed"], bool)
    assert isinstance(audit["winner_changed"], bool)
    for candidate in audit["candidates"]:
        # Verfeinert ist nie kleiner als das Jahresgitter (Bruecke enthaelt
        # die Jahresknoten exakt).
        assert candidate["refined_mean_drawdown"] >= candidate["annual_grid_mean_drawdown"] - 1e-12
        assert candidate["validated_objective"] == pytest.approx(
            candidate["refined_mean_drawdown"]
            + candidate["chance_penalty"]
            + candidate["preference_penalty"]
        )
    # Gewaehlt ist das validierte Minimum.
    best = min(audit["candidates"], key=lambda c: (c["validated_objective"], c["training_rank"]))
    assert best["validated_rank"] == 0
    assert result.weights_bps == audit["validated_winner_weights_bps"]
    assert any("Validierungs-Cube" in line for line in result.reasoning)


def test_training_winner_is_scored_on_the_validation_cube_not_the_training_cube(monkeypatch):
    result = _solve(monkeypatch)
    if result.status == "fallback_house_matrix":
        pytest.skip("Solver-Fallback; keine Finalisten.")
    audit = getattr(result, "drawdown_certification", None)
    assert audit is not None, "max_drawdown-Lauf ohne Drawdown-Zertifizierung"
    training_winner = audit["candidates"][0]
    context = result.context
    w = np.array(
        [training_winner["weights_bps"][b] / 10000.0 for b in solver_module.BUCKET_ORDER]
    )
    on_training_cube = refined_drawdown_check_for_winner(
        solver_module._portfolio_return_factors(context, w),
        seed=int(context.seed),
        weights=context.scenario_weights,
    )
    assert training_winner["refined_mean_drawdown"] != pytest.approx(
        on_training_cube["refined_mean_drawdown"], abs=1e-12
    ), "Die Zertifizierung darf nicht auf dem Trainings-Cube rechnen."


def test_drawdown_certification_is_deterministic(monkeypatch):
    first = _solve(monkeypatch)
    second = _solve(monkeypatch)
    assert first.weights_bps == second.weights_bps
    assert first.drawdown_certification is not None
    assert json.dumps(first.drawdown_certification, sort_keys=True) == json.dumps(
        second.drawdown_certification, sort_keys=True
    )


def test_default_mode_has_no_drawdown_certification(monkeypatch):
    result = _solve(monkeypatch, mode=OBJECTIVE_GOAL_SHORTFALL)
    assert getattr(result, "drawdown_certification", None) is None


def test_validated_ranking_moves_the_decision(monkeypatch):
    """Zwei verschiedene zulaessige Finalisten; die validierte Bewertung
    bevorzugt den Nicht-Trainingsgewinner -> er wird gewaehlt und der Audit
    sagt, dass die Entscheidung bewegt wurde."""
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", OBJECTIVE_MAX_DRAWDOWN)
    context = build_optimizer_context(**_kwargs())
    lo = np.array([lo for lo, _hi in context.bounds])
    hi = np.array([hi for _lo, hi in context.bounds])
    mid = solver_module._normalize_to_bounds((lo + hi) / 2.0, context.bounds)
    # Innerhalb der Hausmatrix-Baender, Aktien am unteren Rand.
    defensive = np.array([0.45, 0.45, 0.0, 0.0, 0.10])
    assert solver_module.is_feasible(
        defensive, bounds=context.bounds, constraints=context.scipy_constraints,
    )[0]
    assert defensive[0] < mid[0]

    from services.optimizer import drawdown_certification as dd_module

    equities = solver_module.BUCKET_ORDER.index("equities")
    real = dd_module.validated_drawdown_evaluation

    def _prefers_less_equity(validation_context, weights_array, *, validation_seed):
        evaluation = real(validation_context, weights_array, validation_seed=validation_seed)
        evaluation["validated_objective"] = float(weights_array[equities])
        return evaluation

    monkeypatch.setattr(dd_module, "validated_drawdown_evaluation", _prefers_less_equity)
    weights, audit = dd_module.certify_drawdown_candidates(
        context,
        winner_weights=mid,
        candidates=[{"weights": defensive, "source": "slsqp"}],
    )
    assert weights is not None
    assert audit["winner_changed"] is True
    assert audit["ranking_changed"] is True
    assert audit["validated_winner_weights_bps"] != audit["training_winner_weights_bps"]
    # Zurueck kommt genau die bewertete (gerundete) Allokation.
    assert {
        bucket: int(round(weights[i] * 10000))
        for i, bucket in enumerate(solver_module.BUCKET_ORDER)
    } == audit["validated_winner_weights_bps"]
    assert weights[equities] == pytest.approx(defensive[equities], abs=1e-4)
    reasoning = dd_module.drawdown_certification_reasoning(audit)
    assert any("BEWEGT" in line for line in reasoning)


def test_run_solver_publishes_the_validated_winner(monkeypatch):
    """Einzelwuerfel-Pfad: bevorzugt die validierte Bewertung einen anderen
    Finalisten, publiziert run_solver genau diesen (nicht nur Anzeige).
    Seed 3 liefert mehrere verschiedene konvergierte Finalisten.

    Seit SAA-RESAMPLED-STABILITY-001 rankt der Produktionspfad nicht mehr
    Multi-Start-Finalisten, sondern {Bag-Mittel, projiziertes Mittel,
    Hausmatrix-Anker} (Tests unten); der Multi-Start-Rerank lebt im
    Einzelwuerfel-Pfad (SINGLE_CUBE) weiter."""
    from services.optimizer import drawdown_certification as dd_module
    from services.optimizer.resampling import SINGLE_CUBE

    liquidity = solver_module.BUCKET_ORDER.index("liquidity")
    real = dd_module.validated_drawdown_evaluation

    def _prefers_more_liquidity(validation_context, weights_array, *, validation_seed):
        evaluation = real(validation_context, weights_array, validation_seed=validation_seed)
        evaluation["validated_objective"] = -float(weights_array[liquidity])
        return evaluation

    monkeypatch.setattr(dd_module, "validated_drawdown_evaluation", _prefers_more_liquidity)
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", OBJECTIVE_MAX_DRAWDOWN)
    result = run_solver(**_kwargs(seed=3), resampling=SINGLE_CUBE)
    audit = result.drawdown_certification
    assert audit["candidate_pool"] == dd_module.POOL_MULTI_START_FINALISTS
    assert audit["n_candidates"] >= 2, audit
    highest = max(c["weights_bps"]["liquidity"] for c in audit["candidates"])
    assert audit["training_winner_weights_bps"]["liquidity"] < highest
    assert audit["winner_changed"] is True
    assert result.weights_bps["liquidity"] == highest
    assert result.weights_bps == audit["validated_winner_weights_bps"]
    assert result.status == "converged"


def test_validation_cube_has_the_training_horizon_when_the_scenario_horizon_is_longer(monkeypatch):
    """Der Validierungs-Cube wird wie der Trainings-Cube auf dem gemeinsamen
    Szenario-Horizont gezogen und auf den Optimierungshorizont gekuerzt --
    sonst misst der Drawdown-Rerank Jahre, die der Lauf nicht plant."""
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", OBJECTIVE_MAX_DRAWDOWN)
    context = build_optimizer_context(**_kwargs(scenario_horizon_years=HORIZON + 5))
    validation_context, _seed, _hash = solver_module._build_validation_context(context)
    assert validation_context.return_paths.shape == context.return_paths.shape


def test_without_validation_cube_the_audit_says_why_and_keeps_the_disclosure():
    from dataclasses import replace

    from services.optimizer import drawdown_certification as dd_module

    context = build_optimizer_context(**_kwargs())
    context = replace(context, scenario_inputs=None)
    lo = np.array([lo for lo, _hi in context.bounds])
    hi = np.array([hi for _lo, hi in context.bounds])
    mid = solver_module._normalize_to_bounds((lo + hi) / 2.0, context.bounds)
    weights, audit = dd_module.certify_drawdown_candidates(
        context, winner_weights=mid, candidates=[],
    )
    assert weights is None
    assert audit["certified"] is False
    assert audit["reason"] == "no_independent_validation_cube"
    check = refined_drawdown_check_for_winner(
        solver_module._portfolio_return_factors(context, mid), seed=1,
    )
    lines = dd_module.drawdown_certification_reasoning(audit, training_cube_check=check)
    assert any("NICHT" in line and "zertifiziert" in line for line in lines)
    assert any("Trainings-Cube (nicht selektionsfrei)" in line for line in lines)


def test_drawdown_certification_is_persisted_in_the_selection_audit():
    from types import SimpleNamespace

    from models import (  # noqa: F401  -- registriert alle ORM-Mapper
        allocation, clients, mandates, profiling, review, snapshots, users, wealth,
    )
    from services.portfolio_engine_optimizer_integration import _persist_optimizer_run

    captured = {}

    class _Db:
        def add(self, run):
            captured["run"] = run

    audit = {"version": "v", "winner_changed": True, "ranking_changed": True}
    result = SimpleNamespace(
        weights_bps={"equities": 5000, "bonds": 3000, "real_estate": 1000,
                     "alternatives": 500, "liquidity": 500},
        constraint_violations=[], reasoning=["x"], stress_evaluations=None,
        restart_results=(), robustification=None, drawdown_certification=audit,
        method="stochastic", status="converged", seed=1, n_paths=10,
        iterations=1, n_starts_attempted=1, objective_value=0.1,
        validation_seed=None, validation_cube_hash=None, validation_n_paths=None,
    )
    _persist_optimizer_run(
        _Db(), mandate_id="m", target_allocation_id=None,
        optimizer_mode="shadow_stochastic", optimizer_result=result,
        user_id=None, now="2026-10-14T00:00:00Z",
    )
    stored = json.loads(captured["run"].robustification_json)
    assert stored["drawdown_certification"] == audit
    assert "final_reason" in stored


# ---------------------------------------------------------------------------
# Unter Resampled Efficiency (SAA-RESAMPLED-STABILITY-001, CIO-Entscheid
# 2026-10-18)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def resampled_max_drawdown():
    """Ein Produktionslauf (Resampling, Default-Konfiguration) im Modus max_drawdown."""
    mp = pytest.MonkeyPatch()
    mp.setenv("OPTIMIZER_OBJECTIVE", OBJECTIVE_MAX_DRAWDOWN)
    try:
        yield run_solver(**_kwargs())
    finally:
        mp.undo()


def test_resampled_rerank_scores_mean_projection_and_house_anchor(resampled_max_drawdown):
    """Kandidaten = {projiziertes Bag-Mittel, rohes Bag-Mittel, Hausmatrix-
    Anker}, alle auf DEMSELBEN Validierungs-Cube wie der Signifikanztest."""
    from services.optimizer import drawdown_certification as dd_module

    result = resampled_max_drawdown
    assert result.resampling and result.resampling["enabled"] is True
    audit = result.drawdown_certification
    assert audit is not None, "Resampling-Lauf im Modus max_drawdown ohne Rerank"
    assert audit["certified"] is True
    assert audit["candidate_pool"] == dd_module.POOL_RESAMPLED
    labels = [c["label"] for c in audit["candidates"]]
    assert labels[0] == dd_module.LABEL_PROJECTED_MEAN
    assert set(labels) <= {
        dd_module.LABEL_PROJECTED_MEAN,
        dd_module.LABEL_RAW_MEAN,
        dd_module.LABEL_HOUSE_ANCHOR,
    }
    significance = result.resampling["significance"]
    anchor = significance["house_anchor_projected_bps"]
    assert anchor is not None
    # Der projizierte Anker ist bewertet (eigene Zeile oder zusammengefasst).
    assert any(c["weights_bps"] == anchor for c in audit["candidates"])
    assert audit["house_anchor_validated_rank"] is not None
    # Gemeinsamer Cube: Rerank, Signifikanztest und Goal-Nachzertifizierung.
    assert audit["validation_seed"] == significance["validation_seed"]
    assert audit["validation_cube_hash"] == significance["validation_cube_hash"]
    assert audit["validation_cube_hash"] == result.validation_cube_hash
    # Der Signifikanztest testet den besten Nicht-Anker-Kandidaten.
    assert significance["candidate_bps"] == audit["significance_candidate_weights_bps"]
    # Die publizierte Allokation folgt dem Signifikanzentscheid.
    expected = (
        anchor
        if significance["decision"] == "house_matrix"
        else significance["candidate_bps"]
    )
    assert result.weights_bps == expected
    assert any(
        "Signifikanztest gegen die Hausmatrix geht" in line for line in result.reasoning
    )


def test_resampled_significance_uses_the_refined_drawdown(resampled_max_drawdown):
    """Im Modus max_drawdown vergleicht der Signifikanztest mit dem
    verfeinerten Drawdown -- seine Punktschaetzung ist identisch mit dem
    validierten Objective des Reranks (gleiche Zielfunktion, gleicher Cube,
    gleicher Bruecken-Seed). Mit dem Jahresgitter-Proxy waeren beide Zahlen
    verschieden (der Proxy liegt systematisch tiefer)."""
    result = resampled_max_drawdown
    significance = result.resampling["significance"]
    if significance.get("reason") == "identical_to_house_anchor":
        pytest.skip("Kandidat = Anker; kein Test gelaufen.")
    assert significance["drawdown_measure"] == "refined_brownian_bridge"
    by_bps = {
        tuple(sorted(c["weights_bps"].items())): c
        for c in result.drawdown_certification["candidates"]
    }
    anchor = by_bps[tuple(sorted(significance["house_anchor_projected_bps"].items()))]
    candidate = by_bps[tuple(sorted(significance["candidate_bps"].items()))]
    # HOUSE-FIRST-SIGNIFICANCE-001 (2026-10-18): die Top-Level-Statistik ist
    # die ZIELEBENE (Chance-Strafe + Soft-Preference) ...
    for stats_key, entry in (("anchor_objective", anchor), ("candidate_objective", candidate)):
        assert significance[stats_key] == pytest.approx(
            entry["chance_penalty"] + entry["preference_penalty"], rel=1e-12, abs=1e-15
        )
    # ... der Skalar mit dem verfeinerten Drawdown (= validated_objective des
    # Reranks) steht im Risikomass-Test, sofern die Zielebene nicht schon
    # entschieden hat.
    from services.optimizer.resampling import resampling_model_basis

    basis = resampling_model_basis(result.resampling)
    assert basis["significance"]["drawdown_measure"] == "refined_brownian_bridge"
    risk = significance.get("risk_measure_test")
    if risk is None:
        assert significance["reason"] == "significant_goal_improvement"
        return
    assert basis["significance"]["risk_measure_test"] == risk
    assert risk["anchor_objective"] == pytest.approx(
        anchor["validated_objective"], rel=1e-12, abs=1e-15
    )
    assert risk["candidate_objective"] == pytest.approx(
        candidate["validated_objective"], rel=1e-12, abs=1e-15
    )
    assert risk["anchor_risk_measure"] == pytest.approx(
        anchor["refined_mean_drawdown"], rel=1e-12
    )
    # Der verfeinerte Drawdown liegt ueber dem Jahresgitter -- haette der
    # Test den Proxy benutzt, laege anchor_objective darunter.
    assert anchor["refined_mean_drawdown"] > anchor["annual_grid_mean_drawdown"]
    # Konsistenz: Rangfolge im Rerank == Vorzeichen der Punktschaetzung.
    anchor_ahead = anchor["validated_rank"] < candidate["validated_rank"]
    assert anchor_ahead == (risk["improvement"] <= 0.0)


def test_default_mode_significance_keeps_its_model_basis(monkeypatch):
    """Ausserhalb max_drawdown kein drawdown_measure-Schluessel: die
    Modellbasis (allocation_context_hash) der Default-Laeufe bleibt gleich."""
    result = _solve(monkeypatch, mode=OBJECTIVE_GOAL_SHORTFALL)
    assert result.drawdown_certification is None
    assert "drawdown_measure" not in (result.resampling.get("significance") or {})


def test_resampled_rerank_hands_the_best_non_anchor_candidate_to_the_test(monkeypatch):
    """Bevorzugt die validierte Bewertung das rohe Bag-Mittel gegenueber dem
    projizierten, geht das rohe Mittel in den Signifikanztest; der Anker wird
    nie selbst zum Testkandidaten."""
    from services.optimizer import drawdown_certification as dd_module

    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", OBJECTIVE_MAX_DRAWDOWN)
    context = build_optimizer_context(**_kwargs())
    validation = solver_module._build_validation_context(context)
    lo = np.array([lo for lo, _hi in context.bounds])
    hi = np.array([hi for _lo, hi in context.bounds])
    projected = solver_module._normalize_to_bounds((lo + hi) / 2.0, context.bounds)
    raw = np.array([0.50, 0.40, 0.0, 0.0, 0.10])
    assert solver_module.is_feasible(
        raw, bounds=context.bounds, constraints=context.scipy_constraints,
    )[0]
    anchor = {"equities": 6000, "bonds": 3000, "real_estate": 500,
              "alternatives": 300, "liquidity": 200}
    equities = solver_module.BUCKET_ORDER.index("equities")
    real = dd_module.validated_drawdown_evaluation

    def _prefers_less_equity(validation_context, weights_array, *, validation_seed):
        evaluation = real(validation_context, weights_array, validation_seed=validation_seed)
        evaluation["validated_objective"] = float(weights_array[equities])
        return evaluation

    monkeypatch.setattr(dd_module, "validated_drawdown_evaluation", _prefers_less_equity)
    weights, audit = dd_module.certify_resampled_candidates(
        context, projected_mean=projected, raw_mean=raw,
        house_anchor_bps=anchor, validation=validation,
    )
    assert audit["significance_candidate_label"] == dd_module.LABEL_RAW_MEAN
    assert weights[equities] == pytest.approx(0.50, abs=1e-4)
    assert audit["house_anchor_validated_rank"] == 2

    # Anker vorne: Testkandidat bleibt der beste NICHT-Anker-Kandidat.
    def _prefers_more_equity(validation_context, weights_array, *, validation_seed):
        evaluation = real(validation_context, weights_array, validation_seed=validation_seed)
        evaluation["validated_objective"] = -float(weights_array[equities])
        return evaluation

    monkeypatch.setattr(dd_module, "validated_drawdown_evaluation", _prefers_more_equity)
    _weights, audit = dd_module.certify_resampled_candidates(
        context, projected_mean=projected, raw_mean=raw,
        house_anchor_bps=anchor, validation=validation,
    )
    assert audit["house_anchor_validated_rank"] == 0
    assert audit["significance_candidate_label"] != dd_module.LABEL_HOUSE_ANCHOR
    assert audit["significance_candidate_weights_bps"] != anchor


def _assert_published_contract(rows):
    from services.optimizer.goal_attribution import (
        EVALUATION_SCOPE_JOINT_PLAN,
        EVALUATION_SCOPE_PENALTY_INTERNAL,
        EVALUATION_SCOPE_PRIORITY_FUNDED,
    )

    scopes = [row.get("evaluation_scope") for row in rows]
    assert EVALUATION_SCOPE_PENALTY_INTERNAL not in scopes, scopes
    assert scopes.count(EVALUATION_SCOPE_JOINT_PLAN) == 1, scopes
    assert EVALUATION_SCOPE_PRIORITY_FUNDED in scopes, scopes


def test_insignificant_house_fallback_publishes_the_goal_attribution_contract(monkeypatch):
    """CIO-Entscheid 3: nicht signifikant -> Hausmatrix; die publizierte
    Zielerreichung folgt dem Vertrag priority_funded + genau eine joint_plan-
    Zeile, nicht der internen Joint-Sicht der Chance-Penalty."""
    real_test = solver_module.paired_bootstrap_improvement

    def _not_significant(loss_pair, **kwargs):
        stats = real_test(loss_pair, **kwargs)
        return {**stats, "p_value": 0.5, "significant": False}

    monkeypatch.setattr(solver_module, "paired_bootstrap_improvement", _not_significant)
    result = _solve(monkeypatch, mode=OBJECTIVE_GOAL_SHORTFALL)
    significance = result.resampling["significance"]
    assert result.resampling["decision"] == "house_matrix", significance
    assert result.weights_bps == significance["house_anchor_projected_bps"]
    _assert_published_contract(result.goal_achievability)


def test_resampled_midpoint_fallback_publishes_the_goal_attribution_contract(monkeypatch):
    """Kein Bag liefert eine zulaessige Allokation -> House-Matrix-Mittelwert
    (OD-5); auch dieser Fallback publiziert den neuen Vertrag."""
    real_select = solver_module._select_cube_candidate

    def _no_candidate(context, **kwargs):
        selection = real_select(context, **kwargs)
        selection.weights = None
        return selection

    monkeypatch.setattr(solver_module, "_select_cube_candidate", _no_candidate)
    result = _solve(monkeypatch, mode=OBJECTIVE_GOAL_SHORTFALL)
    assert result.status == "fallback_house_matrix"
    assert result.resampling["decision"] == "fallback_house_matrix"
    _assert_published_contract(result.goal_achievability)
