"""Michaud-artiger Schaetzfehler-Test: die Engine sieht mu_hat = mu + L z / sqrt(T_EST)
(T_EST = 20 Jahre, Kovarianz Sigma der CMA), bewertet wird unter der WAHREN CMA.
Frage: schuetzt das Haus-Shrinkage gegen CMA-Schaetzfehler?"""
import json, os, sys
from dataclasses import replace
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import exp_common as C
from exp_main import OUT, evaluate_set, lambdas, mix_bps, MARGINS
from exp_common import S, _seed_of, bps_to_w, run, run_prior, build_inputs
T_EST, K = 20, 10
name, scale = sys.argv[1], float(sys.argv[2])
true_ctx = S.build_optimizer_context(**build_inputs(name, scale))
cov = np.asarray(true_ctx.scenario_cov_bps2, dtype=float)  # bps^2
L = np.linalg.cholesky(cov / T_EST + 1e-9 * np.eye(5))
orig = S.scenario_inputs_from_cma
cache = {}
with open(os.path.join(OUT, f"misspec_{name}_{scale:.2f}.jsonl"), "w", encoding="utf-8") as fh:
    for k in range(K):
        rng = np.random.default_rng(_seed_of(name, "misspec", k))
        shift = L @ rng.standard_normal(5)  # bps
        def patched(*a, **kw):
            inp = orig(*a, **kw)
            mu = np.asarray(inp.mu_bps, dtype=float) + shift
            return replace(inp, mu_bps=np.round(mu).astype(np.asarray(inp.mu_bps).dtype))
        S.scenario_inputs_from_cma = patched
        try:
            r = run(name, scale)
            allocs = {"a": dict(r["final"])}
            rec = dict(mandate=name, scale=scale, world=k, shift_bps=shift.tolist(), decision=r["decision"], p=r["p"])
            if r["anchor"] and r["candidate"] and r["decision"] in ("house_matrix", "optimizer"):
                w_h, w_o = bps_to_w(r["anchor"]), bps_to_w(r["candidate"])
                lam = lambdas(r["improvement"], r["reps"]) if r["anchor"] != r["candidate"] else {"eb": 0.0, "prob": 0.0}
                for key in ("eb", "prob"):
                    allocs["b_" + key] = mix_bps(r["ctx"], w_h, w_o, lam[key])[0]
                for m in MARGINS:
                    take = bool(lam.get("_q05", -1) > m and lam.get("_d", 0) > 0)
                    allocs[f"d_{m:g}"] = dict(r["candidate"] if take else r["anchor"])
                allocs["house"], allocs["opt"] = dict(r["anchor"]), dict(r["candidate"])
            for kap in (100.0, 1000.0):
                allocs[f"c_{kap:g}"] = run_prior(name, scale, kappa=kap)["final"]
        finally:
            S.scenario_inputs_from_cma = orig
        rec["eval"] = evaluate_set(true_ctx, name, allocs, cache)
        fh.write(json.dumps(rec) + "\n"); fh.flush()
        print(name, scale, k, rec["decision"], flush=True)
