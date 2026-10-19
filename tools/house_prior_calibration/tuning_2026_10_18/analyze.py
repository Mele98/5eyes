"""Auswertung der JSONL-Ergebnisse von exp_main.py."""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import defaultdict

import numpy as np

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
BUCKETS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
VARIANTS = ("a", "b_eb", "b_prob", "d_0.001", "d_0.005", "c_100", "c_1000", "house", "opt")


def load(pattern):
    rows = []
    for f in sorted(glob.glob(os.path.join(OUT, pattern))):
        with open(f, encoding="utf-8") as fh:
            rows += [json.loads(line) for line in fh if line.strip()]
    return rows


def w(bps):
    return np.array([bps[b] / 100.0 for b in BUCKETS])


def turnover(b1, b2):
    return 0.5 * float(np.sum(np.abs(w(b1) - w(b2))))


def sweep_table(rows, label):
    by_m = defaultdict(list)
    for r in rows:
        by_m[r["mandate"]].append(r)
    print(f"\n=== Sweep {label}: Sprung bei +1 % Zielbetrag (pp, Turnover = 1/2 L1) ===")
    agg = defaultdict(lambda: defaultdict(list))
    for m, rs in sorted(by_m.items()):
        rs.sort(key=lambda r: r["scale"])
        dec = "".join({"optimizer": "O", "house_matrix": "H"}.get(r["decision"], "?") for r in rs)
        print(f"{m}: decisions {dec}")
        for v in VARIANTS:
            seq = [r["eval"].get(v, {}).get("bps") for r in rs]
            if any(s is None for s in seq):
                continue
            jumps = [turnover(seq[i], seq[i + 1]) for i in range(len(seq) - 1)]
            eqj = [abs(seq[i]["equities"] - seq[i + 1]["equities"]) / 100 for i in range(len(seq) - 1)]
            og = [r["eval"][v]["oos_goal"] for r in rs]
            wg = [r["eval"][v]["world_goal"] for r in rs]
            op = [r["eval"][v]["oos_prob"] for r in rs]
            wp = [r["eval"][v]["world_prob"] for r in rs]
            ref_og = [r["eval"]["a"]["oos_goal"] for r in rs]
            ref_wg = [r["eval"]["a"]["world_goal"] for r in rs]
            agg[v]["max_to"].append(max(jumps))
            agg[v]["mean_to"].append(float(np.mean(jumps)))
            agg[v]["n_big"].append(sum(j > 2.0 for j in jumps))
            agg[v]["max_eq"].append(max(eqj))
            agg[v]["d_oos"].append(float(np.mean(np.array(og) - np.array(ref_og))))
            agg[v]["d_world"].append(float(np.mean(np.array(wg) - np.array(ref_wg))))
            agg[v]["oos_prob"].append(float(np.mean(op)))
            agg[v]["world_prob"].append(float(np.mean(wp)))
            print(f"  {v:8s} maxTO {max(jumps):5.1f}  meanTO {np.mean(jumps):4.2f}  #TO>2pp {sum(j > 2.0 for j in jumps):2d}"
                  f"  maxdEq {max(eqj):5.1f}  OOS-goal {np.mean(og):.4f} (vs a {np.mean(og) - np.mean(ref_og):+.5f})"
                  f"  world-goal {np.mean(wg):.4f} ({np.mean(wg) - np.mean(ref_wg):+.5f})"
                  f"  P_oos {np.mean(op) * 100:5.2f}%  P_world {np.mean(wp) * 100:5.2f}%")
    print(f"\n--- Aggregat {label} (Mittel ueber Mandate) ---")
    for v in VARIANTS:
        if v not in agg:
            continue
        a = agg[v]
        print(f"  {v:8s} maxTO(max) {max(a['max_to']):5.1f}  maxTO(mean) {np.mean(a['max_to']):5.1f}  meanTO {np.mean(a['mean_to']):4.2f}"
              f"  #TO>2pp {sum(a['n_big']):3d}  dOOS {np.mean(a['d_oos']):+.5f}  dWorld {np.mean(a['d_world']):+.5f}"
              f"  P_oos {np.mean(a['oos_prob']) * 100:5.2f}%  P_world {np.mean(a['world_prob']) * 100:5.2f}%")


def seeds_table(rows):
    print("\n=== Seed-Stabilitaet: 6 Seeds je (Mandat, Skala); Std Aktien (pp), mittl. paarweiser Turnover (pp) ===")
    groups = defaultdict(list)
    for r in rows:
        groups[(r["mandate"], r["scale"])].append(r)
    agg = defaultdict(lambda: defaultdict(list))
    for key, rs in sorted(groups.items()):
        dec = "".join({"optimizer": "O", "house_matrix": "H"}.get(r["decision"], "?") for r in rs)
        line = f"{key[0]} {key[1]:.2f} [{dec}]"
        for v in VARIANTS:
            seq = [r["eval"].get(v, {}).get("bps") for r in rs]
            if any(s is None for s in seq):
                continue
            eqs = [s["equities"] / 100 for s in seq]
            pt = [turnover(seq[i], seq[j]) for i in range(len(seq)) for j in range(i + 1, len(seq))]
            og = [r["eval"][v]["oos_goal"] for r in rs]
            agg[v]["sd_eq"].append(float(np.std(eqs, ddof=1)))
            agg[v]["pt"].append(float(np.mean(pt)))
            agg[v]["og"].append(float(np.mean(og)))
            agg[v]["wg"].append(float(np.mean([r["eval"][v]["world_goal"] for r in rs])))
            line += f" | {v} {np.std(eqs, ddof=1):4.1f}/{np.mean(pt):4.1f}"
        print(line)
    print("--- Aggregat Seeds ---")
    for v in VARIANTS:
        if v not in agg:
            continue
        a = agg[v]
        print(f"  {v:8s} sdEq mean {np.mean(a['sd_eq']):4.2f} max {max(a['sd_eq']):4.2f}  pairTO mean {np.mean(a['pt']):4.2f} max {max(a['pt']):4.2f}"
              f"  OOS-goal {np.mean(a['og']):.4f}  world-goal {np.mean(a['wg']):.4f}")


def timing(rows):
    print("\n=== Laufzeit elapsed_ms (unter Parallel-Last gemessen) ===")
    for k in ("elapsed_ms_a", "elapsed_ms_c_100", "elapsed_ms_c_1000"):
        v = [r[k] for r in rows if r.get(k) is not None]
        if v:
            print(f"  {k}: median {np.median(v):.0f}  p95 {np.quantile(v, 0.95):.0f}  max {max(v)}")


def lambdas(rows):
    print("\n=== lambda-Verteilung (b) ===")
    for k in ("eb", "prob"):
        v = [r["lambda"][k] for r in rows if r.get("lambda")]
        print(f"  {k}: n {len(v)}  =0: {sum(x == 0 for x in v)}  in (0,1): {sum(0 < x < 1 for x in v)}  =1: {sum(x >= 0.999 for x in v)}")
    infeas = sum(1 for r in rows for k in ("feasible_b_eb", "feasible_b_prob") if r.get(k) is False)
    print(f"  unzulaessige Mischpunkte nach Rundung+Reparatur: {infeas}")


if __name__ == "__main__":
    sw = [r for r in load("sweep_*.jsonl") if True]
    content = [r for r in sw if r["seed"] is None]
    fixed = [r for r in sw if r["seed"] is not None]
    if content:
        sweep_table(content, "Inhalts-Seed (Produktion)")
    if fixed:
        sweep_table(fixed, "fester Seed (CRN)")
    sd = load("seeds_*.jsonl")
    if sd:
        seeds_table(sd)
    allr = sw + sd
    timing(allr)
    lambdas(allr)
