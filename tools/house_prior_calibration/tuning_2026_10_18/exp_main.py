"""House-Shrinkage-Experiment: (a) binaer vs (b) stetige Schrumpfung vs
(c) Haus-Prior im Optimierer vs (d) Ueberlegenheit mit Marge (TOST-artig).

Aufruf:  python exp_main.py sweep  <mandat> [fixed]   -> out/sweep_<mandat>[_fixed].jsonl
         python exp_main.py seeds  <mandat>           -> out/seeds_<mandat>.jsonl
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exp_common import (  # noqa: E402
    BUCKET_ORDER, S, _seed_of, bps_to_w, build_scenario_paths, goal_probability_per_path,
    np, oos_context, run, run_prior,
)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)

KAPPAS = (100.0, 1000.0)
MARGINS = (0.001, 0.005)
N_OOS = 20000
N_WORLDS, N_WORLD_PATHS, T_EST = 30, 3000, 20


def lambdas(improvement, reps):
    if reps is None or improvement is None:
        return {}
    reps = np.asarray(reps, dtype=float)
    se2 = float(np.var(reps, ddof=1))
    d = float(improvement)
    if d <= 0:
        eb = 0.0
    elif se2 <= 0:
        eb = 1.0
    else:
        eb = max(0.0, 1.0 - se2 / (d * d))
    p_pos = float(np.mean(reps > 0.0))
    return {
        "eb": eb,                              # empirisch-Bayes / James-Stein-Faktor
        "prob": max(0.0, 2.0 * p_pos - 1.0),   # 2 P(Delta>0) - 1
        "_p_pos": p_pos, "_se": float(np.sqrt(se2)), "_d": d,
        "_q05": float(np.quantile(reps, 0.05)),
    }


def mix_bps(ctx, w_h, w_o, lam):
    w = w_h + lam * (w_o - w_h)
    bps = S._rounded_bps_with_repair(w, ctx)
    ok, _ = S.is_feasible(S._trusted_weights_bps_to_array(bps), bounds=ctx.bounds,
                          constraints=ctx.scipy_constraints)
    return bps, bool(ok)


def world_contexts(ctx, name):
    """Parameterunsicherheit: konstanter Drift-Shift je Welt,
    delta ~ N(0, Sigma_bucket / T_EST) (Schaetzfehler des Mittels aus T_EST
    Jahresbeobachtungen), auf einem frischen nominalen Wuerfel."""
    H = int(ctx.scenario_horizon_years or ctx.horizon_years)
    cov = np.asarray(ctx.scenario_cov_bps2, dtype=float) / 1e8
    L = np.linalg.cholesky(cov / T_EST + 1e-12 * np.eye(len(cov)))
    rng = np.random.default_rng(_seed_of(name, "worlds"))
    base = build_scenario_paths(ctx.scenario_inputs, horizon_years=H, n_paths=N_WORLD_PATHS,
                                seed=_seed_of(name, "world-paths"), antithetic=True)[:, : int(ctx.horizon_years), :]
    out = []
    for _ in range(N_WORLDS):
        delta = L @ rng.standard_normal(len(cov))
        out.append(replace(ctx, return_paths=base + delta[None, None, :],
                           scenario_weights=None, n_paths=N_WORLD_PATHS))
    return out


def eval_alloc(vctx, w, w_ref):
    pair = S._context_loss_components_on_validation(vctx, w_ref, w, validation_seed=None)
    (_a, _b), (g, _r) = pair(None)
    wealth = S._simulate_context_wealth(vctx, w)
    probs = [float(np.mean(goal_probability_per_path(wealth, liab, vctx.advisory_wealth_rappen)))
             for liab in vctx.liabilities]
    return float(g), probs


def evaluate_set(ctx, name, allocs, oos_cache):
    if "oos" not in oos_cache:
        oos_cache["oos"] = replace(oos_context(ctx, n_paths=N_OOS, salt="x"),
                                   return_paths=build_scenario_paths(
                                       ctx.scenario_inputs,
                                       horizon_years=int(ctx.scenario_horizon_years or ctx.horizon_years),
                                       n_paths=N_OOS, seed=_seed_of(name, "oos"), antithetic=True,
                                   )[:, : int(ctx.horizon_years), :])
        oos_cache["worlds"] = world_contexts(ctx, name)
    # Liabilities/Cashflows haengen vom Zielbetrag ab -> Context-Felder des
    # aktuellen Laufs auf die gecachten Pfade setzen.
    oos = replace(ctx, return_paths=oos_cache["oos"].return_paths, scenario_weights=None, n_paths=N_OOS)
    worlds = [replace(ctx, return_paths=wc.return_paths, scenario_weights=None, n_paths=N_WORLD_PATHS)
              for wc in oos_cache["worlds"]]
    w_ref = bps_to_w(allocs["a"])
    res = {}
    for key, bps in allocs.items():
        w = bps_to_w(bps)
        g, probs = eval_alloc(oos, w, w_ref)
        wg = [eval_alloc(wc, w, w_ref) for wc in worlds]
        vol = float(np.sqrt(S._tiebreak_portfolio_variance(ctx, w)))
        mu = float(np.dot(w, np.asarray(ctx.scenario_mu_bps, dtype=float))) / 1e4 if getattr(ctx, "scenario_mu_bps", None) is not None else None
        res[key] = dict(
            bps=bps, oos_goal=g, oos_prob=probs[0] if probs else None,
            world_goal=float(np.mean([x[0] for x in wg])),
            world_prob=float(np.mean([x[1][0] for x in wg])) if wg and wg[0][1] else None,
            world_prob_p10=float(np.quantile([x[1][0] for x in wg], 0.10)) if wg and wg[0][1] else None,
            vol=vol, mu=mu,
        )
    return res


def one_point(name, scale, seed, oos_cache):
    t0 = time.time()
    r = run(name, scale, seed=seed)
    ctx = r["ctx"]
    rec = dict(mandate=name, scale=scale, seed=seed, decision=r["decision"],
               reason=r["sig"].get("reason"), p=r["p"], improvement=r["improvement"],
               elapsed_ms_a=r["elapsed_ms"], anchor=r["anchor"], candidate=r["candidate"])
    allocs = {"a": dict(r["final"])}
    if r["anchor"] and r["candidate"] and r["decision"] in ("house_matrix", "optimizer"):
        w_h, w_o = bps_to_w(r["anchor"]), bps_to_w(r["candidate"])
        lam = lambdas(r["improvement"], r["reps"]) if r["anchor"] != r["candidate"] else {"eb": 0.0, "prob": 0.0}
        rec["lambda"] = lam
        for key in ("eb", "prob"):
            bps, ok = mix_bps(ctx, w_h, w_o, lam[key])
            allocs["b_" + key] = bps
            rec["feasible_b_" + key] = ok
        for m in MARGINS:
            take = bool(lam.get("_q05", -1.0) > m and lam.get("_d", 0) > 0)
            allocs[f"d_{m:g}"] = dict(r["candidate"] if take else r["anchor"])
        allocs["house"] = dict(r["anchor"])
        allocs["opt"] = dict(r["candidate"])
    for k in KAPPAS:
        rc = run_prior(name, scale, kappa=k, seed=seed)
        allocs[f"c_{k:g}"] = rc["final"]
        rec[f"elapsed_ms_c_{k:g}"] = rc["elapsed_ms"]
    rec["eval"] = evaluate_set(ctx, name, allocs, oos_cache)
    rec["wall_s"] = round(time.time() - t0, 1)
    return rec


def main():
    mode, name = sys.argv[1], sys.argv[2]
    oos_cache: dict = {}
    if mode == "sweep":
        fixed = len(sys.argv) > 3 and sys.argv[3] == "fixed"
        path = os.path.join(OUT, f"sweep_{name}{'_fixed' if fixed else ''}.jsonl")
        scales = [round(0.80 + 0.01 * i, 2) for i in range(41)]
        seed = _seed_of(name, "fixed-seed") if fixed else None
        jobs = [(s, seed) for s in scales]
    else:
        path = os.path.join(OUT, f"seeds_{name}.jsonl")
        jobs = [(s, _seed_of(name, s, k)) for s in (0.9, 1.0, 1.1) for k in range(6)]
    with open(path, "w", encoding="utf-8") as fh:
        for scale, seed in jobs:
            rec = one_point(name, scale, seed, oos_cache)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(name, scale, rec["decision"], rec["wall_s"], flush=True)


if __name__ == "__main__":
    main()
