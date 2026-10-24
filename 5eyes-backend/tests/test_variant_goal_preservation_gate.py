"""VARIANT-GOAL-PRESERVATION-GATE-001 (Codex-Befund 2026-10-18, Engine v12).

Befund (docs/audits/2026-10-18-core-stack-034ee30-implementation-revalidation.md,
"Neuer P0 - Risiko kann weiterhin Zielerosion kaufen"): in den
Risikomass-Varianten (min_volatility, max_drawdown, cvar_return, max_return)
pruefte ``_significance_vs_house_anchor`` nach der Zielebene einen SKALAR
``(Ziel + Risiko)``. Ein materieller Risikogewinn konnte so eine strikt
schlechtere Zielebene auskaufen (Haus goal=0.000/risk=0.080 vs. Kandidat
0.001/0.070 -> ``optimizer``).

Vertrag ab Engine v12 (lexikographisch, nicht verrechenbar):

1. Goal-Preservation-Gate: der Kandidat darf weder auf der Zielebene noch auf
   der Stufe-1-Zielebene (harte/primaere Ziele, ``protected_goal_level``)
   signifikant schlechter sein als die Hausquote -- gepaarter
   Einheiten-Bootstrap mit nullzentriertem Shift-p-Wert (H0: nicht
   schlechter), dieselben Bausteine wie die Default-Offenlegung (#649).
2. Erst danach: Zielebene signifikant besser ODER Risikomass allein
   signifikant besser UND material (>= 50 bps).

Der Default-Pfad (House-Prior) ist unveraendert.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy.orm import configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users,
    wealth,
)

configure_mappers()

import services.optimizer.solver as solver_module  # noqa: E402
from services.optimizer.objective_contract import ObjectiveContractV1  # noqa: E402
from services.optimizer.resampling import (  # noqa: E402
    DEFAULT_RESAMPLING,
    ResamplingConfig,
    resampling_model_basis,
)

N_PATHS = 2000
VARIANTS = ["min_volatility", "max_drawdown", "cvar_return", "max_return"]

ANCHOR = {"equities": 6000, "bonds": 3000, "real_estate": 500,
          "alternatives": 300, "liquidity": 200}
CANDIDATE = {"equities": 5500, "bonds": 3000, "real_estate": 0,
             "alternatives": 1000, "liquidity": 500}


# ---------------------------------------------------------------------------
# Codex-Reproducer (wortgleich uebernommen, ohne xfail)
# ---------------------------------------------------------------------------


def test_material_risk_gain_must_not_buy_any_goal_erosion(
    monkeypatch: pytest.MonkeyPatch,
):
    """docs/audits/reproducers/test_2026_10_18_house_first_significance_adversarial.py"""
    n_paths = 200
    anchor = dict(ANCHOR)
    candidate = dict(CANDIDATE)
    context = SimpleNamespace(
        n_paths=n_paths,
        objective_contract=ObjectiveContractV1(
            objective_mode="min_volatility",
            goal_weighting_mode="equal",
        ),
    )

    monkeypatch.setattr(
        solver_module,
        "_project_house_anchor",
        lambda _context, _anchor: (dict(anchor), None),
    )

    def fake_components(
        _validation_context,
        _anchor_w,
        _candidate_w,
        *,
        validation_seed=None,
    ):
        del validation_seed

        def pair(_indices):
            return (0.000, 0.080), (0.001, 0.070)

        return pair

    monkeypatch.setattr(
        solver_module,
        "_context_loss_components_on_validation",
        fake_components,
    )

    verdict = solver_module._significance_vs_house_anchor(
        context,
        candidate_bps=candidate,
        house_anchor_bps=anchor,
        config=ResamplingConfig(n_bootstrap=100),
        validation=(context, 4242, "audit-cube"),
    )

    assert verdict["improvement"] < 0.0  # goal-only comparison rejects it
    assert verdict["risk_measure_test"]["risk_improvement"] == pytest.approx(0.010)
    assert verdict["risk_measure_test"]["material"] is True
    assert verdict["decision"] == "house_matrix"
    # Evidence getrennt: Gate, Risikotest, Entscheid.
    gate = verdict["goal_preservation"]
    assert gate["passed"] is False
    assert gate["goal_level"]["significantly_worse"] is True
    assert verdict["reason"] == "goal_level_significantly_worse"


# ---------------------------------------------------------------------------
# Synthetische Pfadverluste je Variante
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


def _decide(monkeypatch, context, *, mode, anchor_goal, candidate_goal,
            anchor_risk, candidate_risk, anchor_stage1=None,
            candidate_stage1=None):
    """Entscheid mit vorgegebenen Pfadverlusten (Zielebene/Stufe 1 je Pfad,
    Risikomass konstant)."""

    def _fake_components(validation_context, anchor_w, candidate_w, *, validation_seed=None):
        def pair(idx):
            sel = slice(None) if idx is None else idx
            anchor = (float(np.mean(anchor_goal[sel])), float(anchor_risk))
            cand = (float(np.mean(candidate_goal[sel])), float(candidate_risk))
            if anchor_stage1 is not None:
                anchor += (float(np.mean(anchor_stage1[sel])),)
                cand += (float(np.mean(candidate_stage1[sel])),)
            return anchor, cand
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
    anchor_bps, _ = solver_module._project_house_anchor(ctx, ANCHOR)
    candidate_bps, _ = solver_module._project_house_anchor(ctx, CANDIDATE)
    assert anchor_bps != candidate_bps
    return solver_module._significance_vs_house_anchor(
        ctx,
        candidate_bps=candidate_bps,
        house_anchor_bps=ANCHOR,
        config=DEFAULT_RESAMPLING,
        validation=validation,
    )


@pytest.mark.parametrize("mode", VARIANTS)
def test_deterministic_goal_erosion_is_not_bought_by_large_risk_gain(
    monkeypatch, small_context, mode,
):
    """1 bp Zielerosion gegen 500 bps Risikogewinn: nicht verrechenbar."""
    sig = _decide(
        monkeypatch, small_context, mode=mode,
        anchor_goal=np.zeros(N_PATHS), candidate_goal=np.full(N_PATHS, 1.0e-4),
        anchor_risk=0.1000, candidate_risk=0.0500,
    )
    assert sig["decision"] == "house_matrix", sig
    assert sig["reason"] == "goal_level_significantly_worse"
    assert sig["goal_preservation"]["passed"] is False
    assert sig["risk_measure_test"]["material"] is True
    assert sig["risk_measure_test"]["significant"] is True


@pytest.mark.parametrize("mode", VARIANTS)
def test_stage1_erosion_blocks_even_with_equal_total_goal_level(
    monkeypatch, small_context, mode,
):
    """Gesamte Zielebene gleich, aber harte/primaere Ziele (Stufe 1) schlechter."""
    rng = np.random.default_rng(7)
    sig = _decide(
        monkeypatch, small_context, mode=mode,
        anchor_goal=np.zeros(N_PATHS), candidate_goal=np.zeros(N_PATHS),
        anchor_risk=0.0800, candidate_risk=0.0700,
        anchor_stage1=np.zeros(N_PATHS),
        candidate_stage1=np.where(rng.random(N_PATHS) < 0.10, 1.0, 0.0),
    )
    assert sig["decision"] == "house_matrix", sig
    assert sig["reason"] == "stage1_goal_level_significantly_worse"
    gate = sig["goal_preservation"]
    assert gate["passed"] is False
    assert gate["goal_level"]["significantly_worse"] is False
    assert gate["stage1_goal_level"]["significantly_worse"] is True


def test_stage1_erosion_blocks_a_significant_total_goal_gain(monkeypatch, small_context):
    """Wunschziele besser auf Kosten harter Ziele: auch die Ziel-Route ist gesperrt."""
    rng = np.random.default_rng(3)
    sig = _decide(
        monkeypatch, small_context, mode="max_drawdown",
        anchor_goal=np.where(rng.random(N_PATHS) < 0.30, 1.0, 0.0),
        candidate_goal=np.where(rng.random(N_PATHS) < 0.05, 1.0, 0.0),
        anchor_risk=0.2000, candidate_risk=0.2000,
        anchor_stage1=np.zeros(N_PATHS),
        candidate_stage1=np.where(rng.random(N_PATHS) < 0.10, 1.0, 0.0),
    )
    assert sig["significant"] is True  # Zielebene gesamt signifikant besser ...
    assert sig["decision"] == "house_matrix", sig  # ... aber Stufe 1 erodiert
    assert sig["reason"] == "stage1_goal_level_significantly_worse"


@pytest.mark.parametrize("mode", VARIANTS)
def test_preserved_goals_and_material_risk_gain_choose_optimizer(
    monkeypatch, small_context, mode,
):
    """Gleiche Zielverteilung (nur Rauschen) + materieller Risikogewinn -> Optimierer."""
    rng = np.random.default_rng(42)
    base = np.where(rng.random(N_PATHS) < 0.20, 1.0, 0.0)
    sig = _decide(
        monkeypatch, small_context, mode=mode,
        anchor_goal=base, candidate_goal=base.copy(),
        anchor_risk=0.0800, candidate_risk=0.0700,
        anchor_stage1=base, candidate_stage1=base.copy(),
    )
    assert sig["goal_preservation"]["passed"] is True
    assert sig["decision"] == "optimizer", sig
    assert sig["reason"] == "significant_material_risk_improvement"
    risk = sig["risk_measure_test"]
    # Risikotest auf dem Risikomass ALLEIN (kein Skalar Ziel + Risiko mehr).
    assert risk["comparison"] == "risk_measure_only"
    assert risk["anchor_objective"] == pytest.approx(0.08)
    assert risk["candidate_objective"] == pytest.approx(0.07)


def test_noise_level_goal_difference_passes_the_gate(monkeypatch, small_context):
    """Nicht signifikant schlechter (unabhaengiges Rauschen) ist kein Gate-Fail."""
    rng = np.random.default_rng(5)
    sig = _decide(
        monkeypatch, small_context, mode="cvar_return",
        anchor_goal=np.where(rng.random(N_PATHS) < 0.20, 1.0, 0.0),
        candidate_goal=np.where(rng.random(N_PATHS) < 0.20, 1.0, 0.0),
        anchor_risk=0.0800, candidate_risk=0.0700,
    )
    gate = sig["goal_preservation"]
    assert gate["goal_level"]["significantly_worse"] is False
    assert gate["stage1_goal_level"] is None  # 2-Tupel: keine Stufe-1-Komponente
    assert gate["passed"] is True


def test_default_mode_is_unchanged_no_gate(monkeypatch, small_context):
    """Default (goal_shortfall): kein Gate-Block, Entscheid nur auf der Zielebene."""
    sig = _decide(
        monkeypatch, small_context, mode="goal_shortfall",
        anchor_goal=np.zeros(N_PATHS), candidate_goal=np.zeros(N_PATHS),
        anchor_risk=0.0800, candidate_risk=0.0100,
    )
    assert sig["decision"] == "house_matrix"
    assert sig["reason"] == "goal_improvement_not_significant"
    assert "goal_preservation" not in sig
    assert "risk_measure_test" not in sig


# ---------------------------------------------------------------------------
# Echte Komponenten: Stufe-1-Ebene nur in Varianten
# ---------------------------------------------------------------------------


def test_real_components_carry_stage1_level_only_in_variants(small_context):
    anchor_bps, _ = solver_module._project_house_anchor(small_context, ANCHOR)
    candidate_bps, _ = solver_module._project_house_anchor(small_context, CANDIDATE)
    a = solver_module._trusted_weights_bps_to_array(anchor_bps)
    c = solver_module._trusted_weights_bps_to_array(candidate_bps)

    default_pair = solver_module._context_loss_components_on_validation(
        small_context, a, c, validation_seed=4242,
    )(None)
    assert all(len(parts) == 2 for parts in default_pair)

    variant_ctx = replace(
        small_context,
        objective_contract=ObjectiveContractV1(
            objective_mode="min_volatility",
            goal_weighting_mode=small_context.objective_contract.goal_weighting_mode,
        ),
    )
    pair = solver_module._context_loss_components_on_validation(
        variant_ctx, a, c, validation_seed=4242,
    )
    full = pair(None)
    assert all(len(parts) == 3 for parts in full)
    # Stufe 1 = protected_goal_level der harten Pensionsausgabe.
    assert solver_module._stage1_liabilities(variant_ctx)
    for parts, w in zip(full, (a, c)):
        inputs = solver_module._evaluation_inputs(variant_ctx, w)
        expected, _ = solver_module._protected_level_from_inputs(variant_ctx, inputs)
        assert parts[2] == pytest.approx(expected, rel=1e-9, abs=1e-12)
    # Teilmengen (Bootstrap) funktionieren.
    sub = pair(np.arange(0, 100))
    assert all(len(parts) == 3 and np.isfinite(parts[2]) for parts in sub)


def test_goal_preservation_is_bound_in_the_model_basis():
    payload = {
        "enabled": True,
        "significance": {
            "decision": "house_matrix",
            "goal_preservation": {"passed": False, "version": "x"},
        },
    }
    basis = resampling_model_basis(payload)
    assert basis["significance"]["goal_preservation"] == {"passed": False, "version": "x"}


def test_engine_version_bumped():
    assert solver_module.OPTIMIZER_ENGINE_VERSION == "saa_resampled_v16"
