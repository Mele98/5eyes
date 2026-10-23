"""Gemeinsamer Harness fuer das House-Shrinkage-Experiment (KEIN Produktcode).

Importiert die Engine standardmaessig aus dem Backend DIESES Repos. Fuer eine
exakte Reproduktion des Experiments (Branch origin/fix/importance-sampling-ess,
Engine saa_resampled_v5) zeigt ``SHRINK_EXPERIMENT_BACKEND`` auf das Backend
eines entsprechenden Worktrees; ein Absolutpfad ist nicht kodiert. Schreibt keine
Datenbank: DB_PATH zeigt auf eine Scratchpad-Datei, die Optimizer-Module
oeffnen ohnehin keine Session.
"""
from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

SCRATCH = os.path.dirname(os.path.abspath(__file__))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "shrink.db")
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

BACKEND = os.environ.get("SHRINK_EXPERIMENT_BACKEND") or str(
    Path(__file__).resolve().parents[3] / "5eyes-backend"
)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import numpy as np  # noqa: E402

import services.optimizer.solver as S  # noqa: E402
from services.optimizer import resampling as R  # noqa: E402
from services.optimizer.objective import goal_probability_per_path  # noqa: E402
from services.optimizer.scenario_engine import BUCKET_ORDER, build_scenario_paths  # noqa: E402

# ---------------------------------------------------------------------------
# Inputs: CMA und Hausmatrizen 1:1 aus den bestehenden Tests
# (tests/test_engine_reference_mandates.py) -- nichts erfunden.
# ---------------------------------------------------------------------------

CMA_BASE = {
    "id": "cma-shrink",
    "bonds_chf_ig_return_bps": 220, "bonds_chf_ig_vol_bps": 350,
    "bonds_fx_hedged_return_bps": 220, "bonds_fx_hedged_vol_bps": 430,
    "equity_ch_return_bps": 620, "equity_ch_vol_bps": 1450,
    "equity_intl_return_bps": 700, "equity_intl_vol_bps": 1600,
    "real_estate_ch_return_bps": 450, "real_estate_ch_vol_bps": 820,
    "alternatives_gold_return_bps": 300, "alternatives_gold_vol_bps": 1200,
    "liquidity_return_bps": 80, "liquidity_vol_bps": 20,
    "correlation_matrix_json": "",
    "equities_skewness_bps": -3000, "equities_excess_kurt_bps": 15000,
    "bonds_skewness_bps": 0, "bonds_excess_kurt_bps": 0,
    "real_estate_skewness_bps": 0, "real_estate_excess_kurt_bps": 0,
    "alternatives_skewness_bps": 0, "alternatives_excess_kurt_bps": 0,
    "liquidity_skewness_bps": 0, "liquidity_excess_kurt_bps": 0,
}
RETURN_FIELDS = [k for k in CMA_BASE if k.endswith("_return_bps")]


def cma(**overrides):
    base = dict(CMA_BASE)
    base.update(overrides)
    return SimpleNamespace(**base)


HM = {
    "wachstum": dict(
        profile_name="Wachstumsorientiert",
        equity_min_bps=4500, equity_max_bps=7000, equity_target_bps=6000,
        bonds_min_bps=2000, bonds_max_bps=4500, bonds_target_bps=3000,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=1000, alt_target_bps=300,
        liq_min_bps=200, liq_max_bps=2000, liq_target_bps=200,
        max_risky_fraction_bps=7500),
    "konservativ": dict(
        profile_name="Konservativ",
        equity_min_bps=500, equity_max_bps=2500, equity_target_bps=1500,
        bonds_min_bps=5000, bonds_max_bps=8000, bonds_target_bps=6500,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=500, alt_target_bps=200,
        liq_min_bps=500, liq_max_bps=2000, liq_target_bps=1000,
        max_risky_fraction_bps=3000),
    "ausgewogen": dict(
        profile_name="Ausgewogen",
        equity_min_bps=2500, equity_max_bps=5000, equity_target_bps=4000,
        bonds_min_bps=3500, bonds_max_bps=6000, bonds_target_bps=4500,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=1000, alt_target_bps=300,
        liq_min_bps=300, liq_max_bps=2000, liq_target_bps=500,
        max_risky_fraction_bps=5500),
}


def goal(gid, target_rappen, years, hardness="Hart"):
    today = date.today()
    return SimpleNamespace(
        id=gid, label=gid, goal_type="Vermoegensziel",
        target_amount_rappen=int(target_rappen), target_wealth_rappen=int(target_rappen),
        target_return_bps=None, horizon_years=None,
        start_date=today.isoformat(),
        target_date=(today + timedelta(days=365 * years)).isoformat(),
        is_ongoing=0, frequency="jaehrlich", hardness=hardness, rank=1,
        weight_bps=5000, value_mode="real",
    )


# Mandate: (house, score_x10, wealth CHF, cashflow CHF/J, horizon, goal CHF, goal_years, hardness)
MANDATES = {
    "A_ausg_spar":    dict(hm="ausgewogen", score=50, wealth=500_000, cf=20_000, H=12, goal=900_000, gy=12, hard="Hart"),
    "B_kons_entn":    dict(hm="konservativ", score=25, wealth=2_000_000, cf=-80_000, H=20, goal=900_000, gy=20, hard="Hart"),
    "C_wachs_entn":   dict(hm="wachstum", score=70, wealth=1_500_000, cf=-60_000, H=20, goal=1_500_000, gy=20, hard="Primaer"),
    "D_wachs_spar":   dict(hm="wachstum", score=70, wealth=300_000, cf=30_000, H=15, goal=1_100_000, gy=15, hard="Hart"),
    "E_ausg_entn":    dict(hm="ausgewogen", score=50, wealth=1_000_000, cf=-50_000, H=15, goal=500_000, gy=15, hard="Hart"),
}


def build_inputs(name, scale=1.0, cma_obj=None):
    m = MANDATES[name]
    return dict(
        cma=cma_obj or cma(),
        goals=[goal(f"{name}-ziel", round(m["goal"] * scale) * 100, m["gy"], m["hard"])],
        house_matrix_row=SimpleNamespace(**HM[m["hm"]]),
        score_x10=m["score"],
        advisory_wealth_rappen=m["wealth"] * 100,
        cashflow_series_rappen=[m["cf"] * 100] * m["H"],
        horizon_years=m["H"],
        n_paths=2000,
    )


# ---------------------------------------------------------------------------
# Bootstrap-Replikate mitschneiden (gleicher RNG-Strom wie die Produktion)
# ---------------------------------------------------------------------------
CAPTURE: dict = {}
_ORIG_PBI = R.paired_bootstrap_improvement


def _capturing_pbi(loss_pair, *, n_paths, n_bootstrap, alpha, seed):
    rng = np.random.default_rng(int(seed))
    reps = np.empty(int(n_bootstrap))
    for b in range(int(n_bootstrap)):
        idx = rng.integers(0, int(n_paths), size=int(n_paths))
        a, c = loss_pair(idx)
        reps[b] = R.scalar_loss(a) - R.scalar_loss(c)
    a0, c0 = loss_pair(None)
    CAPTURE.setdefault("calls", []).append(
        dict(full=R.scalar_loss(a0) - R.scalar_loss(c0), reps=reps))
    return _ORIG_PBI(loss_pair, n_paths=n_paths, n_bootstrap=n_bootstrap,
                     alpha=alpha, seed=seed)


S.paired_bootstrap_improvement = _capturing_pbi


def bps_to_w(bps):
    return np.array([int(bps[b]) / 10000.0 for b in BUCKET_ORDER])


def run(name, scale=1.0, seed=None, resampling=None, ctx_kwargs=None, cma_obj=None):
    """Produktionsnaher Lauf (Inhalts-Seed wenn seed=None). Liefert dict."""
    inp = build_inputs(name, scale, cma_obj)
    inp.update(ctx_kwargs or {})
    ctx = S.build_optimizer_context(seed=seed, **inp)
    CAPTURE.clear()
    res = S.run_solver(**inp, optimizer_context=ctx, resampling=resampling)
    rs = res.resampling or {}
    sig = rs.get("significance") or {}
    calls = CAPTURE.get("calls") or []
    goal_call = calls[0] if calls else None
    return dict(
        ctx=ctx, result=res, final=dict(res.weights_bps), payload=rs, sig=sig,
        candidate=sig.get("candidate_bps") or rs.get("resampled_weights_bps"),
        anchor=sig.get("house_anchor_projected_bps"),
        decision=sig.get("decision"), p=sig.get("p_value"),
        improvement=sig.get("improvement"),
        reps=None if goal_call is None else goal_call["reps"],
        elapsed_ms=rs.get("elapsed_ms"),
    )


# ---------------------------------------------------------------------------
# Out-of-sample-Bewertung
# ---------------------------------------------------------------------------

def _seed_of(*parts):
    h = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(h[:8], "big") & 0x7FFFFFFFFFFFFFFF


def oos_context(ctx, n_paths=20000, salt="oos", inputs=None):
    """Frischer nominaler Wuerfel (kein IS), unabhaengiger Seed."""
    inp = inputs if inputs is not None else ctx.scenario_inputs
    H = int(ctx.scenario_horizon_years or ctx.horizon_years)
    paths = build_scenario_paths(inp, horizon_years=H, n_paths=n_paths,
                                 seed=_seed_of(ctx.seed, salt), antithetic=True)
    return replace(ctx, return_paths=paths[:, : int(ctx.horizon_years), :],
                   scenario_weights=None, n_paths=n_paths)


def oos_eval(vctx, w_list):
    """Zielebene (Fehlbetrag + Chance-Strafe) und Zielwahrscheinlichkeit je
    Allokation auf demselben (gepaarten) OOS-Wuerfel."""
    out = []
    base = w_list[0]
    for w in w_list:
        pair = S._context_loss_components_on_validation(vctx, base, w, validation_seed=None)
        (_g0, _r0), (g, r) = pair(None)
        wealth = S._simulate_context_wealth(vctx, w)
        probs = [float(np.mean(goal_probability_per_path(
            wealth, liab, vctx.advisory_wealth_rappen))) for liab in vctx.liabilities]
        out.append(dict(goal_level=float(g), tiebreak=float(r), probs=probs))
    return out


def analytic_ret_vol(ctx, w):
    var = S._tiebreak_portfolio_variance(ctx, w)
    vol = float(np.sqrt(var)) if var is not None else float("nan")
    mu = getattr(ctx.scenario_inputs, "mean_returns", None)
    return vol


def eq(bps):
    return int(bps["equities"]) / 100.0 if bps else float("nan")


# ---------------------------------------------------------------------------
# Variante (c): Hausmatrix als Prior IM Optimierer -- Tiebreak
# kappa * w'Sigma w ersetzt durch kappa_h * (w-w_h)'Sigma(w-w_h)
# (Tracking-Error-Varianz zur zulaessig projizierten Hausquote).
# Nur per Monkeypatch im Experiment.
# ---------------------------------------------------------------------------
from services.optimizer.objective import portfolio_variance_one_year  # noqa: E402

_ORIG_TB = S._tiebreak_portfolio_variance
PRIOR = {"w_h": None, "kappa": 1.0}


def _te_tiebreak(context, w):
    cov = context.scenario_cov_bps2
    if cov is None:
        return None
    if PRIOR["w_h"] is None:
        return _ORIG_TB(context, w)
    d = np.asarray(w, dtype=np.float64) - PRIOR["w_h"]
    return PRIOR["kappa"] * portfolio_variance_one_year(d, cov)


def run_prior(name, scale=1.0, kappa=100.0, seed=None):
    """(c): Optimierer mit Haus-Prior; Signifikanztest aus (Prior ersetzt
    den Schalter), Bags/Projektion/Rundung unveraendert."""
    inp = build_inputs(name, scale)
    ctx = S.build_optimizer_context(seed=seed, **inp)
    anchor_bps, _ = S._project_house_anchor(
        ctx, S._resolve_house_anchor_bps(None, inp["house_matrix_row"]))
    PRIOR["w_h"], PRIOR["kappa"] = bps_to_w(anchor_bps), float(kappa)
    S._tiebreak_portfolio_variance = _te_tiebreak
    try:
        cfg = R.ResamplingConfig(significance_test=False)
        res = S.run_solver(**inp, optimizer_context=ctx, resampling=cfg)
    finally:
        S._tiebreak_portfolio_variance = _ORIG_TB
        PRIOR["w_h"] = None
    rs = res.resampling or {}
    return dict(ctx=ctx, final=dict(res.weights_bps), anchor=anchor_bps,
                elapsed_ms=rs.get("elapsed_ms"),
                dispersion=rs.get("dispersion_bps"))
