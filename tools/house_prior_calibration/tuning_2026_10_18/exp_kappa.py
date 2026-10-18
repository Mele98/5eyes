"""kappa_h-Kalibrierung fuer (c): Raster {10,30,100,300,1000,3000}, Skalen 0.80..1.20 (2 %-Schritte), Inhalts-Seed."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exp_main import OUT, evaluate_set
from exp_common import run_prior
name = sys.argv[1]
KS = (10.0, 30.0, 300.0, 3000.0)  # 100/1000 liegen schon im Haupt-Sweep
cache = {}
with open(os.path.join(OUT, f"kappa_{name}.jsonl"), "w", encoding="utf-8") as fh:
    for i in range(21):
        s = round(0.80 + 0.02 * i, 2)
        allocs, ms, ctx = {}, {}, None
        for k in KS:
            r = run_prior(name, s, kappa=k)
            ctx = r["ctx"]
            allocs.setdefault("a", r["anchor"])
            allocs[f"c_{k:g}"] = r["final"]
            ms[f"c_{k:g}"] = r["elapsed_ms"]
        ev = evaluate_set(ctx, name, allocs, cache)
        fh.write(json.dumps(dict(mandate=name, scale=s, eval=ev, ms=ms)) + "\n"); fh.flush()
        print(name, s, flush=True)
