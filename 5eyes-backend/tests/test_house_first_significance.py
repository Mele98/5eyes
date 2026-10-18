"""HOUSE-FIRST-SIGNIFICANCE-001 (CIO-Entscheid 2026-10-18).

Befund: auf allen CH-Golden-Mandaten sind alle Ziele sicher erreicht
(p = 1). Dann entschied allein der Tiebreak ``kappa * w' Sigma w`` -- und der
Signifikanztest gegen die Hausmatrix waehlte den Optimierer mit p = 0.0025
(= 1/(B+1)), weil eine DETERMINISTISCHE Varianzdifferenz in jeder
Bootstrap-Replikation dasselbe Vorzeichen hat. Ergebnis waren Eckloesungen
(Alternative = Gold auf Bandmaximum, Immobilien auf Bandminimum, Aktien auf
Bandminimum) fuer 2-7 bps weniger Volatilitaet -- Scheinoptimierung auf
Schaetzfehlern der Korrelation gegen die Hausmeinung (IC).

Entscheid: "Hausmatrix, solange die Ziele mit ihr gleich sicher erreicht
sind." Der Test entscheidet auf der Zielebene (Ziel-Fehlbetrag +
Chance-Strafe); in den Risikomass-Varianten zusaetzlich auf dem Risikomass,
aber nur mit Materialitaetsschwelle (50 bps).

Messung: docs/planning/2026-10-18-importance-sampling-ess.md.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from database import Base  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users,
    wealth,
)

configure_mappers()

import services.optimizer.solver as solver_module  # noqa: E402
from services.optimizer.objective_contract import ObjectiveContractV1  # noqa: E402
from services.optimizer.resampling import (  # noqa: E402
    DEFAULT_RESAMPLING,
    RISK_MEASURE_MATERIALITY,
)
from services.optimizer.scenario_engine import BUCKET_ORDER  # noqa: E402

N_PATHS = 2000


# ---------------------------------------------------------------------------
# Entscheidungslogik (synthetische Zielebene/Risikoebene, schnell)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def small_context():
    from test_optimizer_context import _cma, _house_matrix, _pension_goal

    return solver_module.build_optimizer_context(
        cma=_cma(), goals=[_pension_goal()], house_matrix_row=_house_matrix(),
        score_x10=70, advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * 10, horizon_years=10,
        n_paths=200, seed=20261018,
    )


ANCHOR = {"equities": 6000, "bonds": 3000, "real_estate": 500,
          "alternatives": 300, "liquidity": 200}
CANDIDATE = {"equities": 5500, "bonds": 3000, "real_estate": 0,
             "alternatives": 1000, "liquidity": 500}


def _decide(monkeypatch, context, *, mode, anchor_goal, candidate_goal,
            anchor_risk, candidate_risk):
    """Signifikanzentscheid mit vorgegebenen Pfad-Verlusten.

    ``*_goal`` sind Arrays je Pfad (Zielebene = Mittel der Auswahl),
    ``*_risk`` Konstanten (deterministische Risikoebene, wie Tiebreak bzw.
    ein Risikomass ohne Stichprobenstreuung)."""

    def _fake_components(validation_context, anchor_w, candidate_w, *, validation_seed=None):
        def pair(idx):
            sel = slice(None) if idx is None else idx
            return (
                (float(np.mean(anchor_goal[sel])), float(anchor_risk)),
                (float(np.mean(candidate_goal[sel])), float(candidate_risk)),
            )
        return pair

    monkeypatch.setattr(
        solver_module, "_context_loss_components_on_validation", _fake_components,
    )
    ctx = replace(
        context,
        objective_contract=ObjectiveContractV1(
            objective_mode=mode,
            goal_weighting_mode=context.objective_contract.goal_weighting_mode,
        ),
    )
    validation = (replace(ctx, n_paths=N_PATHS), 4242, "cube-hash")
    anchor_bps, _reason = solver_module._project_house_anchor(ctx, ANCHOR)
    candidate_bps, _reason = solver_module._project_house_anchor(ctx, CANDIDATE)
    assert anchor_bps != candidate_bps
    return solver_module._significance_vs_house_anchor(
        ctx,
        candidate_bps=candidate_bps,
        house_anchor_bps=ANCHOR,
        config=DEFAULT_RESAMPLING,
        validation=validation,
    )


def test_reproducer_goals_met_lower_variance_keeps_house_matrix(monkeypatch, small_context):
    """Rot vor dem Fix: beide erfuellen alle Ziele (Zielebene 0), der
    Kandidat hat nur den kleineren Tiebreak -> frueher p = 0.0025 und
    "optimizer". Jetzt: Hausmatrix."""
    zero = np.zeros(N_PATHS)
    sig = _decide(
        monkeypatch, small_context, mode="goal_shortfall",
        anchor_goal=zero, candidate_goal=zero,
        anchor_risk=2.187e-2, candidate_risk=2.180e-2,
    )
    assert sig["decision"] == "house_matrix", sig
    assert sig["reason"] == "goal_improvement_not_significant"
    assert sig["improvement"] == 0.0
    assert sig["significant"] is False
    assert sig["comparison"] == "goal_level"


def test_unmet_goals_still_choose_a_significantly_better_optimizer(monkeypatch, small_context):
    """Ziele mit der Hausmatrix NICHT sicher erreicht und der Kandidat ist
    auf der Zielebene signifikant besser -> Optimierer, auch wenn er die
    hoehere Volatilitaet hat (die Ziele gehen vor)."""
    rng = np.random.default_rng(7)
    anchor_goal = np.where(rng.random(N_PATHS) < 0.30, 1.0, 0.0)
    candidate_goal = np.where(rng.random(N_PATHS) < 0.10, 1.0, 0.0)
    sig = _decide(
        monkeypatch, small_context, mode="goal_shortfall",
        anchor_goal=anchor_goal, candidate_goal=candidate_goal,
        anchor_risk=1.0e-2, candidate_risk=1.5e-2,
    )
    assert sig["decision"] == "optimizer", sig
    assert sig["reason"] == "significant_goal_improvement"
    assert sig["p_value"] <= 0.05


def test_unmet_goals_with_noise_only_keep_house_matrix(monkeypatch, small_context):
    """Gegenprobe: gleiche Zielerreichung bis auf einen einzelnen Pfad
    (der gemessene Golden-Fall 8.1e-9) ist nicht signifikant."""
    anchor_goal = np.zeros(N_PATHS)
    anchor_goal[17] = 8.110173291668927e-09 * N_PATHS
    sig = _decide(
        monkeypatch, small_context, mode="goal_shortfall",
        anchor_goal=anchor_goal, candidate_goal=np.zeros(N_PATHS),
        anchor_risk=2.187e-2, candidate_risk=1.420e-2,
    )
    assert sig["decision"] == "house_matrix", sig
    assert sig["p_value"] > 0.05


@pytest.mark.parametrize("mode", ["min_volatility", "max_drawdown", "cvar_return", "max_return"])
def test_variant_immaterial_risk_gain_keeps_house_matrix(monkeypatch, small_context, mode):
    """Risikomass-Variante: 5 bps weniger Risiko sind deterministisch
    "signifikant", aber nicht material -> Hausmatrix."""
    zero = np.zeros(N_PATHS)
    sig = _decide(
        monkeypatch, small_context, mode=mode,
        anchor_goal=zero, candidate_goal=zero,
        anchor_risk=0.0800, candidate_risk=0.0795,
    )
    assert sig["decision"] == "house_matrix", sig
    assert sig["reason"] == "risk_improvement_not_material"
    risk = sig["risk_measure_test"]
    assert risk["significant"] is True and risk["material"] is False
    assert risk["risk_improvement"] == pytest.approx(0.0005)
    assert risk["materiality_threshold"] == RISK_MEASURE_MATERIALITY == 0.005


@pytest.mark.parametrize("mode", ["min_volatility", "max_drawdown", "cvar_return", "max_return"])
def test_variant_material_risk_gain_chooses_optimizer(monkeypatch, small_context, mode):
    zero = np.zeros(N_PATHS)
    sig = _decide(
        monkeypatch, small_context, mode=mode,
        anchor_goal=zero, candidate_goal=zero,
        anchor_risk=0.0800, candidate_risk=0.0700,
    )
    assert sig["decision"] == "optimizer", sig
    assert sig["reason"] == "significant_material_risk_improvement"
    assert sig["decision_level"] == "goal_level_plus_risk_measure"
    assert sig["risk_measure_test"]["material"] is True


def test_variant_materiality_boundary(monkeypatch, small_context):
    """Genau auf der Schwelle zaehlt als material (>=)."""
    zero = np.zeros(N_PATHS)
    sig = _decide(
        monkeypatch, small_context, mode="min_volatility",
        anchor_goal=zero, candidate_goal=zero,
        anchor_risk=0.0850, candidate_risk=0.0850 - RISK_MEASURE_MATERIALITY,
    )
    assert sig["risk_measure_test"]["material"] is True
    assert sig["decision"] == "optimizer"


def test_variant_material_risk_gain_bought_with_goal_loss_is_not_taken(monkeypatch, small_context):
    """Material weniger Risiko, aber auf der Zielebene deutlich schlechter:
    der Skalar (Risikomass + Chance-Strafe) ist nicht besser -> Hausmatrix."""
    rng = np.random.default_rng(11)
    anchor_goal = np.zeros(N_PATHS)
    candidate_goal = np.where(rng.random(N_PATHS) < 0.25, 1.0, 0.0)
    sig = _decide(
        monkeypatch, small_context, mode="min_volatility",
        anchor_goal=anchor_goal, candidate_goal=candidate_goal,
        anchor_risk=0.0800, candidate_risk=0.0700,
    )
    assert sig["decision"] == "house_matrix", sig
    assert sig["reason"] == "risk_improvement_not_significant"


def test_variant_significant_goal_gain_wins_without_risk_materiality(monkeypatch, small_context):
    """Auch in einer Variante gehen die Ziele vor: signifikant sicherere
    Zielerreichung -> Optimierer, ohne Materialitaetspruefung."""
    rng = np.random.default_rng(3)
    anchor_goal = np.where(rng.random(N_PATHS) < 0.30, 1.0, 0.0)
    candidate_goal = np.where(rng.random(N_PATHS) < 0.05, 1.0, 0.0)
    sig = _decide(
        monkeypatch, small_context, mode="max_drawdown",
        anchor_goal=anchor_goal, candidate_goal=candidate_goal,
        anchor_risk=0.2000, candidate_risk=0.2010,
    )
    assert sig["decision"] == "optimizer", sig
    assert sig["reason"] == "significant_goal_improvement"
    assert "risk_measure_test" not in sig


# ---------------------------------------------------------------------------
# Reproducer End-to-End: CH-Golden-Mandat (Score 5, alle Ziele p = 1)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def golden_score5(tmp_path_factory):
    from test_golden_snapshot_ch_regression import COMBOS, _seed_ch_mandate
    from models.mandates import Mandate
    from services.portfolio_engine import generate_target_allocation

    combo = next(c for c in COMBOS if c["name"] == "bucket5_ausgewogen_default_prefs")
    db_path = tmp_path_factory.mktemp("house_first") / "house_first.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    advisor_id, _client_id, mandate_id, _assessment = _seed_ch_mandate(
        session_factory, suffix=combo["name"], score_x10=combo["score_x10"],
    )
    captured: dict = {}
    original = solver_module.run_solver

    def _capture(**kwargs):
        result = original(**kwargs)
        captured.setdefault("result", result)
        return result

    solver_module.run_solver = _capture
    try:
        with session_factory() as session:
            mandate = session.query(Mandate).filter(Mandate.id == mandate_id).first()
            generated = generate_target_allocation(
                session, mandate, advisor_id, preferences=combo["preferences"],
            )
    finally:
        solver_module.run_solver = original
    try:
        yield {"result": captured["result"], "generated": generated}
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_golden_mandate_with_certain_goals_publishes_the_house_matrix(golden_score5):
    """Reproducer (rot vor HOUSE-FIRST-SIGNIFICANCE-001): Score 5 lieferte
    40/45/5/7/3 statt der Hausmatrix 48/35/10/5/2 mit p = 0.0025, obwohl
    beide Allokationen alle Ziele mit p = 1 erreichen."""
    result = golden_score5["result"]
    significance = result.resampling["significance"]
    rows = [row for row in result.goal_achievability]
    assert rows and all(float(row["probability"]) == 1.0 for row in rows), rows
    assert significance["decision"] == "house_matrix", significance
    assert significance["reason"] in {
        "goal_improvement_not_significant", "identical_to_house_anchor",
    }
    assert result.resampling["decision"] == "house_matrix"
    assert result.weights_bps == significance["house_anchor_projected_bps"]
    target = golden_score5["generated"]["target_allocation"]
    assert [
        target.target_equities_bps, target.target_bonds_bps,
        target.target_real_estate_bps, target.target_alternatives_bps,
        target.target_liquidity_bps,
    ] == [significance["house_anchor_projected_bps"][b] for b in BUCKET_ORDER]
    assert any(
        "Hausmatrix-Zielquote beibehalten" in line
        and "Vergleich auf der Zielebene" in line
        for line in result.reasoning
    )
