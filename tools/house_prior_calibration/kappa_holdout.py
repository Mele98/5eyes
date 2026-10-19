"""Unberuehrter Holdout-Test fuer kappa_H (HOUSE-PRIOR-CALIBRATION-PROVENANCE-001).

Das Tuning vom 2026-10-18 (``tuning_2026_10_18/``) hat kappa_H = 300 auf den
Schaetzfehler-Welten ``seed_of(mandat, "misspec", k)`` ausgewaehlt -- post hoc,
ohne vorab registrierte Regel. Dieser Lauf prueft die Wahl auf NEUEN Welten
(Seed-Domaene ``kappa-holdout-v1``), die das Tuning nie gesehen hat, mit der
Produktions-Engine (``saa_resampled_v7``: Ridge-Prior, 40 Bags x 500 Pfade).

Vorab festgelegt (vor dem ersten Lauf, commitgebunden in diesem Skript):

* Kandidaten: kappa_H in {100, 300, 1000}; Referenz: projizierte Hausquote.
* Welten: 5 Mandate x Zielbetrag-Skalen {0.90, 1.00, 1.10} x K = 10 Welten.
  Die Engine sieht ``mu_hat = mu + L z / sqrt(T_EST)``, ``T_EST = 20``
  (Schaetzfehler des Mittels aus 20 Jahresbeobachtungen, ``L L' = Sigma``).
* Bewertung unter der WAHREN CMA auf einem nominalen 20'000-Pfade-Wuerfel
  (antithetisch, Seed-Domaene ``kappa-holdout-oos-v1``): Zielebene
  (Ziel-Fehlbetrag + Chance-Strafe) und Zielwahrscheinlichkeit.
* Primaerer Endpunkt: Delta P(Ziel) = P(kappa) - P(Haus), gepaart je Welt
  (n = 150). Sekundaer: Delta Zielebene.
* Regel R1 (kein Schaden ggue. Haus): untere einseitige 95-%-Grenze von
  mean Delta P(kappa = 300) > 0  (t-Grenze, Standardfehler ueber Welten).
* Regel R2 (kappa nicht dominiert): mean Delta P(300) >=
  max(mean Delta P(100), mean Delta P(1000)) - 1 * se der gepaarten Differenz.
* Entscheid: "confirmed" genau dann, wenn R1 und R2; sonst
  "not_confirmed" -- dann KEINE automatische Aenderung, Modellowner entscheidet.

Aufruf (eine Mandat-Zeile je Prozess, parallelisierbar)::

    python tools/house_prior_calibration/kappa_holdout.py run A_ausg_spar OUT_DIR
    python tools/house_prior_calibration/kappa_holdout.py summarize OUT_DIR

``OUT_DIR`` z.B. ``docs/planning/2026-10-18-house-prior-kappa-calibration``.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibration_common import (  # noqa: E402
    MANDATES,
    VALUATION_YEAR,
    bps_to_w,
    build_inputs,
    seed_of,
    sha256_file,
)

import numpy as np  # noqa: E402

from services.optimizer import solver as S  # noqa: E402
from services.optimizer.objective import goal_probability_per_path  # noqa: E402
from services.optimizer.scenario_engine import build_scenario_paths  # noqa: E402

KAPPAS = (100.0, 300.0, 1000.0)
SCALES = (0.90, 1.00, 1.10)
K_WORLDS = 10
T_EST = 20
N_OOS = 20_000
WORLD_DOMAIN = "kappa-holdout-v1"
OOS_DOMAIN = "kappa-holdout-oos-v1"


def _run_with_kappa(inputs: dict, kappa: float):
    original = S.HOUSE_PRIOR_KAPPA
    S.HOUSE_PRIOR_KAPPA = float(kappa)
    try:
        result = S.run_solver(**inputs)
    finally:
        S.HOUSE_PRIOR_KAPPA = original
    prior = (result.resampling or {}).get("house_prior") or {}
    return result, prior


def _evaluate(true_ctx, oos_paths, allocations: dict) -> dict:
    vctx = replace(
        true_ctx, return_paths=oos_paths, scenario_weights=None, n_paths=N_OOS,
    )
    reference = bps_to_w(allocations["house"])
    out = {}
    for key, bps in allocations.items():
        w = bps_to_w(bps)
        pair = S._context_loss_components_on_validation(
            vctx, reference, w, validation_seed=None,
        )
        (_g0, _r0), (goal_level, _risk) = pair(None)
        wealth = S._simulate_context_wealth(vctx, w)
        probability = float(np.mean(goal_probability_per_path(
            wealth, vctx.liabilities[0], vctx.advisory_wealth_rappen,
        )))
        out[key] = {"bps": dict(bps), "goal_level": float(goal_level),
                    "probability": probability}
    return out


def run(mandate: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"holdout_{mandate}.jsonl"
    original_inputs = S.scenario_inputs_from_cma
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for scale in SCALES:
            inputs = build_inputs(mandate, scale)
            true_ctx = S.build_optimizer_context(**inputs)
            horizon = int(true_ctx.scenario_horizon_years or true_ctx.horizon_years)
            oos_paths = build_scenario_paths(
                true_ctx.scenario_inputs, horizon_years=horizon, n_paths=N_OOS,
                seed=seed_of(mandate, OOS_DOMAIN, f"{scale:.2f}"), antithetic=True,
            )[:, : int(true_ctx.horizon_years), :]
            cov = np.asarray(true_ctx.scenario_cov_bps2, dtype=np.float64)
            chol = np.linalg.cholesky(cov / T_EST + 1e-9 * np.eye(cov.shape[0]))
            for world in range(K_WORLDS):
                rng = np.random.default_rng(seed_of(mandate, WORLD_DOMAIN, f"{scale:.2f}", world))
                shift = chol @ rng.standard_normal(cov.shape[0])

                def patched(*args, _shift=shift, **kwargs):
                    base = original_inputs(*args, **kwargs)
                    mu = np.asarray(base.mu_bps, dtype=np.float64) + _shift
                    return replace(base, mu_bps=np.round(mu).astype(np.asarray(base.mu_bps).dtype))

                S.scenario_inputs_from_cma = patched
                allocations: dict = {}
                meta: dict = {}
                try:
                    for kappa in KAPPAS:
                        result, prior = _run_with_kappa(inputs, kappa)
                        allocations[f"kappa_{kappa:g}"] = dict(result.weights_bps)
                        allocations.setdefault("house", dict(prior["house_anchor_projected_bps"]))
                        # Keine Laufzeiten im Rohresultat: die JSONL ist
                        # damit byte-reproduzierbar (Laufzeit -> stderr).
                        meta[f"kappa_{kappa:g}"] = {
                            "decision": prior.get("decision"),
                            "engine_version": result.resampling.get("engine_version"),
                        }
                        print(
                            f"  kappa={kappa:g} {result.resampling.get('elapsed_ms')} ms",
                            file=sys.stderr,
                        )
                finally:
                    S.scenario_inputs_from_cma = original_inputs
                record = {
                    "mandate": mandate, "scale": scale, "world": world,
                    "shift_bps": [round(float(x), 6) for x in shift],
                    "meta": meta,
                    "eval": _evaluate(true_ctx, oos_paths, allocations),
                }
                fh.write(json.dumps(record, sort_keys=True) + "\n")
                fh.flush()
                print(mandate, scale, world, flush=True)


def _mean_se(values) -> tuple[float, float]:
    x = np.asarray(values, dtype=np.float64)
    return float(x.mean()), float(x.std(ddof=1) / math.sqrt(x.size))


def summarize(out_dir: Path) -> dict:
    from scipy.stats import t as student_t

    rows = []
    for mandate in MANDATES:
        path = out_dir / f"holdout_{mandate}.jsonl"
        with open(path, encoding="utf-8") as fh:
            rows += [json.loads(line) for line in fh if line.strip()]
    n = len(rows)
    keys = [f"kappa_{k:g}" for k in KAPPAS]
    delta_p = {k: [r["eval"][k]["probability"] - r["eval"]["house"]["probability"] for r in rows] for k in keys}
    delta_g = {k: [r["eval"][k]["goal_level"] - r["eval"]["house"]["goal_level"] for r in rows] for k in keys}
    stats = {}
    for k in keys:
        mp, sp = _mean_se(delta_p[k])
        mg, sg = _mean_se(delta_g[k])
        stats[k] = {
            "mean_delta_probability_pp": round(100 * mp, 4),
            "se_delta_probability_pp": round(100 * sp, 4),
            "mean_delta_goal_level": round(mg, 6),
            "se_delta_goal_level": round(sg, 6),
            "share_worlds_probability_better": round(float(np.mean(np.asarray(delta_p[k]) > 0)), 4),
            "share_worlds_probability_worse": round(float(np.mean(np.asarray(delta_p[k]) < 0)), 4),
        }
    t95 = float(student_t.ppf(0.95, n - 1))
    m300, s300 = _mean_se(delta_p["kappa_300"])
    r1_lower = m300 - t95 * s300
    neighbours = {}
    for k in ("kappa_100", "kappa_1000"):
        diff = np.asarray(delta_p["kappa_300"]) - np.asarray(delta_p[k])
        md, sd = _mean_se(diff)
        neighbours[k] = {"mean_diff_pp": round(100 * md, 4), "se_diff_pp": round(100 * sd, 4),
                         "r2_ok": bool(md >= -sd)}
    r1 = bool(r1_lower > 0.0)
    r2 = all(v["r2_ok"] for v in neighbours.values())
    summary = {
        "n_worlds": n,
        "valuation_year": VALUATION_YEAR,
        "kappas": list(KAPPAS),
        "stats_vs_house": stats,
        "rule_r1": {"lower_95_one_sided_pp": round(100 * r1_lower, 4), "ok": r1},
        "rule_r2": neighbours | {"ok": r2},
        "decision": "confirmed" if (r1 and r2) else "not_confirmed",
        "raw_sha256": {
            f"holdout_{m}.jsonl": sha256_file(out_dir / f"holdout_{m}.jsonl") for m in MANDATES
        },
    }
    with open(out_dir / "holdout_summary.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return summary


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "run":
        run(sys.argv[2], Path(sys.argv[3]))
    elif mode == "summarize":
        print(json.dumps(summarize(Path(sys.argv[2])), indent=2))
    else:
        raise SystemExit(__doc__)
