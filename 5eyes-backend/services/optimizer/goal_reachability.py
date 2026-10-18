"""Ist ein Ziel auf IRGENDEINER zulaessigen Allokation erreichbar?

GOAL-REACHABILITY-SCREEN-001 (CIO-Entscheid 2026-10-18)
=======================================================

Befund (OBJECTIVE-NORMALIZATION-001, Owner-Frage 1): auf dem Fundament-Mandat
entschied in den Risikomass-Varianten zu 76 % ein Ziel ueber die
Chance-Strafe, das auf keiner zulaessigen Allokation erreichbar ist
(Vermoegensziel CHF 5.78 Mio, Wahrscheinlichkeit 1.7-2.9 % gegen tau = 80 %).
Ein solches Ziel kann zwischen zulaessigen Allokationen nur noch ueber sein
Rauschen entscheiden: sein Defizit bleibt auf jeder Allokation bestehen.

Definition
----------
Pruefmenge ``K`` zulaessiger Allokationen:

* alle Ecken des Bandbreiten-Simplex ``{lo <= w <= hi, sum w = 1}`` (Punkte,
  an denen hoechstens ein Bucket strikt zwischen seinen Grenzen liegt) --
  verletzt eine Ecke weitere harte Nebenbedingungen (Risikobudget), wird sie
  euklidisch auf die zulaessige Menge projiziert;
* die Multi-Start-Punkte des Solvers (Bandmitte, konservativ, aggressiv,
  Risikobudget-Kante, Markowitz-Minimum-Varianz, ...).

Bewertet wird auf dem NOMINALEN, unabhaengigen Validierungswuerfel (kein
Importance Sampling, eigener Seed) mit genau der Erfolgsdefinition der
Chance-Strafe (``_goal_probability_core``, gemeinsamer Pfad). Ein Ziel mit
Ziel-Untergrenze (Haertegrad hart/primaer, nicht ``maximize``, nicht
ausserhalb des Horizonts) heisst **praktisch unerreichbar**, wenn

    max_{w in K}  UB_95(p_hat_g(w), N)  <  UNREACHABLE_TAU_FRACTION * tau_g

mit ``UNREACHABLE_TAU_FRACTION = 0.5`` (CIO-Entscheid 2026-10-18): selbst
die obere einseitige 95 %-Wilson-Grenze der guenstigsten gepruften
Allokation erreicht nicht die HALBE geforderte Sicherheit. Ein Ziel, das
mehr als die halbe Sicherheit erreichen kann (Fundament: Einkommensbruecke,
max 54 % gegen tau 80 %), bleibt entscheidungsrelevant und steuert weiter;
nur praktisch aussichtslose Ziele (Familienvermoegen 2035, max ~5 %) werden
ausgenommen. Die Pruefmenge ist eine Ueberdeckung, kein Beweis: das Maximum
kann im Inneren liegen. Obergrenze statt Punktschaetzer, die halbe Schwelle
und die Multi-Start-Punkte (die das Innere abdecken) halten die Regel
konservativ: im Zweifel steuert ein Ziel weiter.

Wirkung (JEDER Modus, CIO-Entscheid 2026-10-18)
------------------------------------------------
* Ein praktisch unerreichbares Ziel steuert weder die Chance-Strafe noch
  (Modus ``goal_shortfall``) den Primaerterm
  (``OptimizerContext.penalty_exempt_goal_ids``). Begruendung: sein
  Fehlbetrag bleibt auf JEDER zulaessigen Allokation bestehen; als Zielterm
  wuerde er die Allokation nur in mehr Risiko treiben ("Hoffen auf ein
  Wunder") -- gegen den Kapitalschutz und auf Kosten der erreichbaren Ziele.
  Gemessen auf dem Fundament-Mandat dominierte es den Primaerterm
  (Z/W0 = 2.68).
* Bags, Signifikanztest und Drawdown-Rerank erben die Ausnahme ueber den
  Context (eine Zielfunktion).
* Offenlegung: ``OptimizerResult.goal_reachability``, ein Beraterhinweis je
  Ziel im Reasoning ("Ziel mit dem Kunden ueberpruefen") und
  ``feasible_set_reachable`` auf den publizierten Zeilen der geprueften
  Ziele. Die Zielwahrscheinlichkeit selbst wird weiter publiziert.
"""
from __future__ import annotations

import itertools

import numpy as np

from .certification import wilson_upper_bound

GOAL_REACHABILITY_SCREEN_VERSION = "goal_reachability_screen_v2"
# Ein Ziel gilt als praktisch unerreichbar, wenn die obere 95 %-Grenze seiner
# besten zulaessigen Erfolgswahrscheinlichkeit unter diesem Anteil seiner
# geforderten Sicherheit tau liegt (CIO-Entscheid 2026-10-18).
UNREACHABLE_TAU_FRACTION = 0.5


def _box_simplex_vertices(bounds) -> list[np.ndarray]:
    lo = np.array([float(b[0]) for b in bounds], dtype=np.float64)
    hi = np.array([float(b[1]) for b in bounds], dtype=np.float64)
    n = lo.size
    vertices: list[np.ndarray] = []
    for free in range(n):
        others = [i for i in range(n) if i != free]
        for pattern in itertools.product((0, 1), repeat=len(others)):
            w = np.empty(n, dtype=np.float64)
            for index, upper in zip(others, pattern):
                w[index] = hi[index] if upper else lo[index]
            w[free] = 1.0 - float(np.sum(w[others]))
            if lo[free] - 1e-12 <= w[free] <= hi[free] + 1e-12:
                w[free] = min(max(w[free], lo[free]), hi[free])
                vertices.append(w)
    return vertices


def candidate_allocations(context) -> list[np.ndarray]:
    """Pruefmenge K (siehe Modul-Docstring), dedupliziert auf 1 bps."""
    from . import solver as _solver
    from .constraints import is_feasible

    raw = list(_solver.build_initial_guesses(
        context.bounds,
        context.score_x10,
        mu_bps=context.scenario_mu_bps,
        cov_bps=context.scenario_cov_bps2,
        risky_fraction_per_bucket=context.risky_fraction_per_bucket,
    ))
    raw.extend(_box_simplex_vertices(context.bounds))
    seen: set[tuple[int, ...]] = set()
    candidates: list[np.ndarray] = []
    for w in raw:
        w = np.asarray(w, dtype=np.float64)
        ok, _violations = is_feasible(
            w, bounds=context.bounds, constraints=context.scipy_constraints,
        )
        if not ok:
            projected = _solver._project_onto_feasible_set(w, context)
            if projected is None:
                continue
            w = projected
        key = tuple(int(round(x * 10000.0)) for x in w)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(w)
    return candidates


def _screened_goals(context, n_wealth_columns: int) -> list:
    from .objective import (
        _PRIMARY_HARDNESS_KEYS,
        _hardness_key,
        scheduled_outside_wealth_horizon,
    )

    goals = []
    for goal in context.liabilities:
        hardness = _hardness_key(getattr(goal, "hardness_key", None))
        if hardness not in _PRIMARY_HARDNESS_KEYS or goal.target_kind == "maximize":
            continue
        if goal.target_kind in ("cashflow_in_year", "outflow_stream") and (
            scheduled_outside_wealth_horizon(goal, n_wealth_columns=n_wealth_columns)
        ):
            continue
        goals.append(goal)
    return goals


def goal_reachability_screen(context) -> dict | None:
    """Fuehrt die Pruefung aus. None ohne pruefbare Ziele oder Validierungswuerfel."""
    from . import solver as _solver
    from .objective import _default_tau_x100, _goal_probability_core
    from .objective_contract import objective_contract_of

    goals = _screened_goals(context, int(context.horizon_years) + 1)
    if not goals:
        return None
    validation = _solver._build_validation_context(context)
    if validation is None:
        return None
    validation_context, validation_seed, cube_hash = validation
    n_paths = int(validation_context.n_paths)
    candidates = candidate_allocations(context)
    state = {
        str(goal.goal_id): {
            "goal": goal,
            "tau": _default_tau_x100(goal) / 10000.0,
            "max_probability": 0.0,
            "max_upper_bound": 0.0,
            "best_candidate_bps": None,
            "reachable": False,
        }
        for goal in goals
    }
    evaluated = 0
    for w in candidates:
        open_ids = [gid for gid, row in state.items() if not row["reachable"]]
        if not open_ids:
            break
        evaluated += 1
        wealth = _solver._simulate_context_wealth(validation_context, w)
        annualized = _solver._annualized_twr_bps_per_path(validation_context, w)
        for gid in open_ids:
            row = state[gid]
            success = _goal_probability_core(
                wealth,
                row["goal"],
                validation_context.advisory_wealth_rappen,
                annualized_return_bps_per_path=annualized,
            )
            probability = float(np.mean(success)) if success.size else 0.0
            upper = wilson_upper_bound(probability, n_paths)
            if row["best_candidate_bps"] is None or probability > row["max_probability"]:
                row["max_probability"] = probability
                row["best_candidate_bps"] = [
                    int(round(x * 10000.0)) for x in np.asarray(w, dtype=np.float64)
                ]
            row["max_upper_bound"] = max(row["max_upper_bound"], upper)
            if upper >= UNREACHABLE_TAU_FRACTION * row["tau"]:
                row["reachable"] = True

    unreachable = sorted(gid for gid, row in state.items() if not row["reachable"])
    mode = objective_contract_of(context).objective_mode
    exempt = list(unreachable)
    return {
        "version": GOAL_REACHABILITY_SCREEN_VERSION,
        "objective_mode": mode,
        "validation_seed": int(validation_seed),
        "validation_cube_hash": cube_hash,
        "validation_n_paths": n_paths,
        "n_candidates": len(candidates),
        "n_candidates_evaluated": evaluated,
        "unreachable_tau_fraction": UNREACHABLE_TAU_FRACTION,
        "goals": [
            {
                "goal_id": gid,
                "label": str(row["goal"].label),
                "tau": row["tau"],
                "max_probability": row["max_probability"],
                "max_upper_bound": row["max_upper_bound"],
                "best_candidate_bps": row["best_candidate_bps"],
                "reachable": bool(row["reachable"]),
            }
            for gid, row in state.items()
        ],
        "unreachable_goal_ids": unreachable,
        "penalty_exempt_goal_ids": exempt,
    }


def reachability_reasoning(screen: dict | None) -> list[str]:
    """Beraterhinweis je praktisch unerreichbarem Ziel."""
    if not screen or not screen.get("unreachable_goal_ids"):
        return []
    lines = []
    for row in screen.get("goals") or ():
        if row.get("reachable"):
            continue
        lines.append(
            "Beraterhinweis: Ziel " + repr(str(row["label"])) + " ist mit keiner "
            "zulaessigen Allokation mit ausreichender Sicherheit erreichbar (max. "
            f"{100.0 * float(row['max_probability']):.1f} %, obere 95 %-Grenze "
            f"{100.0 * float(row['max_upper_bound']):.1f} %, gefordert "
            f"{100.0 * float(row['tau']):.0f} %). Ziel mit dem Kunden "
            "ueberpruefen (Betrag, Termin, Prioritaet). Die Allokation wird "
            "nicht auf dieses Ziel optimiert (kein zusaetzliches Risiko fuer "
            "ein aussichtsloses Ziel)."
        )
    return lines


def annotate_rows(rows, screen: dict | None) -> list[dict]:
    """Setzt ``feasible_set_reachable`` (bool) auf jeder GEPRUEFTEN Zielzeile."""
    verdict = {
        str(row["goal_id"]): bool(row["reachable"])
        for row in ((screen or {}).get("goals") or ())
    }
    out = []
    for row in rows:
        row = dict(row)
        goal_id = row.get("goal_id")
        # Nur gepruefte Ziele (Untergrenze, im Horizont) bekommen das Feld;
        # alle anderen Zeilen bleiben unveraendert.
        if goal_id is not None and str(goal_id) in verdict:
            row["feasible_set_reachable"] = verdict[str(goal_id)]
        out.append(row)
    return out
