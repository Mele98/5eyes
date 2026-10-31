"""Analytische Gradienten fuer den SLSQP-Solver -- Experiment (KEIN Produktcode).

Konzept: docs/planning/2026-10-22-analytic-gradients.md (ANALYTIC-GRADIENTS-001).

Dieses Skript veraendert keinen Produktcode. Es

1. implementiert die Zielfunktion des Default-Modus ``goal_shortfall`` (Engine
   ``saa_resampled_v10``) samt Gradient per Vorwaertsmodus (Tangenten-
   Rekursion durch die Vermoegensrekursion inkl. Cashflows, Liabilities,
   Mortalitaetsmaske, W2.5-Schalter und direkten Prioritaets-Scope-Replays),
2. prueft Wert-Paritaet gegen die Produktion und den Gradienten gegen
   zentrale Finite Differenzen der PRODUKTIONS-Funktion,
3. misst den Effekt im echten ``run_solver`` (40 Bags x 500 Pfade), indem
   ``solver._solve_single_start`` per Monkeypatch einen ``jac`` erhaelt
   (Modi ``fd`` = Produktion, ``analytic`` = exakter f.ue.-Gradient,
   ``smooth`` = Stufe 2 auf geglaetteter Chance-Strafe, Auswahl exakt,
   ``constrained`` = analytic + Stufe-1-Schranke als SLSQP-Nebenbedingung),
4. bewertet das Ergebnis OOS auf einem unabhaengigen 20'000-Pfade-Wuerfel.

Sicherheit: ``DB_PATH`` muss gesetzt sein und darf nicht die Live-DB sein
(der Fundament-Fall braucht eine Session; sie geht auf eine frische
SQLite-Datei unter ``DB_PATH``). Threads werden auf 1 gesetzt.

Aufruf (aus dem Repo-Root)::

    DB_PATH=<scratch>/a07_grad.db python tools/analytic_gradients/analytic_gradient_experiment.py check
    DB_PATH=... python tools/analytic_gradients/analytic_gradient_experiment.py solve --cases M1,M2,M3,M3R,M4,M5,FUND
    DB_PATH=... python tools/analytic_gradients/analytic_gradient_experiment.py kappa --cases M3R,FUND
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[2] / "ares-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Live-DB-Waechter: Produktivpfad aus derselben Quelle wie ``config``.
from core.db_location import refuse_live_db  # noqa: E402

if not os.environ.get("DB_PATH"):
    raise SystemExit("DB_PATH muss auf eine Wegwerf-Datei zeigen.")
refuse_live_db(os.environ["DB_PATH"], context="analytic_gradient_experiment")
for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_key, "1")

import numpy as np  # noqa: E402
from scipy.optimize import minimize  # noqa: E402

import services.optimizer.solver as solver  # noqa: E402
from services.optimizer import objective as obj  # noqa: E402
from services.optimizer.allocation_intent import (  # noqa: E402
    SOFT_PREFERENCE_ALPHA_DEFAULT,
    preference_loss_from_array,
)
from services.optimizer.certification import (  # noqa: E402
    WILSON_Z_ONE_SIDED_95,
    effective_sample_size,
    wilson_lower_bound,
)
from services.optimizer.house_prior import prior_metric_bps2, tracking_error_bps  # noqa: E402
from services.optimizer.objective_contract import objective_contract_of  # noqa: E402
from services.optimizer.objective_variants import OBJECTIVE_GOAL_SHORTFALL  # noqa: E402
from services.optimizer.priority_scope import PriorityScopeWealth  # noqa: E402
from services.optimizer.scenario_engine import BUCKET_ORDER, build_scenario_paths  # noqa: E402

OUT_DIR = Path(os.environ.get("A07_OUT_DIR") or Path(os.environ["DB_PATH"]).parent)
SCIPY_FD_STEP = 1.4901161193847656e-08  # scipy approx_derivative '2-point', |x| <= 1


# ===========================================================================
# 1. Analytische Zielfunktion + Gradient (Vorwaertsmodus, 5 Richtungen)
# ===========================================================================


def _wilson_lb_and_slope(p: float, n: float, z: float = WILSON_Z_ONE_SIDED_95):
    """Untere Wilson-Grenze und dLB/dp (0 ausserhalb des offenen Bereichs)."""
    lb = wilson_lower_bound(p, n, z=z)
    if n <= 0.0 or p <= 0.0 or p >= 1.0:
        return lb, 0.0
    z2 = z * z
    denom = 1.0 + z2 / n
    root = math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
    raw = (p + z2 / (2.0 * n) - z * root) / denom
    if raw <= 0.0 or raw >= 1.0:
        return lb, 0.0
    slope = (1.0 - z * (1.0 - 2.0 * p) / (2.0 * n * root)) / denom
    return lb, slope


class AnalyticObjective:
    """Zielfunktion ``f = L + C + kappa_H TE^2 (bzw. kappa w'Sw) + P_pref``
    eines OptimizerContext und ihr Gradient nach ``w`` (R^5).

    ``chance``: ``exact`` (Wert exakt, Gradient f.ue. = 0, weil die Strafe
    stueckweise konstant ist), ``smooth`` (logistisch geglaetteter
    Erfolgsindikator in Wert UND Gradient, wie
    ``protected_goal_level_surrogate``), ``none``.

    ``method``: ``adjoint`` (Rueckwaertsrekursion, je Scope EIN Rueckwaerts-
    lauf auf (P,)-Vektoren + EINE Kontraktion mit den Bucket-Renditen) oder
    ``forward`` (Tangenten dW/dw, (P,5) je Jahr -- Referenz). Beide nutzen
    dieselben Saaten dJ/dW[t,p] und dJ/dTWR[p].
    """

    def __init__(self, ctx, *, smooth_width: float = obj.STAGE1_SURROGATE_WIDTH,
                 method: str = "adjoint"):
        contract = objective_contract_of(ctx)
        if contract.objective_mode != OBJECTIVE_GOAL_SHORTFALL:
            raise NotImplementedError("nur goal_shortfall")
        if ctx.tax_regime is not None:
            raise NotImplementedError("Steuer-Pfad (median/binned) nicht abgedeckt")
        self.ctx = ctx
        self.method = method
        self.mode = contract.goal_weighting_mode
        R = np.asarray(ctx.return_paths, dtype=np.float64)
        self.P, self.H, self.B = R.shape
        self.Rt = np.ascontiguousarray(R.transpose(1, 0, 2))  # (H, P, B)
        self.W0 = float(ctx.advisory_wealth_rappen)
        self.scale = obj._context_scale_rappen(self.W0)
        self.width = float(smooth_width)
        if ctx.scenario_weights is None:
            self.omega = np.full(self.P, 1.0 / self.P)
            self.n_eff = float(self.P)
        else:
            wts = np.asarray(ctx.scenario_weights, dtype=np.float64).reshape(-1)
            self.omega = wts / float(np.sum(wts))
            self.n_eff = float(effective_sample_size(wts))
        if ctx.mortality_death_year_index_per_path is not None:
            death = np.asarray(ctx.mortality_death_year_index_per_path, dtype=np.int32)
            self.alive = (np.arange(self.H)[:, None] < death[None, :])  # (H, P)
        else:
            self.alive = None
        self.joint_plan = (
            self._pad(ctx.cashflow_series_rappen), self._pad(ctx.aggregated_liability_path),
        )
        # Prioritaets-Scopes: derselbe Schluessel und dieselbe Plan-Aufbereitung
        # wie die Produktion (priority_scope), nur mit Ableitung simuliert.
        replay = solver._context_replay_inputs(ctx, np.full(self.B, 1.0 / self.B))
        probe = PriorityScopeWealth(
            joint=np.zeros((self.P, self.H + 1)), liabilities=ctx.liabilities, replay=replay,
        )
        self.goal_keys = []
        self.scope_plans = {}
        for goal in ctx.liabilities:
            key = probe._scope_key(goal)
            self.goal_keys.append(key)
            if key is not None and key not in self.scope_plans:
                cash, liab, _div = replay.prepare_scope(key[0], key[1])
                self.scope_plans[key] = (np.asarray(cash, float), np.asarray(liab, float))
        self.n_cols = self.H + 1
        self.stage1_ids = {str(g.goal_id) for g in solver._stage1_liabilities(ctx)}
        cov = ctx.scenario_cov_bps2
        self.house = None if ctx.house_prior_weights is None else np.asarray(ctx.house_prior_weights, float)
        if cov is None:
            self.Q = None
        elif self.house is not None:
            self.Q = float(ctx.house_prior_kappa) * prior_metric_bps2(np.asarray(cov, float)) / 1e8
        else:
            self.Q = obj.TIEBREAK_VARIANCE_WEIGHT * np.asarray(cov, float) / 1e8
        self.n_calls = 0

    def _pad(self, values) -> np.ndarray:
        out = np.zeros(self.H, dtype=np.float64)
        arr = np.asarray(list(values or ()), dtype=np.float64)
        n = min(self.H, arr.size)
        out[:n] = arr[:n]
        return out

    # -- Vermoegensrekursion (+ optional Tangente) -----------------------------
    def _simulate(self, f_hp: np.ndarray, cash: np.ndarray, liab: np.ndarray, tangent: bool):
        """Wie ``scenario_engine._simulate_wealth_paths_untaxed``; liefert
        W (H+1, P), Positivmaske (H, P) und optional S = dW/dw (H+1, P, B)."""
        H, P, B = self.H, self.P, self.B
        W = np.empty((H + 1, P))
        W[0] = self.W0
        pos_all = np.empty((H, P), dtype=bool)
        S = np.zeros((H + 1, P, B)) if tangent else None
        for t in range(H):
            prev = W[t]
            pos = prev > 0
            pos_all[t] = pos
            grown = np.where(pos, prev * f_hp[t], prev)
            if self.alive is not None:
                nxt = grown + cash[t] * self.alive[t]
                nxt = nxt - liab[t] * self.alive[t]
            else:
                nxt = grown + cash[t]
                if liab[t] != 0.0:
                    nxt = nxt - liab[t]
            W[t + 1] = nxt
            if tangent:
                # dW_{t+1}/dw = 1[W_t>0] (f_t dW_t + W_t R_t) + 1[W_t<=0] dW_t
                S[t + 1] = np.where(
                    pos[:, None], S[t] * f_hp[t][:, None] + prev[:, None] * self.Rt[t], S[t],
                )
        return W, pos_all, S

    def _forward(self, w: np.ndarray, tangent: bool):
        f_hp = np.einsum("hpb,b->hp", self.Rt, w)
        scoped = {None: self._simulate(f_hp, *self.joint_plan, tangent)}
        for key, (cash, liab) in self.scope_plans.items():
            scoped[key] = self._simulate(f_hp, cash, liab, tangent)
        safe = np.maximum(f_hp, 1e-12)
        a = np.exp(np.mean(np.log(safe), axis=0)) - 1.0  # (P,)
        return f_hp, safe, scoped, a * 1e4, a

    # -- Bausteine je Ziel: Wert je Pfad + Saat (dWert/dW[Spalte, p], dWert/dTWR[p])
    def _shortfall_sq(self, goal, WgT, twr):
        """(sq je Pfad, Spalten-Saat (P,)|None, Spalte(n) (P,)|int|None, TWR-Saat (P,)|None)."""
        kind = goal.target_kind
        P = self.P
        if kind == "return_rate":
            h = max(1, min(int(goal.target_year_index or (self.n_cols - 1)), self.n_cols - 1))
            base0 = max(1.0, self.W0)
            target = base0 * ((1.0 + float(goal.target_amount_rappen) / 10000.0) ** h)
            base = np.maximum(0.0, 1.0 + twr / 1e4)
            comp = base0 * np.power(base, h)
            s = np.maximum(0.0, target - comp)
            dcomp_dtwr = base0 * h * np.power(base, h - 1) * (base > 0) / 1e4
            return (s / self.scale) ** 2, None, None, -(2.0 * s / self.scale ** 2) * dcomp_dtwr
        if kind == "wealth_at_t":
            idx = max(1, min(int(goal.target_year_index), self.n_cols - 1))
            s = np.maximum(0.0, float(goal.target_amount_rappen) - WgT[idx])
            return (s / self.scale) ** 2, -(2.0 * s / self.scale ** 2), idx, None
        if kind in ("cashflow_in_year", "outflow_stream"):
            due = obj._positive_due_wealth_indices(goal, n_wealth_columns=self.n_cols)
            if due.size == 0:
                return np.zeros(P), None, None, None
            sub = WgT[due]  # (n_due, P)
            j = np.argmin(sub, axis=0)  # Subgradient: aktive Faelligkeit
            m = sub[j, np.arange(P)]
            s = np.maximum(0.0, -m)
            return (s / self.scale) ** 2, -(2.0 * s / self.scale ** 2), due[j], None
        return np.zeros(P), None, None, None

    def _margin(self, goal, WgT, twr):
        """Wie ``objective._success_margin_per_path``: (Abstand, Spalten-Saat, Spalte, TWR-Saat)."""
        kind = goal.target_kind
        if kind == "wealth_at_t":
            idx = max(1, min(int(goal.target_year_index), self.n_cols - 1))
            target = max(1.0, float(goal.target_amount_rappen or 0))
            return (WgT[idx] - target) / target, np.full(self.P, 1.0 / target), idx, None
        if kind in ("cashflow_in_year", "outflow_stream"):
            due = obj._positive_due_wealth_indices(goal, n_wealth_columns=self.n_cols)
            if due.size == 0:
                return None, None, None, None
            volume = max(1.0, obj.goal_volume_rappen(
                goal, initial_value_rappen=self.W0, n_wealth_columns=self.n_cols))
            sub = WgT[due]
            j = np.argmin(sub, axis=0)
            return sub[j, np.arange(self.P)] / volume, np.full(self.P, 1.0 / volume), due[j], None
        if kind == "return_rate":
            h = max(1, min(int(goal.target_year_index or (self.n_cols - 1)), self.n_cols - 1))
            tg = max((1.0 + float(goal.target_amount_rappen or 0) / 10000.0) ** h, 1e-12)
            base = np.maximum(0.0, 1.0 + twr / 1e4)
            dm = (h * np.power(base, h - 1) * (base > 0)) / tg / 1e4
            return np.power(base, h) / tg - 1.0, None, None, dm
        return None, None, None, None

    # -- Gesamtwert ----------------------------------------------------------
    def evaluate(self, w, *, chance: str = "exact", tangent: bool = True,
                 goals_filter=None, include_prior: bool = True,
                 penalty_factor_demoted: bool = True):
        self.n_calls += 1
        w = np.asarray(w, dtype=np.float64).reshape(-1)
        use_forward = tangent and self.method == "forward"
        f_hp, safe, scoped, twr, a = self._forward(w, use_forward)
        P, H, B = self.P, self.H, self.B
        ar = np.arange(P)
        value = 0.0
        seeds = {key: None for key in scoped}  # dJ/dW, (H+1, P)
        twr_seed = np.zeros(P)

        def add_seed(key, coef_p, col):
            if coef_p is None or col is None:
                return
            if seeds[key] is None:
                seeds[key] = np.zeros((H + 1, P))
            if np.ndim(col) == 0:
                seeds[key][int(col)] += coef_p
            else:
                np.add.at(seeds[key], (col, ar), coef_p)

        for goal, key in zip(self.ctx.liabilities, self.goal_keys):
            if goals_filter is not None and str(goal.goal_id) not in goals_filter:
                continue
            WgT = scoped[key][0]
            hw = obj._goal_hardness_weight(goal, self.mode)
            gw = max(1, int(goal.weight_bps)) / 10000.0
            if goal.target_kind == "maximize":
                h = max(1, min(int(goal.target_year_index or (self.n_cols - 1)), max(1, self.n_cols - 1)))
                factor = 1.0 + twr / 1e4
                live = factor >= obj._MAXIMIZE_MIN_GROWTH_FACTOR
                growth = float(h) * np.log(np.maximum(factor, obj._MAXIMIZE_MIN_GROWTH_FACTOR))
                c = obj.MAXIMIZE_GROWTH_WEIGHT * hw * gw
                value -= c * float(self.omega @ growth)
                twr_seed -= c * self.omega * (h * live / np.maximum(factor, 1e-300)) / 1e4
                continue
            sq, col_seed, col, t_seed = self._shortfall_sq(goal, WgT, twr)
            c = hw * gw * obj._demoted_volume_cap(goal, self.W0, self.n_cols)
            value += c * float(self.omega @ sq)
            if tangent:
                if col_seed is not None:
                    add_seed(key, c * self.omega * col_seed, col)
                if t_seed is not None:
                    twr_seed += c * self.omega * t_seed
        # Chance-Strafe
        if chance != "none":
            for goal, key in zip(self.ctx.liabilities, self.goal_keys):
                if goals_filter is not None and str(goal.goal_id) not in goals_filter:
                    continue
                hardness = obj._hardness_key(getattr(goal, "hardness_key", None))
                if hardness not in obj._PRIMARY_HARDNESS_KEYS or goal.target_kind == "maximize":
                    continue
                if goal.target_kind in ("cashflow_in_year", "outflow_stream") and (
                    obj.scheduled_outside_wealth_horizon(goal, n_wealth_columns=self.n_cols)
                ):
                    continue
                WgT = scoped[key][0]
                tau = obj._default_tau_x100(goal) / 10000.0
                rel_vol = obj.goal_volume_rappen(
                    goal, initial_value_rappen=self.W0, n_wealth_columns=self.n_cols,
                ) / self.scale
                factor = obj._demoted_goal_factor(goal, rel_vol) if penalty_factor_demoted else 1.0
                coef = obj.CHANCE_PENALTY_WEIGHT * factor * rel_vol * rel_vol
                if chance == "exact":
                    ind = obj._goal_probability_core(
                        np.ascontiguousarray(WgT.T), goal, int(self.W0),
                        annualized_return_bps_per_path=twr,
                    ).astype(np.float64)
                    lb = wilson_lower_bound(float(self.omega @ ind), self.n_eff)
                    value += coef * max(0.0, tau - lb)
                    continue
                margin, col_seed, col, t_seed = self._margin(goal, WgT, twr)
                if margin is None:
                    continue  # immer erreicht (wie Produktion)
                th = np.tanh(0.5 * margin / self.width)
                p_s = float(self.omega @ (0.5 * (1.0 + th)))
                lb, slope = _wilson_lb_and_slope(p_s, self.n_eff)
                deficit = tau - lb
                if deficit > 0.0:
                    value += coef * deficit
                    if tangent:
                        dsig = (0.25 / self.width) * (1.0 - th * th)
                        k = -coef * slope * self.omega * dsig
                        if col_seed is not None:
                            add_seed(key, k * col_seed, col)
                        if t_seed is not None:
                            twr_seed += k * t_seed
        grad = np.zeros(B)
        if tangent:
            ratio_mask = (f_hp > 1e-12) / safe  # (H, P)
            twr_coef = twr_seed * 1e4 * (1.0 + a) / H  # dJ/df_{t,p} = twr_coef / f_{t,p}
            if self.method == "forward":
                for key, seed in seeds.items():
                    if seed is not None:
                        grad += np.einsum("hp,hpb->b", seed, scoped[key][2])
                grad += np.einsum("hp,hpb->b", twr_coef[None, :] * ratio_mask, self.Rt)
            else:
                C = twr_coef[None, :] * ratio_mask  # dJ/df (H, P), dazu Rekursionsanteil
                for key, seed in seeds.items():
                    if seed is None:
                        continue
                    WgT, pos, _S = scoped[key]
                    lam = seed[H].copy()
                    for t in range(H - 1, -1, -1):
                        # W_{t+1} = pos_t ? W_t f_t : W_t (+ Plan) -> dW_{t+1}/df_t = pos_t W_t
                        C[t] += lam * pos[t] * WgT[t]
                        lam = seed[t] + lam * np.where(pos[t], f_hp[t], 1.0)
                grad += np.einsum("hp,hpb->b", C, self.Rt)
        if include_prior and self.Q is not None:
            delta = w - self.house if self.house is not None else w
            value += float(delta @ self.Q @ delta)
            grad += (self.Q + self.Q.T) @ delta
        pref = self.ctx.preferred_target_bps
        if include_prior and pref:
            value += preference_loss_from_array(w, pref, lam=self.ctx.preference_penalty_lambda)
            for i, bucket in enumerate(BUCKET_ORDER):
                if bucket in pref:
                    grad[i] += 2.0 * self.ctx.preference_penalty_lambda * float(
                        SOFT_PREFERENCE_ALPHA_DEFAULT.get(bucket, 1.0)
                    ) * (w[i] - float(pref[bucket]) / 10000.0)
        return float(value), grad

    def stage1_surrogate(self, w, tangent=True):
        """``protected_goal_level_surrogate`` (Stufe-1-Suche) + Gradient."""
        return self.evaluate(
            w, chance="smooth", tangent=tangent, goals_filter=self.stage1_ids,
            include_prior=False, penalty_factor_demoted=False,
        )


# ===========================================================================
# 2. Produktions-Referenzen
# ===========================================================================


def prod_objective(ctx, w):
    return float(solver._objective_from_array(ctx, np.asarray(w, float)))


def prod_smooth_part(ctx, w):
    """Produktions-Zielfunktion OHNE Chance-Strafe (lambda_chance = 0)."""
    w = np.asarray(w, float)
    contract = objective_contract_of(ctx)
    factors, wealth, twr, scope = solver._evaluation_inputs(ctx, w)
    value = float(obj.combined_objective_two_phase(
        ctx.liabilities, wealth, initial_wealth_rappen=ctx.advisory_wealth_rappen,
        horizon_years=ctx.horizon_years, weights=ctx.scenario_weights,
        annualized_return_bps_per_path=twr, objective_mode=contract.objective_mode,
        goal_weighting_mode=contract.goal_weighting_mode, portfolio_return_factors=factors,
        portfolio_variance=solver._tiebreak_portfolio_variance(ctx, w),
        scope_wealth=scope, lambda_chance=0.0,
    ))
    if ctx.preferred_target_bps:
        value += preference_loss_from_array(w, ctx.preferred_target_bps, lam=ctx.preference_penalty_lambda)
    return value


def prod_stage1_surrogate(ctx, w):
    w = np.asarray(w, float)
    contract = objective_contract_of(ctx)
    _f, wealth, twr, scope = solver._evaluation_inputs(ctx, w)
    return float(obj.protected_goal_level_surrogate(
        solver._stage1_liabilities(ctx), wealth,
        initial_wealth_rappen=ctx.advisory_wealth_rappen, horizon_years=ctx.horizon_years,
        weights=ctx.scenario_weights, annualized_return_bps_per_path=twr,
        goal_weighting_mode=contract.goal_weighting_mode, scope_wealth=scope,
    ))


def central_fd(fun, w, h=1e-6):
    g = np.zeros(len(w))
    for i in range(len(w)):
        e = np.zeros(len(w))
        e[i] = h
        g[i] = (fun(w + e) - fun(w - e)) / (2.0 * h)
    return g


def forward_fd(fun, w, h=SCIPY_FD_STEP):
    f0 = fun(w)
    g = np.zeros(len(w))
    for i in range(len(w)):
        e = np.zeros(len(w))
        e[i] = h
        g[i] = (fun(w + e) - f0) / h
    return g


def rel_err(a, b):
    return float(np.linalg.norm(a - b) / max(np.linalg.norm(b), 1e-12))


# ===========================================================================
# 3. Faelle: Referenzmandate M1-M5 (tests/test_engine_reference_mandates.py),
#    M3R (M3 mit Raengen 1/2/3 -> Prioritaets-Scope-Replays), Fundament
# ===========================================================================


def _cma(id_):
    return SimpleNamespace(**{
        "id": id_,
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
    })


def _hm(kind):
    rows = {
        "wachstum": dict(profile_name="Wachstumsorientiert",
            equity_min_bps=4500, equity_max_bps=7000, equity_target_bps=6000,
            bonds_min_bps=2000, bonds_max_bps=4500, bonds_target_bps=3000,
            real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
            alt_min_bps=0, alt_max_bps=1000, alt_target_bps=300,
            liq_min_bps=200, liq_max_bps=2000, liq_target_bps=200, max_risky_fraction_bps=7500),
        "konservativ": dict(profile_name="Konservativ",
            equity_min_bps=500, equity_max_bps=2500, equity_target_bps=1500,
            bonds_min_bps=5000, bonds_max_bps=8000, bonds_target_bps=6500,
            real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
            alt_min_bps=0, alt_max_bps=500, alt_target_bps=200,
            liq_min_bps=500, liq_max_bps=2000, liq_target_bps=1000, max_risky_fraction_bps=3000),
        "ausgewogen": dict(profile_name="Ausgewogen",
            equity_min_bps=2500, equity_max_bps=5000, equity_target_bps=4000,
            bonds_min_bps=3500, bonds_max_bps=6000, bonds_target_bps=4500,
            real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
            alt_min_bps=0, alt_max_bps=1000, alt_target_bps=300,
            liq_min_bps=300, liq_max_bps=2000, liq_target_bps=500, max_risky_fraction_bps=5500),
    }
    return SimpleNamespace(**rows[kind])


def _goal(goal_id, label, hardness, goal_type="Vermoegensziel", target_rappen=1_000_000_00,
          days=365 * 10, is_ongoing=False, rank=1):
    today = date.today()
    return SimpleNamespace(
        id=goal_id, label=label, goal_type=goal_type,
        target_amount_rappen=target_rappen, target_wealth_rappen=target_rappen,
        target_return_bps=None, horizon_years=None, start_date=today.isoformat(),
        target_date=(today + timedelta(days=days)).isoformat(),
        is_ongoing=1 if is_ongoing else 0, frequency="jaehrlich",
        hardness=hardness, rank=rank, weight_bps=5000, value_mode="real",
    )


def reference_case(name: str) -> dict:
    if name == "M1":
        return dict(cma=_cma("cma-m1"), goals=[_goal("m1-lebenshaltung", "Lebensunterhalt", "Hart",
                    target_rappen=80_000_00, days=365 * 27)],
                    house_matrix_row=_hm("konservativ"), score_x10=25,
                    advisory_wealth_rappen=2_500_000_00, cashflow_series_rappen=[-80_000_00] * 27,
                    horizon_years=27, n_paths=500, seed=1, is_retired=True)
    if name == "M2":
        return dict(cma=_cma("cma-m2"), goals=[
                    _goal("m2-eigenheim", "Eigenheim", "Opportunistisch", target_rappen=600_000_00, days=365 * 15),
                    _goal("m2-max", "Max", "Opportunistisch", goal_type="Maximierung", target_rappen=0, days=365 * 30)],
                    house_matrix_row=_hm("wachstum"), score_x10=85,
                    advisory_wealth_rappen=200_000_00, cashflow_series_rappen=[10_000_00] * 30,
                    horizon_years=30, n_paths=500, seed=2, is_retired=False)
    if name in ("M3", "M3R"):
        # M3R: Erbschaft (Rang 1) vor Pension (Rang 2) -> der Rang-1-Scope
        # enthaelt die Pensionsabfluesse NICHT (direkter Scope-Replay).
        ranks = (2, 1, 3) if name == "M3R" else (1, 1, 1)
        return dict(cma=_cma("cma-m3"), goals=[
                    _goal("m3-pension", "Pension", "Hart", goal_type="Pensionsausgabe",
                          target_rappen=720_000_00, days=365 * 10, is_ongoing=True, rank=ranks[0]),
                    _goal("m3-erbschaft", "Erbschaft", "Primär", target_rappen=5_000_000_00, days=365 * 25, rank=ranks[1]),
                    _goal("m3-rendite", "Rendite", "Opportunistisch", goal_type="Renditeziel",
                          target_rappen=0, days=365 * 25, rank=ranks[2])],
                    house_matrix_row=_hm("ausgewogen"), score_x10=55,
                    advisory_wealth_rappen=50_000_000_00, cashflow_series_rappen=[200_000_00] * 25,
                    horizon_years=25, n_paths=500, seed=3)
    if name == "M4":
        return dict(cma=_cma("cma-m4-direct"), goals=[_goal("m4-pension", "Pension", "Primär",
                    target_rappen=2_000_000_00, days=365 * 20)],
                    house_matrix_row=_hm("wachstum"), score_x10=75,
                    advisory_wealth_rappen=1_000_000_00, cashflow_series_rappen=[20_000_00] * 20,
                    horizon_years=20, n_paths=500, seed=4)
    if name == "M5":
        return dict(cma=_cma("cma-m5"), goals=[_goal("m5-erbe", "Erbe", "Hart",
                    target_rappen=1_000_000_00, days=365 * 25)],
                    house_matrix_row=_hm("konservativ"), score_x10=30,
                    advisory_wealth_rappen=1_500_000_00, cashflow_series_rappen=[5_000_00] * 25,
                    horizon_years=25, n_paths=500, seed=5, is_retired=True)
    raise KeyError(name)


_FOUNDATION_KWARGS: dict | None = None


def foundation_case() -> dict:
    """run_solver-kwargs des Fundament-Falls aus EINEM Lauf der Stage-8-Pipeline
    (shadow_stochastic) auf einer frischen SQLite-Datei; danach direkt
    ``run_solver`` (kein weiterer Pipeline-Lauf)."""
    global _FOUNDATION_KWARGS
    if _FOUNDATION_KWARGS is not None:
        return dict(_FOUNDATION_KWARGS)
    import pickle

    cache_file = OUT_DIR / f"a07_fund_kwargs_{date.today().isoformat()}.pkl"
    if cache_file.exists():
        _FOUNDATION_KWARGS = pickle.loads(cache_file.read_bytes())
        return dict(_FOUNDATION_KWARGS)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import configure_mappers, sessionmaker

    from database import Base
    import importlib
    import pkgutil

    import models

    for module in pkgutil.iter_modules(models.__path__):
        importlib.import_module(f"models.{module.name}")
    configure_mappers()
    import services.portfolio_engine as pe
    from models.mandates import Mandate
    from models.users import User
    from services.foundation_example import FOUNDATION_MANDATE_NUMBER, upsert_foundation_example_case
    from services.portfolio_engine import ensure_runtime_reference_data, generate_target_allocation

    db_file = Path(os.environ["DB_PATH"]).with_name(Path(os.environ["DB_PATH"]).stem + "_fund.db")
    if db_file.exists():
        db_file.unlink()
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    captured: list[dict] = []
    original = solver.run_solver

    from sqlalchemy import inspect as sa_inspect

    def snapshot(value):
        """ORM-Zeilen als losgeloeste SimpleNamespace (Session schliesst danach)."""
        try:
            mapper = sa_inspect(value).mapper
        except Exception:  # noqa: BLE001 - kein ORM-Objekt
            return value
        return SimpleNamespace(**{a.key: getattr(value, a.key) for a in mapper.column_attrs})

    def capture(**kwargs):
        if not captured:
            frozen = dict(kwargs)
            frozen["cma"] = snapshot(kwargs["cma"])
            frozen["house_matrix_row"] = snapshot(kwargs["house_matrix_row"])
            frozen["goals"] = [snapshot(g) for g in kwargs["goals"]]
            captured.append(frozen)
        return original(**kwargs)

    solver.run_solver = capture
    old_mode = pe.settings.optimizer_mode
    started = time.perf_counter()
    try:
        with SF() as s:
            advisor = User(id="advisor-a07", username="advisor-a07", password_hash="h",
                           full_name="A07", role="advisor", is_active=1,
                           created_at="2026-05-24T00:00:00.000Z", updated_at="2026-05-24T00:00:00.000Z")
            s.add(advisor)
            s.commit()
            upsert_foundation_example_case(s, advisor)
            ensure_runtime_reference_data(s, "advisor-a07")
            s.commit()
            mandate = s.query(Mandate).filter(Mandate.mandate_number == FOUNDATION_MANDATE_NUMBER).one()
            pe.settings.optimizer_mode = "shadow_stochastic"
            generate_target_allocation(s, mandate, "advisor-a07", preferences=None)
            s.rollback()
    finally:
        pe.settings.optimizer_mode = old_mode
        solver.run_solver = original
        engine.dispose()
    pipeline_s = time.perf_counter() - started
    if not captured:
        raise RuntimeError("Fundament: run_solver wurde nicht aufgerufen")
    kwargs = captured[0]
    kwargs.pop("optimizer_context", None)
    kwargs["_pipeline_seconds"] = pipeline_s
    _FOUNDATION_KWARGS = kwargs
    try:
        cache_file.write_bytes(pickle.dumps(kwargs))
    except Exception as exc:  # noqa: BLE001 - Cache ist optional
        print("Fundament-Cache nicht geschrieben:", exc)
    return dict(kwargs)


def calibration_case(name: str) -> dict:
    """Kalibrierungsmandate A-E (tools/house_prior_calibration, 2000 Pfade):
    knappe Ziele -> Fehlbetrag und Chance-Strafe aktiv."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "house_prior_calibration"))
    import calibration_common as cc  # noqa: E402

    key = next(k for k in cc.MANDATES if k.startswith(name + "_"))
    return cc.build_inputs(key)


def case_kwargs(name: str) -> dict:
    if name == "FUND":
        return foundation_case()
    if name in ("A", "B", "C", "D", "E"):
        return calibration_case(name)
    return reference_case(name)


# ===========================================================================
# 4. Solver-Harness: jac per Monkeypatch, Zaehler, Laufzeit
# ===========================================================================

STATE: dict = {"mode": "fd", "ao": None, "stage": "stage2", "sims": 0, "grads": 0, "slsqp_seconds": 0.0,
               "starts": 0, "nfev": 0, "njev": 0, "nit": 0, "bags": []}
_ORIG = {
    "select": solver._select_cube_candidate,
    "stage1": solver._goal_protection_stage,
    "solve": solver._solve_single_start,
    "inputs": solver._evaluation_inputs,
}


def _patched_inputs(context, w):
    STATE["sims"] += 1
    return _ORIG["inputs"](context, w)


def _patched_select(context, **kwargs):
    STATE["ao"] = AnalyticObjective(context) if STATE["mode"] != "fd" else None
    STATE["stage"] = "stage2"
    STATE["bags"].append(context)
    selection = _ORIG["select"](context, **kwargs)
    if STATE["mode"] == "constrained":
        _constrained_stage2(context, selection, kwargs.get("max_iter", 50), kwargs.get("ftol", 1e-6))
    return selection


def _constrained_stage2(ctx, selection, max_iter, ftol):
    """Variante ``constrained``: bindet die Stufe-1-Schranke, ersetzt ein
    SLSQP-Lauf MIT Nebenbedingung ``G1_glatt(w) <= Schranke`` (analytische
    Jacobi-Matrix) die Streckensuche; entschieden wird EXAKT (G1 und f)."""
    audit = selection.goal_protection
    if not audit or not audit.get("constraint_pass") or selection.weights is None:
        return
    ao: AnalyticObjective = STATE["ao"]
    bound = float(audit["bound"])
    tol = 1e-9 * max(1.0, abs(bound))
    unit = max(abs(bound), 1e-12)

    def level(w):
        return solver._protected_level_from_inputs(ctx, _ORIG["inputs"](ctx, w))[0]

    def exact_f(w):
        return float(solver._objective_from_array(ctx, w))

    x0 = np.asarray(selection.weights, float)
    cons = list(ctx.scipy_constraints) + [{
        "type": "ineq",
        "fun": lambda w: (bound - ao.stage1_surrogate(w, tangent=False)[0]) / unit,
        "jac": lambda w: -ao.stage1_surrogate(w)[1] / unit,
    }]
    res = minimize(lambda w: ao.evaluate(w, chance="exact", tangent=False)[0],
                   x0=x0, jac=lambda w: ao.evaluate(w, chance="exact")[1],
                   method="SLSQP", bounds=ctx.bounds, constraints=cons,
                   options={"maxiter": max_iter, "ftol": ftol, "disp": False})
    STATE["nfev"] += int(res.nfev)
    STATE["njev"] += int(res.njev)
    STATE["nit"] += int(res.nit)
    best_w, best_f = x0, exact_f(x0)
    cand = solver._normalize_to_bounds(np.asarray(res.x, float), ctx.bounds)
    for t in (1.0, 0.75, 0.5, 0.25):
        trial = solver._normalize_to_bounds((1.0 - t) * x0 + t * cand, ctx.bounds)
        ok, _v = solver.is_feasible(trial, bounds=ctx.bounds, constraints=ctx.scipy_constraints)
        if not ok or level(trial) > bound + tol:
            continue
        value = exact_f(trial)
        if value < best_f:
            best_w, best_f = trial, value
        break
    if best_w is not x0:
        STATE["constrained_improved"] = STATE.get("constrained_improved", 0) + 1
        selection.weights = np.asarray(best_w, float).copy()
        selection.objective = best_f


def _patched_stage1(*args, **kwargs):
    STATE["stage"] = "stage1"
    try:
        return _ORIG["stage1"](*args, **kwargs)
    finally:
        STATE["stage"] = "stage2"


def _patched_solve(objective_fn, x0, bounds, constraints, *, max_iter=50, ftol=1e-6):
    STATE["starts"] += 1
    started = time.perf_counter()
    if STATE["mode"] == "fd":
        res = _ORIG["solve"](objective_fn, x0, bounds, constraints, max_iter=max_iter, ftol=ftol)
    else:
        ao: AnalyticObjective = STATE["ao"]
        if STATE["stage"] == "stage1":
            target = lambda w: ao.stage1_surrogate(w)  # noqa: E731
            exact_at = lambda w: ao.stage1_surrogate(w, tangent=False)[0]  # noqa: E731
        else:
            chance = "smooth" if STATE["mode"] == "smooth" else "exact"
            target = lambda w: ao.evaluate(w, chance=chance)  # noqa: E731
            exact_at = lambda w: ao.evaluate(w, chance="exact", tangent=False)[0]  # noqa: E731
        # Skala der Produktions-Closure (f / unit) aus dem Startpunkt.
        prod0 = float(objective_fn(x0))
        unit = exact_at(x0) / prod0 if prod0 not in (0.0,) and np.isfinite(prod0) else 1.0
        if not np.isfinite(unit) or unit == 0.0:
            unit = 1.0

        if STATE.get("split", True):
            # Wert (Linesearch) ohne Rueckwaertslauf; Gradient nur an den
            # Punkten, an denen SLSQP ihn anfordert (je Iteration einmal).
            if STATE["stage"] == "stage1":
                value_at = lambda w: ao.stage1_surrogate(w, tangent=False)[0]  # noqa: E731
            else:
                value_at = lambda w: ao.evaluate(w, chance=chance, tangent=False)[0]  # noqa: E731

            def fun(w):
                return value_at(w) / unit

            def jac(w):
                STATE["grads"] += 1
                return target(w)[1] / unit

            res = minimize(fun, x0=x0, jac=jac, method="SLSQP", bounds=bounds,
                           constraints=constraints,
                           options={"maxiter": max_iter, "ftol": ftol, "disp": False})
        else:
            def fun(w):
                STATE["grads"] += 1
                v, g = target(w)
                return v / unit, g / unit

            res = minimize(fun, x0=x0, jac=True, method="SLSQP", bounds=bounds,
                           constraints=constraints,
                           options={"maxiter": max_iter, "ftol": ftol, "disp": False})
    STATE["slsqp_seconds"] += time.perf_counter() - started
    STATE["nfev"] += int(getattr(res, "nfev", 0) or 0)
    STATE["njev"] += int(getattr(res, "njev", 0) or 0)
    STATE["nit"] += int(getattr(res, "nit", 0) or 0)
    return res


def install_patches():
    solver._select_cube_candidate = _patched_select
    solver._goal_protection_stage = _patched_stage1
    solver._solve_single_start = _patched_solve
    solver._evaluation_inputs = _patched_inputs


def run_case(name: str, mode: str, *, kappa: float | None = None) -> dict:
    kwargs = case_kwargs(name)
    kwargs.pop("_pipeline_seconds", None)
    STATE.update(mode=mode, sims=0, grads=0, starts=0, nfev=0, njev=0, nit=0, bags=[], slsqp_seconds=0.0, constrained_improved=0)
    old_kappa = solver.HOUSE_PRIOR_KAPPA
    if kappa is not None:
        solver.HOUSE_PRIOR_KAPPA = float(kappa)
    started = time.perf_counter()
    try:
        result = solver.run_solver(**kwargs)
    finally:
        solver.HOUSE_PRIOR_KAPPA = old_kappa
    elapsed = time.perf_counter() - started
    ctx = result.context
    w = np.array([result.weights_bps[b] / 10000.0 for b in BUCKET_ORDER])
    # Trainings-Zielfunktion je Bag (gleiche Wuerfel in allen Modi): Mittel
    bag_obj = [row.get("objective_value") for row in (result.resampling or {}).get("bags", []) or []]
    te = None
    if ctx is not None and ctx.house_prior_weights is not None and ctx.scenario_cov_bps2 is not None:
        te = tracking_error_bps(w, ctx.house_prior_weights, ctx.scenario_cov_bps2)
    return {
        "case": name, "mode": mode, "kappa": kappa, "seconds": round(elapsed, 3),
        "status": result.status, "weights_bps": dict(result.weights_bps),
        "objective_value": float(result.objective_value),
        "sims": STATE["sims"], "analytic_evals": STATE["grads"], "starts": STATE["starts"], "slsqp_seconds": round(STATE["slsqp_seconds"], 3), "constrained_improved": STATE.get("constrained_improved", 0),
        "nfev": STATE["nfev"], "njev": STATE["njev"], "nit": STATE["nit"],
        "te_bps": te, "oos": oos_metrics(ctx, w) if ctx is not None else None,
        # je Bag: TE zur Hausquote und ob die Stufe-1-Schranke band
        # (dann Streckensuche statt Minimierer der kappa-Zielfunktion)
        "bags": [
            {
                "te_bps": (tracking_error_bps(
                    np.array([row["weights_bps"][b] / 10000.0 for b in BUCKET_ORDER]),
                    ctx.house_prior_weights, ctx.scenario_cov_bps2)
                    if row.get("weights_bps") and ctx is not None and ctx.house_prior_weights is not None
                    else None),
                "bound_binding": bool((row.get("goal_protection") or {}).get("constraint_pass")),
                "objective": row.get("objective_value"),
            }
            for row in ((result.resampling or {}).get("bags") or [])
        ],
        "bag_objective_mean": (float(np.mean([v for v in bag_obj if v is not None])) if bag_obj else None),
    }


_OOS_CACHE: dict = {}


def oos_metrics(ctx, w, n_paths: int = 20000, seed: int = 0xA07) -> dict:
    """Zielebene (Fehlbetrag + Chance-Strafe) und P(Ziel) auf einem
    unabhaengigen antithetischen Wuerfel (gleiche Verteilung, ohne IS)."""
    key = (id(ctx.scenario_inputs), ctx.horizon_years)
    vctx = _OOS_CACHE.get(key)
    if vctx is None:
        horizon = int(ctx.scenario_horizon_years or ctx.horizon_years)
        paths = build_scenario_paths(ctx.scenario_inputs, horizon_years=horizon,
                                     n_paths=n_paths, seed=seed, antithetic=True)
        paths = paths[:, : int(ctx.horizon_years), :]
        death = ctx.mortality_death_year_index_per_path
        if death is not None:
            death = np.full(n_paths, int(np.asarray(death)[0]), dtype=np.int32)
        vctx = replace(ctx, return_paths=paths, scenario_weights=None, n_paths=n_paths,
                       mortality_death_year_index_per_path=death)
        _OOS_CACHE[key] = vctx
    contract = objective_contract_of(vctx)
    factors, wealth, twr, scope = _ORIG["inputs"](vctx, w)
    goal_level, _tb = obj.two_phase_objective_parts(
        vctx.liabilities, wealth, initial_wealth_rappen=vctx.advisory_wealth_rappen,
        horizon_years=vctx.horizon_years, weights=None, annualized_return_bps_per_path=twr,
        objective_mode=contract.objective_mode, goal_weighting_mode=contract.goal_weighting_mode,
        portfolio_return_factors=factors, portfolio_variance=solver._tiebreak_portfolio_variance(vctx, w),
        scope_wealth=scope,
    )
    probs = {}
    for goal in vctx.liabilities:
        if goal.target_kind == "maximize":
            continue
        per = obj.goal_probability_per_path(wealth, goal, int(vctx.advisory_wealth_rappen),
                                            annualized_return_bps_per_path=twr, scope_wealth=scope)
        probs[str(goal.goal_id)] = round(float(np.mean(per)), 5)
    return {"goal_level": float(goal_level), "p_goal": probs}


# ===========================================================================
# 5. Kommandos
# ===========================================================================


def _feasible_points(ctx, n_random: int, rng) -> list[np.ndarray]:
    pts = [np.asarray(x, float) for x in solver._cube_initial_guesses(ctx)]
    if ctx.house_prior_weights is not None:
        pts.append(np.asarray(ctx.house_prior_weights, float))
    lo = np.array([b[0] for b in ctx.bounds])
    hi = np.array([b[1] for b in ctx.bounds])
    tries = 0
    while n_random > 0 and tries < 2000:
        tries += 1
        x = lo + rng.random(len(lo)) * (hi - lo)
        x = solver._normalize_to_bounds(x, ctx.bounds)
        ok, _ = solver.is_feasible(x, bounds=ctx.bounds, constraints=ctx.scipy_constraints)
        if ok:
            pts.append(x)
            n_random -= 1
    return pts


def capture_bag_contexts(name: str, n_bags: int) -> list:
    """Bag-Wuerfel (mit Haus-Prior) eines Produktionslaufs, erste ``n_bags``."""
    run_case(name, "fd")
    return list(STATE["bags"][:n_bags])


def cmd_check(cases: list[str], n_bags: int, n_random: int) -> dict:
    rng = np.random.default_rng(20261022)
    out = {}
    for name in cases:
        rows = []
        for ctx in capture_bag_contexts(name, n_bags):
            ao = AnalyticObjective(ctx)
            for w in _feasible_points(ctx, n_random, rng):
                v_mine, g_mine_exact = ao.evaluate(w, chance="exact")
                v_prod = prod_objective(ctx, w)
                v_s_mine, g_s = ao.evaluate(w, chance="none")
                g_fd = central_fd(lambda x: prod_smooth_part(ctx, x), w)
                v1, g1 = ao.stage1_surrogate(w)
                v1_prod = prod_stage1_surrogate(ctx, w) if ao.stage1_ids else 0.0
                g1_fd = central_fd(lambda x: prod_stage1_surrogate(ctx, x), w) if ao.stage1_ids else np.zeros(5)
                vs, gs = ao.evaluate(w, chance="smooth")
                gs_fd = central_fd(lambda x: ao.evaluate(x, chance="smooth", tangent=False)[0], w)
                # Vorwaerts- und Rueckwaertsmodus muessen uebereinstimmen
                _vf, g_fwd = AnalyticObjective(ctx, method="forward").evaluate(w, chance="smooth")
                # Was SLSQP heute sieht: Vorwaerts-FD der EXAKTEN Funktion (scipy-Schritt)
                g_scipy = forward_fd(lambda x: prod_objective(ctx, x), w)
                big = np.linalg.norm(g_mine_exact) > 1e-4
                rows.append({
                    "value_rel_diff": abs(v_mine - v_prod) / max(abs(v_prod), 1e-300),
                    "adjoint_vs_forward_rel_err": rel_err(gs, g_fwd),
                    "grad_smooth_rel_err": rel_err(g_s, g_fd),
                    "stage1_value_rel_diff": abs(v1 - v1_prod) / max(abs(v1_prod), 1e-300) if ao.stage1_ids else 0.0,
                    "stage1_grad_rel_err": rel_err(g1, g1_fd) if ao.stage1_ids and np.linalg.norm(g1_fd) > 0 else None,
                    "smooth_grad_rel_err": rel_err(gs, gs_fd),
                    "scipy_fd_vs_analytic_rel_err": rel_err(g_scipy, g_mine_exact) if big else None,
                    "scipy_fd_abs_err": float(np.max(np.abs(g_scipy - g_mine_exact))),
                    "scipy_fd_spike": bool(np.max(np.abs(g_scipy - g_mine_exact)) > 1.0),
                    "chance_part": v_mine - v_s_mine,
                    "goal_grad_norm": float(np.linalg.norm(
                        ao.evaluate(w, chance="smooth", include_prior=False)[1])),
                    "n_scopes": len(ao.scope_plans),
                })
        # Laufzeit je Auswertung: Produktion vs. analytisch (Wert+Gradient)
        ctx = STATE["bags"][0]
        ao = AnalyticObjective(ctx)
        w = np.asarray(solver._cube_initial_guesses(ctx)[0], float)
        reps = 30
        t0 = time.perf_counter()
        for k in range(reps):
            prod_objective(ctx, w + 1e-9 * k)
        t_prod = (time.perf_counter() - t0) / reps
        t0 = time.perf_counter()
        for k in range(reps):
            ao.evaluate(w + 1e-9 * k, chance="exact")
        t_grad = (time.perf_counter() - t0) / reps
        t0 = time.perf_counter()
        for k in range(reps):
            ao.evaluate(w + 1e-9 * k, chance="exact", tangent=False)
        t_val = (time.perf_counter() - t0) / reps
        ao_f = AnalyticObjective(ctx, method="forward")
        t0 = time.perf_counter()
        for k in range(reps):
            ao_f.evaluate(w + 1e-9 * k, chance="exact")
        t_fwd = (time.perf_counter() - t0) / reps

        def q(key):
            vals = [r[key] for r in rows if r[key] is not None]
            return {"max": float(np.max(vals)), "median": float(np.median(vals))} if vals else None

        out[name] = {
            "n_points": len(rows), "n_scopes": rows[0]["n_scopes"] if rows else 0,
            "value_rel_diff": q("value_rel_diff"),
            "adjoint_vs_forward_rel_err": q("adjoint_vs_forward_rel_err"),
            "grad_smooth_rel_err": q("grad_smooth_rel_err"),
            "stage1_value_rel_diff": q("stage1_value_rel_diff"),
            "stage1_grad_rel_err": q("stage1_grad_rel_err"),
            "smooth_grad_rel_err": q("smooth_grad_rel_err"),
            "scipy_fd_vs_analytic_rel_err": q("scipy_fd_vs_analytic_rel_err"),
            "scipy_fd_abs_err": q("scipy_fd_abs_err"),
            "scipy_fd_spikes": int(sum(r["scipy_fd_spike"] for r in rows)),
            "ms_forward_value_grad": round(1e3 * t_fwd, 3),
            "points_with_active_chance": int(sum(r["chance_part"] > 0 for r in rows)),
            "points_with_goal_gradient": int(sum(r["goal_grad_norm"] > 1e-8 for r in rows)),
            "ms_prod_value": round(1e3 * t_prod, 3),
            "ms_analytic_value_grad": round(1e3 * t_grad, 3),
            "ms_analytic_value_only": round(1e3 * t_val, 3),
            "ms_fd_gradient_equiv": round(1e3 * t_prod * 6, 3),
        }
        print(name, json.dumps(out[name]), flush=True)
    return out


def cmd_solve(cases: list[str], modes: list[str]) -> list[dict]:
    rows = []
    for name in cases:
        for mode in modes:
            row = run_case(name, mode)
            rows.append(row)
            print(json.dumps(row), flush=True)
    return rows


def cmd_kappa(cases: list[str], modes: list[str], kappas: list[float]) -> list[dict]:
    rows = []
    for name in cases:
        for mode in modes:
            for kappa in kappas:
                row = run_case(name, mode, kappa=kappa)
                rows.append(row)
                print(json.dumps({k: row[k] for k in ("case", "mode", "kappa", "te_bps", "seconds", "weights_bps")}
                                 | {"oos_goal_level": row["oos"]["goal_level"]}), flush=True)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "solve", "kappa"))
    parser.add_argument("--cases", default="M1,M2,M3,M3R,M4,M5,FUND")
    parser.add_argument("--modes", default="fd,analytic,smooth")
    parser.add_argument("--kappas", default="30,100,300,1000,3000")
    parser.add_argument("--bags", type=int, default=2)
    parser.add_argument("--random", type=int, default=3)
    args = parser.parse_args(argv)
    install_patches()
    cases = [c.strip() for c in args.cases.split(",") if c.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if args.command == "check":
        result = cmd_check(cases, args.bags, args.random)
    elif args.command == "solve":
        result = cmd_solve(cases, modes)
    else:
        result = cmd_kappa(cases, modes, [float(k) for k in args.kappas.split(",")])
    out = OUT_DIR / f"a07_gradients_{args.command}_{'_'.join(cases)}.json"
    out.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print("->", out)
    if "FUND" in cases and _FOUNDATION_KWARGS is not None:
        print("Fundament-Pipeline (1 Lauf, shadow_stochastic):",
              round(_FOUNDATION_KWARGS["_pipeline_seconds"], 2), "s")


if __name__ == "__main__":
    main()
