"""Schaetzgroesse, p-Wert-Semantik und Mehrfachvergleich (Engine v14).

Codex-Reproducer ``docs/audits/reproducers/
test_2026_10_18_resampling_estimand_and_pvalue_adversarial.py``: seit Engine
v7 als ``tests/test_stat_contract_resampling_estimand_and_pvalue.py``
uebernommen (Assertions unveraendert, zusaetzlich ein Stub fuer
``_house_midpoint_fallback_result``) und gruen. Sein Rotlauf unter
``--runxfail`` gegen develop ist Harness-Drift des Reproducers: ohne den Stub
endet der Fallback-Pfad in einem AttributeError des SimpleNamespace-Contexts
-- die Produktion ist dort bereits fail-closed (Mindestquote 90 %), es wird
kein Mittel publiziert. Der p-Wert-Test ist auch als Reproducer gruen.

SIGNIFICANCE-MULTIPLICITY-001: in den Risikomass-Varianten begruendet die
Ablehnung EINER von zwei Ueberlegenheitshypothesen (Zielebene ODER
Risikomass) die Abweichung von der Hausquote. Bis v13 lief jede mit
alpha = 5 %; die familienweise Fehlerrate lag simuliert bei 8.25 %. Ab v14
Holm/Bonferroni (je Test alpha/2), Familie offengelegt.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import services.optimizer.solver as solver_module
from services.optimizer import resampling as rs
from services.optimizer.objective_contract import ObjectiveContractV1
from services.optimizer.objective_variants import OBJECTIVE_GOAL_SHORTFALL
from services.optimizer.resampling import (
    ResamplingConfig,
    bootstrap_seed,
    paired_bootstrap_improvement,
    resampling_model_basis,
)
from services.optimizer.scenario_engine import sampling_unit_ids


# ---------------------------------------------------------------------------
# SIGNIFICANCE-MULTIPLICITY-001
# ---------------------------------------------------------------------------

ANCHOR = {"equities": 6000, "bonds": 3000, "real_estate": 500,
          "alternatives": 300, "liquidity": 200}
CANDIDATE = {"equities": 5500, "bonds": 3000, "real_estate": 0,
             "alternatives": 1000, "liquidity": 500}
N_PATHS = 200
VALIDATION_SEED = 4242
N_BOOTSTRAP = 199  # alpha (B + 1) ganzzahlig fuer 5 % und 2.5 %


def _context(mode: str):
    return SimpleNamespace(
        n_paths=N_PATHS,
        objective_contract=ObjectiveContractV1(
            objective_mode=mode, goal_weighting_mode="equal",
        ),
    )


def _install(monkeypatch, goal_gain: np.ndarray, risk_gain: np.ndarray):
    """Pfadweise Verbesserungen Haus - Kandidat je Ebene (Kandidat = 0)."""
    monkeypatch.setattr(
        solver_module, "_project_house_anchor",
        lambda _context, _anchor: (dict(ANCHOR), None),
    )

    def fake_components(_vc, _aw, _cw, *, validation_seed=None):
        del validation_seed

        def pair(idx):
            g = goal_gain if idx is None else goal_gain[idx]
            r = risk_gain if idx is None else risk_gain[idx]
            return (float(np.mean(g)), float(np.mean(r))), (0.0, 0.0)

        return pair

    monkeypatch.setattr(
        solver_module, "_context_loss_components_on_validation", fake_components,
    )


def _verdict(mode: str, alpha: float = 0.05):
    context = _context(mode)
    return solver_module._significance_vs_house_anchor(
        context,
        candidate_bps=dict(CANDIDATE),
        house_anchor_bps=dict(ANCHOR),
        config=ResamplingConfig(n_bootstrap=N_BOOTSTRAP, significance_alpha=alpha),
        validation=(context, VALIDATION_SEED, "audit-cube"),
    )


def _p_value(gain: np.ndarray) -> float:
    units = sampling_unit_ids(N_PATHS, antithetic=True)
    stats = paired_bootstrap_improvement(
        lambda idx: (float(np.mean(gain if idx is None else gain[idx])), 0.0),
        n_paths=N_PATHS, n_bootstrap=N_BOOTSTRAP, alpha=0.05,
        seed=bootstrap_seed(VALIDATION_SEED), sampling_unit_ids=units,
        sampling_unit="antithetic_pair",
    )
    return float(stats["p_value"])


def _gain_with_p_between(lower: float, upper: float, *, scale: float, shift: float = 0.0):
    """Deterministisch (fester Seed): kleinste Lage, deren einseitiger
    p-Wert in (lower, upper] liegt."""
    noise = np.random.default_rng(31).standard_normal(N_PATHS) * scale
    noise -= noise.mean()
    for k in range(1, 400):
        gain = noise + shift + k * scale * 0.005
        p = _p_value(gain)
        if lower < p <= upper:
            return gain, p
    raise AssertionError("kein Fall im p-Fenster gefunden")


def test_goal_channel_p_between_half_alpha_and_alpha_no_longer_deviates(monkeypatch):
    """Variante: Zielebene p in (2.5 %, 5 %], Risiko neutral.

    Bis v13 ``optimizer`` (Test mit alpha = 5 % ohne Familienkorrektur);
    ab v14 bleibt die Hausquote."""
    gain, p = _gain_with_p_between(0.025, 0.05, scale=0.01)
    _install(monkeypatch, gain, np.zeros(N_PATHS))
    verdict = _verdict("min_volatility")
    assert 0.025 < verdict["p_value"] <= 0.05 and verdict["p_value"] == pytest.approx(p)
    assert verdict["decision"] == "house_matrix"
    assert verdict["reason"] == "risk_improvement_not_significant"
    family = verdict["multiple_comparison"]
    assert family["method"] == rs.MULTIPLICITY_METHOD
    assert family["hypotheses"] == ["goal_level", "risk_measure_only"]
    assert family["per_test_alpha"] == pytest.approx(0.025)
    assert verdict["alpha"] == pytest.approx(0.025)


def test_material_risk_channel_p_between_half_alpha_and_alpha_no_longer_deviates(monkeypatch):
    """Variante: Risikomass material (>= 50 bps), p in (2.5 %, 5 %]."""
    gain, p = _gain_with_p_between(
        0.025, 0.05, scale=0.04, shift=rs.RISK_MEASURE_MATERIALITY,
    )
    assert float(np.mean(gain)) >= rs.RISK_MEASURE_MATERIALITY
    _install(monkeypatch, np.zeros(N_PATHS), gain)
    verdict = _verdict("max_return")
    risk = verdict["risk_measure_test"]
    assert risk["material"] is True
    assert 0.025 < risk["p_value"] <= 0.05 and risk["p_value"] == pytest.approx(p)
    assert risk["significant"] is False
    assert verdict["decision"] == "house_matrix"
    assert verdict["reason"] == "risk_improvement_not_significant"


def test_clear_improvement_still_deviates_in_variants(monkeypatch):
    """Keine Ueberkorrektur: p <= alpha/2 -> Optimierer wie bisher."""
    gain, p = _gain_with_p_between(0.0, 0.02, scale=0.01)
    _install(monkeypatch, gain, np.zeros(N_PATHS))
    verdict = _verdict("cvar_return")
    assert p <= 0.025
    assert verdict["decision"] == "optimizer"
    assert verdict["reason"] == "significant_goal_improvement"


def test_goal_shortfall_single_test_keeps_full_alpha(monkeypatch):
    """Ohne Prior-Anker im Default-Modus ist die Familie ein Test: unveraendert."""
    gain, _p = _gain_with_p_between(0.025, 0.05, scale=0.01)
    _install(monkeypatch, gain, np.zeros(N_PATHS))
    verdict = _verdict(OBJECTIVE_GOAL_SHORTFALL)
    assert verdict["multiple_comparison"]["family_size"] == 1
    assert verdict["alpha"] == pytest.approx(0.05)
    assert verdict["decision"] == "optimizer"


def test_goal_preservation_gate_keeps_unadjusted_alpha(monkeypatch):
    """Die Gate-Pruefungen ('signifikant schlechter') gehoeren nicht zur
    Familie: sie koennen eine Abweichung nur verhindern (konservativ)."""
    gain, _p = _gain_with_p_between(0.025, 0.05, scale=0.01)
    _install(monkeypatch, -gain, np.full(N_PATHS, 0.02))
    verdict = _verdict("min_volatility")
    gate = verdict["goal_preservation"]["goal_level"]
    assert gate["alpha"] == pytest.approx(0.05)
    assert gate["significantly_worse"] is True
    assert verdict["decision"] == "house_matrix"
    assert verdict["reason"] == "goal_level_significantly_worse"


def test_family_wise_error_rate_under_global_null_is_controlled(monkeypatch):
    """Property (fester Seed, 800 Welten): beide Nullhypothesen wahr (keine
    Verbesserung, Risiko-Rauschen so skaliert, dass Signifikanz und
    Materialitaet zusammenfallen). Anteil grundloser Abweichungen <= alpha
    plus 3 Monte-Carlo-Standardfehler. Unkorrigiert (je Test 5 %) liegt er
    in derselben Simulation deutlich darueber."""
    rng = np.random.default_rng(2026_10_24)
    n_worlds = 800
    alpha = 0.05
    # SE des Mittels ~ 0.003 -> einseitige 5 %-Schwelle ~ 0.005 = Materialitaet.
    risk_scale = 0.003 * np.sqrt(N_PATHS)
    deviations_fixed = 0
    deviations_unadjusted = 0
    for _ in range(n_worlds):
        goal = rng.standard_normal(N_PATHS)
        risk = rng.standard_normal(N_PATHS) * risk_scale
        _install(monkeypatch, goal, risk)
        deviations_fixed += _verdict("min_volatility")["decision"] == "optimizer"
        goal_p = _p_value(goal)
        risk_p = _p_value(risk)
        unadjusted = (np.mean(goal) > 0 and goal_p <= alpha) or (
            np.mean(risk) > 0 and risk_p <= alpha
            and np.mean(risk) >= rs.RISK_MEASURE_MATERIALITY
        )
        deviations_unadjusted += bool(unadjusted)
    tolerance = 3.0 * np.sqrt(alpha * (1 - alpha) / n_worlds)
    rate_fixed = deviations_fixed / n_worlds
    rate_unadjusted = deviations_unadjusted / n_worlds
    assert rate_fixed <= alpha + tolerance
    assert rate_unadjusted > alpha + tolerance


def test_family_helper_and_model_basis_binding():
    one = rs.superiority_test_family(OBJECTIVE_GOAL_SHORTFALL, 0.05)
    two = rs.superiority_test_family("max_drawdown", 0.05)
    assert one["family_size"] == 1 and one["per_test_alpha"] == 0.05
    assert two["family_size"] == 2 and two["per_test_alpha"] == 0.025
    assert "multiple_comparison" in rs._SIGNIFICANCE_BASIS_FIELDS
    basis = resampling_model_basis({
        "enabled": True,
        "significance": {"multiple_comparison": two, "decision": "house_matrix"},
    })
    assert basis["significance"]["multiple_comparison"] == two


def test_significance_sentence_names_family_alpha():
    text = solver_module._significance_sentence({
        "alpha": 0.025, "n_bootstrap": 999, "validation_n_paths": 2000,
        "improvement": 0.01, "improvement_lower_bound": 0.001, "p_value": 0.02,
        "multiple_comparison": rs.superiority_test_family("min_volatility", 0.05),
    })
    assert "alpha je Test=2.5%" in text
    assert "Holm-korrigiert fuer 2 Ueberlegenheitstests" in text
    assert "untere 97.5%-Konfidenzgrenze" in text
