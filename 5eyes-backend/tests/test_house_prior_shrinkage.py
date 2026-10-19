"""HOUSE-PRIOR-001 (CIO-Entscheid 2026-10-18, Engine ``saa_resampled_v6``).

Befund (v5, HOUSE-FIRST-SIGNIFICANCE-001): der Signifikanztest gegen die
Hausmatrix kannte nur zwei Ergebnisse -- Hausquote ODER Optimierer-Kandidat.
Auf den Referenzmandaten (CMA und Hausmatrizen aus
``test_engine_reference_mandates``) sprang die publizierte Allokation bei
+1-2 % Zielbetrag um 14-20 pp Turnover, und ueber Seeds streute die
Aktienquote bis 7.4 pp. Entscheid: die Hausmatrix wird Prior IM Optimierer
(``kappa_H * (w - w_H)' Sigma (w - w_H)`` statt ``w' Sigma w``, kappa_H =
300); der Bootstrap bleibt nur Offenlegung + Sicherheitsnetz.

Design/Experiment: docs/planning/2026-10-18-house-prior-v6.md.

Die Verhaltens-Tests (Stetigkeit, Seed-Stabilitaet, Hausquote bei sicheren
Zielen, Zulaessigkeit, Determinismus) benutzen nur ``run_solver`` und die
publizierten Gewichte -- sie laufen unveraendert gegen die Engine v5 und
sind dort (bis auf die Hausquote bei sicheren Zielen, die schon v5
garantierte) ROT. Die Audit-Tests importieren ``house_prior`` lokal.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import services.optimizer.solver as solver_module  # noqa: E402
from services.optimizer.objective import portfolio_variance_one_year  # noqa: E402
from services.optimizer.objective_contract import (  # noqa: E402
    ObjectiveContractV1,
    resolve_objective_contract,
)
from services.optimizer.resampling import ResamplingConfig  # noqa: E402
from services.optimizer.scenario_engine import BUCKET_ORDER  # noqa: E402
from test_engine_reference_mandates import (  # noqa: E402
    _base_cma,
    _house_matrix_ausgewogen,
    _house_matrix_konservativ,
    _house_matrix_wachstum,
)

# ---------------------------------------------------------------------------
# Referenzmandate (Experiment HOUSE-PRIOR-SHRINKAGE-001): CMA und Hausmatrizen
# 1:1 aus test_engine_reference_mandates; je ein reales Vermoegensziel.
# Zieldaten kalenderjahr-relativ mit festem Monat/Tag -- der Inhalts-Seed
# hasht sie relativ zum Bewertungsjahr, der Test ist also ueber Kalendertage
# und -jahre stabil (SAA-SEED-FLOAT-ROBUST-001).
# ---------------------------------------------------------------------------

MANDATES = {
    "A_ausgewogen_sparen": dict(
        house=_house_matrix_ausgewogen, score=50, wealth=500_000, cashflow=20_000,
        horizon=12, goal=900_000, goal_years=12, hardness="Hart"),
    "B_konservativ_entnahme": dict(
        house=_house_matrix_konservativ, score=25, wealth=2_000_000, cashflow=-80_000,
        horizon=20, goal=900_000, goal_years=20, hardness="Hart"),
    "D_wachstum_sparen": dict(
        house=_house_matrix_wachstum, score=70, wealth=300_000, cashflow=30_000,
        horizon=15, goal=1_100_000, goal_years=15, hardness="Hart"),
    "E_ausgewogen_entnahme": dict(
        house=_house_matrix_ausgewogen, score=50, wealth=1_000_000, cashflow=-50_000,
        horizon=15, goal=500_000, goal_years=15, hardness="Hart"),
}


def _goal(name: str, amount_chf: int, years: int, hardness: str):
    year = date.today().year
    return SimpleNamespace(
        id=f"{name}-ziel", label=f"Ziel {name}", goal_type="Vermoegensziel",
        target_amount_rappen=int(amount_chf) * 100,
        target_wealth_rappen=int(amount_chf) * 100,
        target_return_bps=None, horizon_years=None,
        start_date=f"{year}-01-01", target_date=f"{year + years}-06-30",
        is_ongoing=0, frequency="jaehrlich", hardness=hardness, rank=1,
        weight_bps=5000, value_mode="real",
    )


def _inputs(name: str, scale: float = 1.0, *, goals=None) -> dict:
    m = MANDATES[name]
    if goals is None:
        goals = [_goal(name, round(m["goal"] * scale), m["goal_years"], m["hardness"])]
    return dict(
        cma=_base_cma(),
        goals=goals,
        house_matrix_row=m["house"](),
        score_x10=m["score"],
        advisory_wealth_rappen=m["wealth"] * 100,
        cashflow_series_rappen=[m["cashflow"] * 100] * m["horizon"],
        horizon_years=m["horizon"],
        n_paths=2000,
    )


_RUNS: dict = {}


def _run(name: str, scale: float = 1.0, *, seed: int | None = None):
    """Produktionslauf (40 Bags x 500 Pfade; ``seed=None`` = Inhalts-Seed wie
    in der Produktion); je Modul gecacht."""
    key = (name, round(scale, 4), seed)
    if key not in _RUNS:
        inputs = _inputs(name, scale)
        context = solver_module.build_optimizer_context(seed=seed, **inputs)
        _RUNS[key] = solver_module.run_solver(**inputs, optimizer_context=context)
    return _RUNS[key]


def _w(weights_bps) -> np.ndarray:
    return np.array([int(weights_bps[b]) for b in BUCKET_ORDER], dtype=float)


def _turnover_pp(a, b) -> float:
    return float(np.abs(_w(a) - _w(b)).sum()) / 2.0 / 100.0


def _projected_anchor(name: str, scale: float = 1.0) -> dict[str, int]:
    inputs = _inputs(name, scale)
    context = solver_module.build_optimizer_context(**inputs)
    anchor, reason = solver_module._project_house_anchor(
        context,
        solver_module._resolve_house_anchor_bps(None, inputs["house_matrix_row"]),
    )
    assert anchor is not None, reason
    return anchor


# ---------------------------------------------------------------------------
# 1. Stetigkeit (Regression des Befunds)
# ---------------------------------------------------------------------------

# Je Mandat drei 1-%-Nachbarn genau dort, wo v5 (Inhalts-Seed, diese
# Zieldaten) zwischen Optimierer und Hausquote kippte:
# D 0.90 -> 0.92: 16.9 pp, E 0.96 -> 0.98: 19.9 pp, A 1.02 -> 1.04: 15.6 pp.
CONTINUITY_POINTS = {
    "D_wachstum_sparen": (0.90, 0.91, 0.92),
    "E_ausgewogen_entnahme": (0.96, 0.97, 0.98),
    "A_ausgewogen_sparen": (1.02, 1.03, 1.04),
}
MAX_TURNOVER_PER_PERCENT_PP = 5.0


@pytest.mark.parametrize("name", sorted(CONTINUITY_POINTS))
def test_one_percent_goal_change_moves_the_allocation_continuously(name):
    """+1 % Zielbetrag darf die SAA nicht springen lassen (v5: bis 20 pp)."""
    scales = CONTINUITY_POINTS[name]
    results = [_run(name, scale) for scale in scales]
    jumps = [
        _turnover_pp(a.weights_bps, b.weights_bps)
        for a, b in zip(results, results[1:])
    ]
    assert max(jumps) <= MAX_TURNOVER_PER_PERCENT_PP, (
        name, jumps, [r.weights_bps for r in results],
    )


def test_one_percent_goal_change_is_continuous_with_common_random_numbers():
    """Auch mit festem Seed (wie die Goal-Sensitivity): kein Sprung (v5:
    17.3 pp mit festem Seed -- die Unstetigkeit war strukturell)."""
    seed = 20261018
    results = [_run("D_wachstum_sparen", s, seed=seed) for s in (0.90, 0.91, 0.92)]
    jumps = [
        _turnover_pp(a.weights_bps, b.weights_bps)
        for a, b in zip(results, results[1:])
    ]
    assert max(jumps) <= MAX_TURNOVER_PER_PERCENT_PP, jumps


# ---------------------------------------------------------------------------
# 2. Seed-Stabilitaet
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,scale", [
    ("D_wachstum_sparen", 0.92), ("A_ausgewogen_sparen", 1.03),
])
def test_equity_quota_is_seed_stable_where_v5_flipped(name, scale):
    """6 Seeds an Punkten, an denen v5 je nach Wuerfel zwischen Optimierer
    und Hausquote wechselte (gemessen v5: Sigma Aktien 6.2 pp bei D 0.92,
    Entscheide H/H/H/O/H/O; 6.6 pp bei A 1.03, O/O/H/O/H/H). v6: <= 1 pp."""
    equities = [
        _run(name, scale, seed=9_000_000 + salt).weights_bps["equities"] / 100.0
        for salt in range(6)
    ]
    assert float(np.std(equities, ddof=1)) <= 1.0, equities


# ---------------------------------------------------------------------------
# 3. Hausquote, solange die Ziele mit ihr sicher erreicht sind
# ---------------------------------------------------------------------------


def test_certain_goal_publishes_exactly_the_house_quota():
    """Ziel mit der Hausquote sicher erreicht -> Gradient der Zielebene 0 ->
    Optimum ist exakt die Hausquote (wie v5, jetzt stetig begruendet)."""
    result = _run("A_ausgewogen_sparen", 0.40)
    goal_rows = [r for r in result.goal_achievability if r.get("goal_id")]
    assert goal_rows and all(float(r["probability"]) == 1.0 for r in goal_rows)
    assert result.weights_bps == _projected_anchor("A_ausgewogen_sparen", 0.40)


def test_no_goals_publishes_exactly_the_house_quota():
    inputs = _inputs("E_ausgewogen_entnahme", goals=[])
    result = solver_module.run_solver(**inputs)
    context = solver_module.build_optimizer_context(**inputs)
    anchor, _ = solver_module._project_house_anchor(
        context, solver_module._resolve_house_anchor_bps(None, inputs["house_matrix_row"]),
    )
    assert result.weights_bps == anchor


def test_certain_goal_has_zero_tracking_error_and_zero_bag_dispersion():
    from services.optimizer.house_prior import DECISION_HOUSE_PRIOR

    result = _run("A_ausgewogen_sparen", 0.40)
    block = result.resampling["house_prior"]
    assert block["decision"] == DECISION_HOUSE_PRIOR
    # Engine v7: exakt identisch ODER innerhalb der Solver-Toleranz (<= 1 bp
    # je Bucket, Ridge-Metrik; Herleitung bei REASON_WITHIN_TOLERANCE) --
    # publiziert wird in beiden Faellen exakt der Anker.
    assert block["reason"] in {
        "identical_to_house_anchor", "within_solver_tolerance_of_house_anchor",
    }
    assert block["tracking_error_vs_house_bps"] == 0.0
    assert block["final_bps"] == block["house_anchor_projected_bps"] == result.weights_bps
    assert max(result.resampling["dispersion_bps"].values()) <= 1.0


# ---------------------------------------------------------------------------
# 4. Zielverbesserung + Offenlegung
# ---------------------------------------------------------------------------


def test_ambitious_goal_deviates_and_improves_goal_attainment():
    """D: Abweichung nur, weil sie die Zielerreichung verbessert -- auf dem
    unabhaengigen Validierungswuerfel ist das Ergebnis auf Zielebene und
    Zielwahrscheinlichkeit mindestens so gut wie die Hausquote."""
    result = _run("D_wachstum_sparen", 1.0)
    block = result.resampling["house_prior"]
    assert block["decision"] == "house_prior"
    assert block["tracking_error_vs_house_bps"] > 0.0
    disclosure = block["disclosure"]
    assert disclosure["improvement"] >= 0.0
    assert disclosure["final_goal_level"] <= disclosure["house_goal_level"]
    goal_rows = [r for r in block["goal_probabilities"] if r["goal_id"]]
    assert goal_rows
    for row in goal_rows:
        assert row["probability_final"] >= row["probability_house"], row


def test_disclosure_fields_are_complete_and_in_the_model_basis():
    from services.optimizer.house_prior import (
        HOUSE_PRIOR_DISCLOSURE_TEST_VERSION,
        HOUSE_PRIOR_KAPPA,
        HOUSE_PRIOR_VERSION,
    )
    from services.optimizer.resampling import resampling_model_basis

    result = _run("D_wachstum_sparen", 1.0)
    payload = result.resampling
    assert payload["engine_version"] == "saa_resampled_v9"
    assert "significance" not in payload
    block = payload["house_prior"]
    assert HOUSE_PRIOR_KAPPA == 300.0
    assert block["kappa"] == 300.0
    assert block["version"] == HOUSE_PRIOR_VERSION
    for key in (
        "house_anchor_bps", "house_anchor_projected_bps", "candidate_bps",
        "final_bps", "tracking_error_vs_house_bps",
        "candidate_tracking_error_vs_house_bps", "disclosure",
        "goal_probabilities", "validation_seed", "validation_cube_hash",
        "validation_n_paths", "decision", "reason",
    ):
        assert key in block, key
    disclosure = block["disclosure"]
    assert disclosure["test"] == HOUSE_PRIOR_DISCLOSURE_TEST_VERSION
    for key in (
        "improvement", "improvement_lower_bound", "improvement_upper_bound",
        "p_value_better", "p_value_worse", "significantly_worse",
        "house_goal_level", "final_goal_level", "n_bootstrap", "alpha",
        # Engine v7: Stichprobeneinheit und p-Wert-Vertrag.
        "sampling_unit", "n_independent_units", "sampling_unit_hash",
        "bootstrap_method", "null_hypothesis", "p_value_calibration",
        "bootstrap_tail_fraction_not_better", "bootstrap_tail_fraction_not_worse",
    ):
        assert key in disclosure, key
    assert disclosure["sampling_unit"] == "antithetic_pair"
    assert disclosure["improvement_lower_bound"] <= disclosure["improvement"]
    assert disclosure["improvement"] <= disclosure["improvement_upper_bound"]
    # TE = 1e4 * sqrt((w - w_H)' (Sigma + eps I) (w - w_H)) -- Engine v7
    # Ridge-Metrik (HOUSE-PRIOR-PSD-NULLSPACE-001); der reine CMA-TE liegt
    # nur marginal darunter.
    from services.optimizer.house_prior import prior_metric_bps2

    delta = (_w(block["final_bps"]) - _w(block["house_anchor_projected_bps"])) / 1e4
    expected_te = 1e4 * np.sqrt(
        portfolio_variance_one_year(delta, prior_metric_bps2(result.context.scenario_cov_bps2))
    )
    pure_te = 1e4 * np.sqrt(
        portfolio_variance_one_year(delta, result.context.scenario_cov_bps2)
    )
    assert block["tracking_error_vs_house_bps"] == pytest.approx(expected_te, abs=1e-3)
    assert pure_te <= block["tracking_error_vs_house_bps"] <= pure_te * 1.05
    assert block["prior_metric"]["min_eigenvalue_bps2"] >= 2500.0 - 1e-6
    # Reasoning fuer Kunde/Pruefer.
    assert any(
        "Hausmatrix als Anker des Optimierers" in line and "Tracking Error" in line
        and "Zielwahrscheinlichkeit" in line
        for line in result.reasoning
    ), result.reasoning
    # Modellbasis (allocation_context_hash): kappa und Version gehen ein.
    basis = resampling_model_basis(payload)
    assert basis["house_prior"]["kappa"] == 300.0
    assert basis["house_prior"]["version"] == HOUSE_PRIOR_VERSION
    assert basis["house_prior"]["decision"] == block["decision"]
    assert "significance" not in basis


# ---------------------------------------------------------------------------
# 5. Zulaessigkeit (inkl. bps-Rundung und projiziertem Anker)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,scale", [
    ("D_wachstum_sparen", 0.90), ("D_wachstum_sparen", 1.0),
    ("E_ausgewogen_entnahme", 0.97), ("A_ausgewogen_sparen", 1.03),
])
def test_published_allocation_is_feasible_after_bps_rounding(name, scale):
    result = _run(name, scale)
    assert sum(result.weights_bps.values()) == 10000
    evaluation = solver_module.evaluate_weights(result.context, dict(result.weights_bps))
    assert evaluation.feasible, evaluation.constraint_violations
    assert result.status in {"converged", "converged_robustified"}


def test_anchor_outside_the_mandate_bands_is_projected_and_result_feasible():
    """Hausquote ausserhalb der Bandbreiten: der Prior zieht zur PROJIZIERTEN
    Quote, das Ergebnis bleibt zulaessig (Risikobudget, Bandbreiten)."""
    raw = {"equities": 9000, "bonds": 500, "real_estate": 300,
           "alternatives": 100, "liquidity": 100}
    inputs = _inputs("D_wachstum_sparen", 1.0)
    result = solver_module.run_solver(**inputs, house_anchor_bps=raw)
    block = result.resampling["house_prior"]
    assert block["house_anchor_bps"] == raw
    assert block["house_anchor_projected_bps"] != raw
    projected = block["house_anchor_projected_bps"]
    assert solver_module.evaluate_weights(result.context, projected).feasible
    assert solver_module.evaluate_weights(result.context, dict(result.weights_bps)).feasible


# ---------------------------------------------------------------------------
# 6. Determinismus
# ---------------------------------------------------------------------------


def test_identical_inputs_are_bitwise_reproducible():
    inputs = _inputs("E_ausgewogen_entnahme", 0.97)
    first = solver_module.run_solver(**inputs)
    second = solver_module.run_solver(**inputs)
    strip = lambda payload: {  # noqa: E731
        k: v for k, v in payload.items() if k not in {"elapsed_ms", "bags"}
    }
    assert first.seed == second.seed
    assert first.weights_bps == second.weights_bps
    assert strip(first.resampling) == strip(second.resampling)
    assert first.objective_value == second.objective_value


# ---------------------------------------------------------------------------
# 7. Eine Zielfunktion (Solver, evaluate_weights, Validierung)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def small_context():
    inputs = _inputs("D_wachstum_sparen", 1.0)
    inputs["n_paths"] = 300
    return solver_module.build_optimizer_context(seed=20261018, **inputs)


def test_prior_replaces_the_variance_tiebreak_only_with_an_anchor(small_context):
    from services.optimizer.house_prior import HOUSE_PRIOR_KAPPA

    cov = small_context.scenario_cov_bps2
    anchor = {"equities": 6000, "bonds": 3000, "real_estate": 500,
              "alternatives": 300, "liquidity": 200}
    w = np.array([0.55, 0.30, 0.08, 0.05, 0.02])
    w_h = _w(anchor) / 1e4
    # Ohne Anker: v5-Tiebreak w' Sigma w.
    assert small_context.house_prior_weights is None
    assert solver_module._tiebreak_portfolio_variance(small_context, w) == pytest.approx(
        portfolio_variance_one_year(w, cov), rel=1e-15,
    )
    prior_ctx = solver_module._with_house_prior(small_context, anchor)
    assert prior_ctx.house_prior_kappa == HOUSE_PRIOR_KAPPA
    assert not prior_ctx.house_prior_weights.flags.writeable
    # Engine v7 (HOUSE-PRIOR-PSD-NULLSPACE-001): Ridge-Metrik Sigma + eps I.
    from services.optimizer.house_prior import prior_metric_bps2

    assert solver_module._tiebreak_portfolio_variance(prior_ctx, w) == pytest.approx(
        HOUSE_PRIOR_KAPPA * portfolio_variance_one_year(w - w_h, prior_metric_bps2(cov)),
        rel=1e-12,
    )
    assert solver_module._tiebreak_portfolio_variance(prior_ctx, w_h) == 0.0


def test_solver_objective_equals_evaluate_weights_and_validation_split(small_context):
    """Eine Zielfunktion: SLSQP-Closure, ``evaluate_weights`` und die
    Zerlegung auf dem Validierungswuerfel (Offenlegung) sehen denselben
    Prior-Term."""
    anchor = {"equities": 6000, "bonds": 3000, "real_estate": 500,
              "alternatives": 300, "liquidity": 200}
    prior_ctx = solver_module._with_house_prior(small_context, anchor)
    bps = {"equities": 6600, "bonds": 2400, "real_estate": 500,
           "alternatives": 300, "liquidity": 200}
    w = _w(bps) / 1e4
    direct = solver_module._objective_from_array(prior_ctx, w)
    assert solver_module.evaluate_weights(prior_ctx, bps).objective_value == pytest.approx(
        direct, rel=1e-12,
    )
    # Validierungswuerfel (ohne IS-Gewichte, wie in der Offenlegung): die
    # Risikoebene ist der Prior-Term, Zielebene + Risikoebene = Skalar.
    validation_ctx, validation_seed, _hash = solver_module._build_validation_context(prior_ctx)
    assert validation_ctx.house_prior_weights is prior_ctx.house_prior_weights
    pair = solver_module._context_loss_components_on_validation(
        validation_ctx, _w(anchor) / 1e4, w, validation_seed=validation_seed,
    )
    (_house_goal, house_risk), (goal, risk) = pair(None)
    assert house_risk == 0.0
    assert risk == pytest.approx(
        solver_module._tiebreak_portfolio_variance(prior_ctx, w), rel=1e-12,
    )
    assert goal + risk == pytest.approx(
        solver_module._objective_from_array(validation_ctx, w), rel=1e-9,
    )


def test_result_binds_the_prior_decision_objective():
    """HOUSE-PRIOR-DECISION-OBJECTIVE-IDENTITY-001 (Engine v7, ersetzt den
    v6-Vertrag "result.context ist das Aufrufer-Objekt"): der Prior steuert
    die Bags UND der Abschluss laeuft auf dem Prior-Context. ``result.context``
    ist der aus dem uebergebenen Context abgeleitete Prior-Context (alle
    uebrigen Felder dieselben Objekte), ``result.objective_value`` ist die
    Entscheidungs-Zielfunktion G + P_pref + kappa_H * TE_M^2 und
    ``evaluate_weights(result.context, result.weights_bps)`` reproduziert ihn
    exakt. Der Prior-Term steht zusaetzlich im Audit."""
    import dataclasses

    inputs = _inputs("D_wachstum_sparen", 1.0)
    context = solver_module.build_optimizer_context(**inputs)
    result = solver_module.run_solver(**inputs, optimizer_context=context)
    assert context.house_prior_weights is None
    assert result.context is not context
    assert result.context.house_prior_weights is not None
    for field in dataclasses.fields(context):
        if field.name in {"house_prior_weights", "house_prior_kappa"}:
            continue
        assert getattr(result.context, field.name) is getattr(context, field.name), field.name
    assert solver_module.evaluate_weights(
        result.context, dict(result.weights_bps),
    ).objective_value == pytest.approx(result.objective_value, rel=1e-12, abs=1e-12)
    block = result.resampling["house_prior"]
    prior_ctx = solver_module._with_house_prior(context, block["house_anchor_projected_bps"])
    np.testing.assert_array_equal(prior_ctx.house_prior_weights, result.context.house_prior_weights)
    w = _w(result.weights_bps) / 1e4
    assert block["final_prior_penalty"] == pytest.approx(
        solver_module._tiebreak_portfolio_variance(prior_ctx, w), rel=1e-12,
    )
    assert block["final_prior_penalty"] > 0.0


# ---------------------------------------------------------------------------
# 8. Sicherheitsnetz, kein Anker, Varianten unveraendert
# ---------------------------------------------------------------------------


def test_disclosure_bootstrap_detects_worse_and_better_and_equal():
    from services.optimizer.house_prior import paired_bootstrap_disclosure

    rng = np.random.default_rng(5)
    n = 2000
    house = np.where(rng.random(n) < 0.10, 1.0, 0.0)
    worse = np.where(rng.random(n) < 0.30, 1.0, 0.0)

    def pair_of(a, b):
        return lambda idx: (
            float(np.mean(a if idx is None else a[idx])),
            float(np.mean(b if idx is None else b[idx])),
        )

    kwargs = dict(n_paths=n, n_bootstrap=400, alpha=0.05, seed=11)
    bad = paired_bootstrap_disclosure(pair_of(house, worse), **kwargs)
    assert bad["significantly_worse"] is True and bad["improvement"] < 0
    assert bad["p_value_worse"] <= 0.05
    good = paired_bootstrap_disclosure(pair_of(worse, house), **kwargs)
    assert good["significantly_worse"] is False and good["p_value_better"] <= 0.05
    same = paired_bootstrap_disclosure(pair_of(house, house), **kwargs)
    assert same["significantly_worse"] is False and same["improvement"] == 0.0


def test_guard_publishes_the_house_quota_when_the_result_is_significantly_worse(monkeypatch):
    real = solver_module.paired_bootstrap_disclosure

    def _worse(loss_pair, **kwargs):
        stats = real(loss_pair, **kwargs)
        return {**stats, "improvement": -0.01, "p_value_worse": 0.0025,
                "significantly_worse": True}

    monkeypatch.setattr(solver_module, "paired_bootstrap_disclosure", _worse)
    inputs = _inputs("D_wachstum_sparen", 1.0)
    result = solver_module.run_solver(**inputs)
    block = result.resampling["house_prior"]
    assert block["candidate_bps"] != block["house_anchor_projected_bps"]
    assert block["decision"] == "house_prior_guard"
    assert block["reason"] == "significantly_worse_than_house"
    assert result.resampling["decision"] == "house_prior_guard"
    assert result.weights_bps == block["house_anchor_projected_bps"] == block["final_bps"]
    assert block["tracking_error_vs_house_bps"] == 0.0
    assert any("Sicherheitsnetz" in line for line in result.reasoning)


def test_without_anchor_the_v5_rule_remains(monkeypatch):
    monkeypatch.setattr(
        solver_module, "_project_house_anchor",
        lambda context, anchor: (None, "house_anchor_not_projectable"),
    )
    inputs = _inputs("E_ausgewogen_entnahme", 0.97)
    config = ResamplingConfig(n_bags=6, bag_n_paths=300)
    result = solver_module.run_solver(**inputs, resampling=config)
    assert "house_prior" not in result.resampling
    assert result.context.house_prior_weights is None
    significance = result.resampling["significance"]
    assert significance["decision"] == "optimizer_untested"
    assert significance["reason"] == "house_anchor_not_projectable"


@pytest.mark.parametrize("mode", ["min_volatility", "max_drawdown", "cvar_return", "max_return"])
def test_risk_measure_variants_keep_the_v5_significance_rule(mode):
    inputs = _inputs("E_ausgewogen_entnahme", 0.97)
    contract = ObjectiveContractV1(
        objective_mode=mode,
        goal_weighting_mode=resolve_objective_contract().goal_weighting_mode,
    )
    config = ResamplingConfig(n_bags=4, bag_n_paths=300)
    result = solver_module.run_solver(
        **inputs, objective_contract=contract, resampling=config,
    )
    assert result.context.house_prior_weights is None
    assert "house_prior" not in result.resampling
    significance = result.resampling["significance"]
    from services.optimizer.resampling import SIGNIFICANCE_TEST_VERSION

    # Mathematisch die v5-Regel; seit Engine v7 mit Einheiten-Bootstrap und
    # nullzentriertem p-Wert (eigene Testversion).
    assert significance["test"] == SIGNIFICANCE_TEST_VERSION
    assert significance["sampling_unit"] == "antithetic_pair"
    assert significance["decision"] in {"optimizer", "house_matrix"}


# ---------------------------------------------------------------------------
# 9. kappa: Monotonie und Grenzfall (Property)
# ---------------------------------------------------------------------------


def test_kappa_limits_move_from_free_optimizer_to_the_house_quota(monkeypatch):
    """Grenzfaelle in kappa: sehr grosses kappa -> so nah an die Hausquote,
    wie die Zielschutz-Schranke (GOAL-HIERARCHY-001) erlaubt, sehr kleines
    kappa -> deutlich weiter weg.

    Bewusst KEINE strikte Monotonie fuer benachbarte kappa: fuer exakte
    Bag-Minimierer gilt TE(kappa) nicht steigend, der Multi-Start-SLSQP
    findet auf der nicht-konvexen Zielebene aber nicht immer das globale
    Bag-Minimum (gemessen D 1.0: TE 47 bps bei kappa 30, 103 bps bei 300;
    die kappa-300-Loesung hatte in 4 von 4 Bags auch unter kappa 30 den
    kleineren Zielwert). Offener Punkt im Planungsdokument."""
    config = ResamplingConfig(n_bags=8, bag_n_paths=500)
    inputs = _inputs("D_wachstum_sparen", 1.0)
    tes = {}
    audits = {}
    for kappa in (3.0, 1e6):
        monkeypatch.setattr(solver_module, "HOUSE_PRIOR_KAPPA", kappa)
        result = solver_module.run_solver(**inputs, resampling=config)
        block = result.resampling["house_prior"]
        assert block["kappa"] == kappa
        tes[kappa] = block["candidate_tracking_error_vs_house_bps"]
        audits[kappa] = [b["goal_protection"] for b in result.resampling["bags"]]
    # GOAL-HIERARCHY-001 (Engine v7): das harte Ziel von D ist Stufe 1 -- auch
    # kappa -> unendlich zieht nur bis an die Zielschutz-Schranke G1* + eps,
    # nicht mehr bis auf die Hausquote (v6: TE <= 5 bps). Der Prior wirkt
    # weiterhin: grosses kappa liegt naeher an der Hausquote.
    # GOAL-REACHABILITY-CERTIFICATE-001 (Engine v9, CIO-Abnahme #655): bei D
    # bestimmt die Stufe-1-Zielschutz-Schranke das Ergebnis, nicht kappa --
    # in JEDEM Bag verletzt das Optimum der vollen Zielfunktion die Schranke
    # und die Auswahl laeuft mit ihr als Nebenbedingung (``constraint_pass``,
    # Ergebnis nahe dem Stufe-1-Minimierer, kappa-unabhaengig). Der Abstand
    # zur Hausquote haengt dann am Wuerfel, nicht am Prior: TE(1e6) - TE(3)
    # = -3.4 (v8-Seed), +0.8 (Zwischenstand v9_reach), +16.2 bps (v9; 85.3
    # vs 101.5), feste Seeds 11/12/13: +3.3/+1.5/-1.0. Eine TE-Toleranz
    # waere daher Seed-Anpassung; geprueft wird stattdessen die Ursache
    # (Schranke in allen Bags aktiv) und unten die Schranke selbst. Die
    # eigentliche kappa-Monotonie sichert
    # ``test_kappa_limits_without_binding_goal_protection_are_monotone``.
    for kappa in (3.0, 1e6):
        assert all(a is not None and a["constraint_pass"] for a in audits[kappa]), kappa
    for audit in audits[1e6]:
        assert audit is not None
        assert audit["final_level"] <= audit["bound"] * (1.0 + 1e-6)


def test_kappa_limits_without_binding_goal_protection_are_monotone(monkeypatch):
    """CIO-Abnahme #655: kappa-Monotonie auf einem Mandat OHNE Stufe 1.

    Referenzmandat A mit opportunistischem statt hartem Ziel: kein
    geschuetztes Ziel, keine Zielschutz-Schranke (``goal_protection`` None
    in jedem Bag). Dort muss der Prior ungehindert wirken: kappa -> unendlich
    landet auf der (projizierten) Hausquote, kleines kappa deutlich weiter
    weg. Gemessen (v9): TE 30.9 bps (kappa 3) -> 0.0 bps (kappa 1e6).
    """
    config = ResamplingConfig(n_bags=8, bag_n_paths=500)
    m = MANDATES["A_ausgewogen_sparen"]
    inputs = _inputs(
        "A_ausgewogen_sparen", 1.0,
        goals=[_goal("A_ausgewogen_sparen", m["goal"], m["goal_years"], "Opportunistisch")],
    )
    tes = {}
    for kappa in (3.0, 1e6):
        monkeypatch.setattr(solver_module, "HOUSE_PRIOR_KAPPA", kappa)
        result = solver_module.run_solver(**inputs, resampling=config)
        block = result.resampling["house_prior"]
        assert block["kappa"] == kappa
        assert all(b["goal_protection"] is None for b in result.resampling["bags"])
        tes[kappa] = block["candidate_tracking_error_vs_house_bps"]
    assert tes[1e6] < tes[3.0], tes
    assert tes[1e6] <= 5.0, tes
    assert tes[3.0] >= 10.0, tes
