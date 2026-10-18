"""Ergaenzung zu exp_misspec.py: kappa_h = 300 (und 30) auf denselben Welten."""
import json, os, sys
from dataclasses import replace
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from exp_main import OUT, evaluate_set
from exp_common import S, _seed_of, run_prior, build_inputs
T_EST, K = 20, 10
name, scale = sys.argv[1], float(sys.argv[2])
true_ctx = S.build_optimizer_context(**build_inputs(name, scale))
cov = np.asarray(true_ctx.scenario_cov_bps2, dtype=float)
L = np.linalg.cholesky(cov / T_EST + 1e-9 * np.eye(5))
orig = S.scenario_inputs_from_cma
cache = {}
with open(os.path.join(OUT, f"mis300_{name}_{scale:.2f}.jsonl"), "w", encoding="utf-8") as fh:
    for k in range(K):
        rng = np.random.default_rng(_seed_of(name, "misspec", k))
        shift = L @ rng.standard_normal(5)
        def patched(*a, **kw):
            inp = orig(*a, **kw)
            mu = np.asarray(inp.mu_bps, dtype=float) + shift
            return replace(inp, mu_bps=np.round(mu).astype(np.asarray(inp.mu_bps).dtype))
        S.scenario_inputs_from_cma = patched
        try:
            allocs = {}
            for kap in (30.0, 300.0):
                r = run_prior(name, scale, kappa=kap)
                allocs.setdefault("a", r["anchor"])
                allocs[f"c_{kap:g}"] = r["final"]
        finally:
            S.scenario_inputs_from_cma = orig
        ev = evaluate_set(true_ctx, name, allocs, cache)
        fh.write(json.dumps(dict(mandate=name, scale=scale, world=k, eval=ev)) + "\n"); fh.flush()
