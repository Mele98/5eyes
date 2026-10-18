"""kappa-Raster und Schaetzfehler-(Misspec-)Auswertung."""
import glob, json, os
from collections import defaultdict
import numpy as np
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
B = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
def w(b): return np.array([b[k] / 100 for k in B])
def to(a, b): return 0.5 * float(np.abs(w(a) - w(b)).sum())
def rows(p):
    out = []
    for f in sorted(glob.glob(os.path.join(OUT, p))):
        out += [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
    return out
# kappa grid (+ 100/1000 aus Haupt-Sweep auf denselben Skalen)
main = {(r["mandate"], r["scale"]): r for r in rows("sweep_*.jsonl") if r["seed"] is None}
kr = rows("kappa_*.jsonl")
by = defaultdict(list)
for r in kr:
    m = main.get((r["mandate"], r["scale"]))
    if m:
        for k in ("c_100", "c_1000", "a", "opt"):
            r["eval"]["x_" + k] = m["eval"][k]
    by[r["mandate"]].append(r)
print("=== kappa-Raster (2 %-Schritte, Inhalts-Seed): maxTO je 2 %, mittl. Abstand zur Hausquote (TO pp), OOS-Zielebene (nominal), Welt-Zielebene ===")
keys = ["c_10", "c_30", "x_c_100", "c_300", "x_c_1000", "c_3000", "x_a", "x_opt"]
agg = defaultdict(lambda: defaultdict(list))
for m, rs in sorted(by.items()):
    rs.sort(key=lambda r: r["scale"])
    for k in keys:
        seq = [r["eval"].get(k) for r in rs]
        if any(s is None for s in seq): continue
        j = [to(seq[i]["bps"], seq[i+1]["bps"]) for i in range(len(seq)-1)]
        dist = [to(s["bps"], r["eval"]["a"]["bps"]) for s, r in zip(seq, rs)]
        og = np.mean([s["oos_goal"] for s in seq]); wg = np.mean([s["world_goal"] for s in seq])
        agg[k]["mx"].append(max(j)); agg[k]["dist"].append(np.mean(dist)); agg[k]["og"].append(og); agg[k]["wg"].append(wg)
        print(f"{m:13s} {k:9s} maxTO {max(j):5.1f} dist {np.mean(dist):5.1f} OOS {og:.4f} world {wg:.4f}")
print("--- Aggregat kappa ---")
for k in keys:
    a = agg[k]
    if a: print(f"{k:9s} maxTO max {max(a['mx']):5.1f} mean {np.mean(a['mx']):4.1f}  dist {np.mean(a['dist']):4.1f}  OOS {np.mean(a['og']):.4f}  world {np.mean(a['wg']):.4f}")
ms = defaultdict(list)
for r in [r for r in kr]:
    for k, v in r["ms"].items(): ms[k].append(v)
for k, v in ms.items(): print(f"elapsed {k}: median {np.median(v):.0f} max {max(v)}")
# Misspec
mr = rows("misspec_*.jsonl")
print("\n=== Schaetzfehler-Test: Engine sieht mu_hat (T=20), Bewertung unter wahrer CMA (20k Pfade) ===")
V = ("a", "b_eb", "b_prob", "d_0.001", "d_0.005", "c_100", "c_1000", "house", "opt")
g = defaultdict(lambda: defaultdict(list))
for r in mr:
    key = (r["mandate"], r["scale"])
    best = min(r["eval"][v]["oos_goal"] for v in V if v in r["eval"])
    for v in V:
        if v in r["eval"]:
            g[key][v].append((r["eval"][v]["oos_goal"], r["eval"][v]["oos_prob"], r["eval"][v]["bps"]["equities"] / 100))
    g[key]["dec"].append(r["decision"][0].upper())
tot = defaultdict(list); totp = defaultdict(list); sde = defaultdict(list)
for key, d in sorted(g.items()):
    line = f"{key[0]:13s} {key[1]:.1f} [{''.join(d['dec'])}]"
    for v in V:
        if d[v]:
            x = np.array(d[v]); line += f" | {v} {x[:,0].mean():.4f}/{x[:,2].std(ddof=1):4.1f}"
            tot[v].append(x[:,0].mean()); totp[v].append(x[:,1].mean()); sde[v].append(x[:,2].std(ddof=1))
    print(line)
print("--- Aggregat Misspec (Mittel ueber 15 Mandat/Skala-Zellen x 10 Welten): wahre Zielebene, wahre P(Ziel), Std Aktienquote ueber Welten ---")
for v in V:
    if tot[v]: print(f"{v:8s} goal {np.mean(tot[v]):.5f} (vs a {np.mean(tot[v]) - np.mean(tot['a']):+.5f})  P {np.mean(totp[v]) * 100:5.2f}%  sdEq {np.mean(sde[v]):4.2f}")
# kappa 30/300 Misspec
m3 = rows("mis300_*.jsonl")
mm = {(r["mandate"], r["scale"], r["world"]): r for r in mr}
acc = defaultdict(list); pp = defaultdict(list); eqs = defaultdict(lambda: defaultdict(list))
for r in m3:
    base = mm.get((r["mandate"], r["scale"], r["world"]))
    if not base: continue
    for k in ("c_30", "c_300"):
        acc[k].append(r["eval"][k]["oos_goal"] - base["eval"]["a"]["oos_goal"]); pp[k].append(r["eval"][k]["oos_prob"] - base["eval"]["a"]["oos_prob"])
        eqs[k][(r["mandate"], r["scale"])].append(r["eval"][k]["bps"]["equities"] / 100)
    for k in ("c_100", "c_1000", "house", "opt"):
        acc[k].append(base["eval"][k]["oos_goal"] - base["eval"]["a"]["oos_goal"]); pp[k].append(base["eval"][k]["oos_prob"] - base["eval"]["a"]["oos_prob"])
print("\n=== Misspec, gepaart mit (a) je Welt (n=150) ===")
for k in ("c_30", "c_100", "c_300", "c_1000", "house", "opt"):
    x = np.array(acc[k]); y = np.array(pp[k])
    sd = "" if k not in eqs else f" sdEq {np.mean([np.std(v, ddof=1) for v in eqs[k].values()]):.2f}"
    print(f"{k:7s} dGoal {x.mean():+.5f} (se {x.std(ddof=1)/np.sqrt(len(x)):.5f}, besser in {np.mean(x < 0)*100:4.1f}% der Welten)  dP {y.mean()*100:+.2f}pp (se {y.std(ddof=1)/np.sqrt(len(y))*100:.2f}){sd}")
