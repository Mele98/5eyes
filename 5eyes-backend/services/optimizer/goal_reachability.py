"""Ist ein Ziel auf IRGENDEINER zulaessigen Allokation erreichbar?

ENGINE v11 (GOAL-REVISION-DECISION-001, CIO-Entscheid 2026-10-21 nach Codex-
Closure-Review docs/audits/2026-10-20-goal-reachability-certificate-pr655-
closure-review.md): ein lokales Optimum ist kein globaler
Unmoeglichkeitsnachweis. Eine schmale zulaessige Erfolgsinsel zwischen allen
Startpunkten (400/400 erfolgreiche Pfade) wurde von SLSQP verfehlt und das
harte Ziel trotzdem als ``certified_unreachable_on_screen_cube`` aus Stufe 1
herabgestuft. Seit v11:

* die lokale Suche (unveraendert: Multi-Start, Glaettungsfortsetzung,
  exakter Indikator) liefert nur noch ``reachable`` (gefunden) oder
  ``not_found_reachable_locally`` (lokal nicht gefunden, KEIN Beweis);
  ohne zulaessige Menge ``global_certificate_unavailable``. Jeder Zustand
  ausser ``reachable`` ist fail-safe: das Ziel bleibt mit seinem Haertegrad
  in Stufe 1. ``certified_unreachable_goal_ids`` ist immer leer;
* die Engine stuft NIE selbst herab. ``demoted_goal_ids`` sind die Ziele mit
  gueltiger Berater-Entscheidung ``GoalRevisionDecisionV1``
  (services/goal_revision_decision.py, Ziel-Snapshot-Hash passt);
* ein lokaler Such-Miss erzeugt einen Vorschlag (``revision_suggested`` je
  Zielzeile, Beraterhinweis im Reasoning): "Als nachrangiges Wunschziel
  einstufen..." mit Begruendung -> POST erzeugt die Decision;
* die Wilson-Obergrenze ist eine Stichproben-Unsicherheit AM BESTEN
  GEFUNDENEN PUNKT, kein Optimierungs-Bound (Codex 5.2.4).

ENGINE v9 (GOAL-REACHABILITY-CERTIFICATE-001, CIO-Entscheid 2026-10-19 nach
Codex-Review docs/audits/2026-10-19-maximize-goal-hardness-pr650-current-
review.md, Abschnitt 4): ein endlicher Screen-Miss stufte ein hartes Ziel
aus Stufe 1 herab, obwohl eine zulaessige Innenallokation es sicher
erfuellte. Seit v9 entscheidet ueber die Herabstufung (Wunschziel-Gewicht
0.2 + W0-Deckel, nicht Stufe 1) NUR noch ein Zertifikat:

* fuer jedes Ziel, das der guenstige Screen nicht mit ``UB >= tau/2`` findet,
  eine echte Optimierung ``max_w p_glatt_g(w)`` ueber die zulaessige Menge
  (dieselben Bandbreiten, Restriktionen und Risikobudget wie der Solver),
  Multi-Start von ALLEN Screen-Kandidaten und vom Zentrum der zulaessigen
  Menge (Mittel der Kandidaten; die Menge ist konvex), Fortsetzung ueber
  abnehmende Glaettungsbreiten (``CERTIFICATE_WIDTHS``);
* bewertet auf dem eigenen Screening-Wuerfel mit dem EXAKTEN
  Erfolgsindikator an jedem zulaessigen ausgewerteten Punkt;
* ``certified_unreachable_on_screen_cube`` nur, wenn die obere einseitige
  95 %-Wilson-Grenze (Kish-ESS) des besten gefundenen Punktes < tau/2;
  sonst ``reachable`` (das Ziel bleibt Stufe 1). Ohne zulaessige Menge kein
  Zertifikat (``certificate_unavailable``) und damit keine Herabstufung.

``not_found_reachable_goal_ids`` bleibt reine Offenlegung; operativ wirkt
ausschliesslich ``demoted_goal_ids`` (= zertifiziert unerreichbar). Das
Zertifikat ist ein lokales Optimum auf einem Wuerfel, kein globaler
Unmoeglichkeitsnachweis; die Alternative "Herabstufung nur per expliziter,
versionierter GoalRevisionDecision" (Codex 6.1.4) ist dokumentiert, nicht
umgesetzt.

ENGINE v7 (GOAL-SCREEN-OBJECTIVE-ERASURE-001, GOAL-SCREEN-HOLDOUT-LEAKAGE-001,
GOAL-SCREEN-FEASIBLE-SET-PROOF-001; CIO-Entscheid 2026-10-18 nach Codex-
Review docs/audits/2026-10-18-core-optimizer-pr631-reachability-and-
validation-review.md): der Screen ist REINE OFFENLEGUNG.

* Herabstufung statt Ausnahme (GOAL-HIERARCHY-002, CIO-Review #650): ein
  im Default-Modus nicht gefundenes Ziel (obere Grenze < tau/2) gehoert
  unabhaengig vom Haertegrad nicht zur Stufe 1 der Zielhierarchie
  (``solver._stage1_liabilities``) -- es verdraengt keine erreichbaren Ziele,
  bleibt aber mit vollem Fehlbetrag in der Zielfunktion.
* Kein Ziel wird mehr aus Fehlbetrag oder Chance-Strafe genommen
  (``penalty_exempt_goal_ids`` ist immer leer; das Feld bleibt nur fuer die
  Auditstruktur). Ein Ziel, das seine Schwelle nie erreicht, unterscheidet
  trotzdem zwischen viel und wenig Fehlbetrag (CHF 0 vs. CHF 900 gegen
  CHF 1000) -- und harte/primaere Ziele sind in der Zielhierarchie
  geschuetzt (``objective.protected_goal_level``).
* Eigener Screening-Wuerfel (``SCREENING_SEED_OFFSET``), nie der
  Validierungswuerfel, der spaeter den Gewinner zertifiziert und gegen die
  Hausmatrix testet.
* Die Pruefmenge ist endlich und beweist keine Unerreichbarkeit: der Status
  heisst ``not_found_reachable_in_screen_set``, nicht "unerreichbar".

Historischer Text (v3, bis Engine v6):

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
Chance-Strafe (``_goal_probability_core`` auf dem priorisierten Scope des
Ziels, direkter Replay seit Engine v10). Ein Ziel mit
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
* Risikomass-Varianten (``max_drawdown``, ``min_volatility``,
  ``cvar_return``, ``max_return``; CIO-Entscheid b, 2026-10-18): dort
  steuern nur Ziele, deren Schwelle tau auf mindestens einer zulaessigen
  Allokation erreichbar ist (``max UB_95 >= tau``). Die Variante verspricht
  ein Risikomass; sie darf nicht fuer ein ohnehin nicht absicherbares Ziel
  Risiko aufbauen (gemessen: Fundament ``min_volatility`` 73.7 % Aktien,
  mehr als Default und Hausmatrix, solange die Einkommensbruecke mit max
  ~54 % gegen tau 80 % steuerte). Teilweise erreichbare Ziele werden mit
  eigenem Beraterhinweis offengelegt.
* Default: ein praktisch unerreichbares Ziel steuert weder die Chance-Strafe noch
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

GOAL_REACHABILITY_SCREEN_VERSION = "goal_reachability_screen_v6_local_search_no_auto_demotion"
GOAL_REACHABILITY_CERTIFICATE_VERSION = "max_smoothed_success_multistart_v2_local_only"
# Fortsetzung der logistischen Glaettung (Anteil des Zielwerts): breit zuerst
# (Gradient auch weit vom Ziel), zuletzt die Stufe-1-Breite.
CERTIFICATE_WIDTHS = (0.25, 0.05, 0.02)
CERTIFICATE_MAX_ITER = 40
# Engine v11: ein lokaler Such-Miss ist KEIN Unerreichbarkeitsnachweis.
CERTIFICATE_STATUS_NOT_FOUND = "not_found_reachable_locally"
CERTIFICATE_STATUS_REACHABLE = "reachable"
CERTIFICATE_STATUS_UNAVAILABLE = "global_certificate_unavailable"
# Ein globales Zertifikat (oberer Bound + Gap ueber die ganze zulaessige
# Menge) existiert nicht; jede Zeile traegt das ausdruecklich.
GLOBAL_CERTIFICATE_STATUS = "unavailable_local_search_only"
# Seed-Offset des Screening-Wuerfels (Primzahl, verschieden vom
# Validierungs-Offset ``solver.VALIDATION_SEED_OFFSET = 1_000_003``).
SCREENING_SEED_OFFSET = 2_000_003
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


def _build_screening_context(context):
    """Eigener Screening-Wuerfel (gleiche Verteilung, eigener Seed).

    GOAL-SCREEN-HOLDOUT-LEAKAGE-001: der Validierungswuerfel
    (``solver._build_validation_context``) bleibt bis zum Freeze des
    Gewinners unberuehrt. None ohne ScenarioInputs oder bei
    fehlgeschlagenem Wuerfel.
    """
    import hashlib
    from dataclasses import replace

    from services.return_moments import ReturnMomentError

    from .scenario_cache import scenario_inputs_digest
    from .scenario_engine import build_scenario_paths

    inputs = getattr(context, "scenario_inputs", None)
    if inputs is None:
        return None
    screening_seed = int(context.seed) + SCREENING_SEED_OFFSET
    scenario_horizon = int(
        getattr(context, "scenario_horizon_years", None) or context.horizon_years
    )
    try:
        paths = build_scenario_paths(
            inputs,
            horizon_years=scenario_horizon,
            n_paths=int(context.n_paths),
            seed=screening_seed,
            antithetic=True,
        )
    except (ReturnMomentError, ValueError):
        return None
    paths = paths[:, : int(context.horizon_years), :]
    screening_context = replace(context, return_paths=paths, scenario_weights=None)
    cube_hash = hashlib.sha256(
        "|".join([
            scenario_inputs_digest(inputs),
            str(scenario_horizon),
            str(int(context.n_paths)),
            str(screening_seed),
            "antithetic=True",
            "screening",
        ]).encode("utf-8")
    ).hexdigest()
    return screening_context, screening_seed, cube_hash


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


def _weighted_mean(values: np.ndarray, weights: np.ndarray | None) -> float:
    if values.size == 0:
        return 0.0
    if weights is None:
        return float(np.mean(values))
    return float(np.sum(values * weights) / np.sum(weights))


def _feasible_set_center(candidates: list[np.ndarray], context) -> np.ndarray | None:
    """Zentrum der zulaessigen Menge: Mittel der (zulaessigen) Kandidaten.

    Bandbreiten, Summe = 1 und Risikobudget sind konvex -- das Mittel
    zulaessiger Punkte ist zulaessig; geprueft wird trotzdem (und notfalls
    projiziert), sobald die Menge bekannt ist."""
    if not candidates:
        return None
    center = np.mean(np.vstack([np.asarray(c, dtype=np.float64) for c in candidates]), axis=0)
    bounds = getattr(context, "bounds", None)
    if bounds is None:
        return center
    from . import solver as _solver
    from .constraints import is_feasible

    ok, _violations = is_feasible(
        center, bounds=bounds, constraints=getattr(context, "scipy_constraints", None) or [],
    )
    if ok:
        return center
    return _solver._project_onto_feasible_set(center, context)


def certify_goal_reachability(
    context,
    screening_context,
    goal,
    candidates: list[np.ndarray],
    *,
    tau: float,
    cube_hash: str,
) -> dict:
    """GOAL-REACHABILITY-CERTIFICATE-001: ``max_w p_g(w)`` ueber die zulaessige Menge.

    Multi-Start von allen Screen-Kandidaten und vom Zentrum der zulaessigen
    Menge; je Start SLSQP auf ``-log p_glatt`` mit abnehmender
    Glaettungsbreite (``CERTIFICATE_WIDTHS``), dieselben Bandbreiten und
    Nebenbedingungen wie der Solver. Bewertet wird an JEDEM zulaessigen
    ausgewerteten Punkt mit dem exakten Erfolgsindikator auf dem
    Screening-Wuerfel; massgeblich ist der beste Punkt. Abbruch, sobald eine
    obere Grenze ``>= tau/2`` gefunden ist (das Ziel ist dann erreichbar).
    """
    from scipy.optimize import minimize

    from . import solver as _solver
    from .certification import effective_sample_size
    from .constraints import is_feasible
    from .objective import _goal_probability_core, _success_margin_per_path

    threshold = UNREACHABLE_TAU_FRACTION * float(tau)
    weights = getattr(screening_context, "scenario_weights", None)
    if weights is not None:
        weights = np.asarray(weights, dtype=np.float64).reshape(-1)
    n_paths = int(screening_context.n_paths)
    n_eff = float(effective_sample_size(weights)) if weights is not None else float(n_paths)
    initial = screening_context.advisory_wealth_rappen
    bounds = getattr(context, "bounds", None)
    constraints = getattr(context, "scipy_constraints", None) or []
    state = {
        "max_probability": 0.0, "best_w": None, "n_evaluations": 0,
    }

    from .priority_scope import _scope_differs

    scoped_goal = _scope_differs(goal)

    def evaluate(w: np.ndarray, *, feasible: bool) -> np.ndarray | None:
        wealth = _solver._simulate_context_wealth(screening_context, w)
        if scoped_goal:
            # Engine v10: das Ziel auf seinem priorisierten Scope (direkter
            # Replay), derselbe Pfad wie Zielfunktion und Publikation.
            wealth = _solver._context_scope_wealth(
                screening_context, w, wealth,
            ).for_goal(goal)
        annualized = _solver._annualized_twr_bps_per_path(screening_context, w)
        state["n_evaluations"] += 1
        if feasible:
            success = np.asarray(_goal_probability_core(
                wealth, goal, initial, annualized_return_bps_per_path=annualized,
            ), dtype=np.float64)
            probability = _weighted_mean(success, weights)
            if state["best_w"] is None or probability > state["max_probability"]:
                state["max_probability"] = probability
                state["best_w"] = np.asarray(w, dtype=np.float64).copy()
        return _success_margin_per_path(goal, wealth, initial, annualized)

    def reached() -> bool:
        return wilson_upper_bound(state["max_probability"], n_eff) >= threshold

    center = _feasible_set_center(candidates, context)
    starts = ([center] if center is not None else []) + [
        np.asarray(c, dtype=np.float64) for c in candidates
    ]
    status = None
    n_local_solves = 0
    solver_status: dict[str, int] = {"success": 0, "failure": 0, "non_finite": 0}
    for x0 in starts:
        evaluate(x0, feasible=True)  # Kandidaten/Zentrum sind zulaessig
        if reached():
            status = CERTIFICATE_STATUS_REACHABLE
            break
    if status is None and bounds is None:
        status = CERTIFICATE_STATUS_UNAVAILABLE
    if status is None:
        def is_ok(w: np.ndarray) -> bool:
            return bool(is_feasible(w, bounds=bounds, constraints=constraints)[0])

        for x0 in starts:
            x = np.asarray(x0, dtype=np.float64)
            for width in CERTIFICATE_WIDTHS:

                def negative_log_smooth(w, _width=width):
                    w = np.asarray(w, dtype=np.float64)
                    margin = evaluate(w, feasible=is_ok(w))
                    if margin is None:
                        return 0.0
                    # log sigmoid(m / b), numerisch stabil
                    smooth = -np.logaddexp(0.0, -np.asarray(margin) / _width)
                    if weights is None:
                        log_mean = float(np.logaddexp.reduce(smooth) - np.log(smooth.size))
                    else:
                        log_mean = float(
                            np.logaddexp.reduce(smooth + np.log(weights))
                            - np.log(np.sum(weights))
                        )
                    return -log_mean

                result = minimize(
                    negative_log_smooth, x0=x, method="SLSQP", bounds=bounds,
                    constraints=constraints,
                    options={"maxiter": CERTIFICATE_MAX_ITER, "ftol": 1e-9, "disp": False},
                )
                n_local_solves += 1
                solver_status["success" if bool(getattr(result, "success", False)) else "failure"] += 1
                raw = getattr(result, "x", None)
                if raw is None or not np.all(np.isfinite(raw)):
                    solver_status["non_finite"] += 1
                elif is_ok(np.asarray(raw)):
                    x = np.asarray(raw, dtype=np.float64)
                    evaluate(x, feasible=True)
                if reached():
                    status = CERTIFICATE_STATUS_REACHABLE
                    break
            if status is not None:
                break
        if status is None:
            # Engine v11: lokal nicht gefunden -- kein Beweis, keine Wirkung.
            status = CERTIFICATE_STATUS_NOT_FOUND
    best = state["best_w"]
    return {
        "version": GOAL_REACHABILITY_CERTIFICATE_VERSION,
        "status": status,
        "global_certificate": GLOBAL_CERTIFICATE_STATUS,
        "solver_status_counts": dict(solver_status),
        "max_probability": float(state["max_probability"]),
        # Stichproben-Unsicherheit am besten gefundenen Punkt, KEIN
        # Optimierungs-Bound ueber die zulaessige Menge (Codex 5.2.4).
        "max_upper_bound": float(wilson_upper_bound(state["max_probability"], n_eff)),
        "upper_bound_kind": "sampling_wilson_at_best_found_point",
        "threshold": float(threshold),
        "n_eff": float(n_eff),
        "best_bps": (
            None if best is None else [int(round(x * 10000.0)) for x in best]
        ),
        "n_starts": len(starts),
        "n_local_solves": int(n_local_solves),
        "n_evaluations": int(state["n_evaluations"]),
        "widths": list(CERTIFICATE_WIDTHS),
        "screening_cube_hash": cube_hash,
    }


def goal_reachability_screen(context) -> dict | None:
    """Fuehrt die Pruefung aus. None ohne pruefbare Ziele oder Validierungswuerfel."""
    from . import solver as _solver
    from .objective import _default_tau_x100, _goal_probability_core
    from .objective_contract import objective_contract_of
    from .objective_variants import OBJECTIVE_GOAL_SHORTFALL

    goals = _screened_goals(context, int(context.horizon_years) + 1)
    if not goals:
        return None
    screening = _build_screening_context(context)
    if screening is None:
        return None
    validation_context, validation_seed, cube_hash = screening
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
            "tau_reachable": False,
        }
        for goal in goals
    }
    mode = objective_contract_of(context).objective_mode
    risk_variant = mode != OBJECTIVE_GOAL_SHORTFALL
    from .priority_scope import _scope_differs, scope_wealth_for

    any_scoped = any(_scope_differs(goal) for goal in validation_context.liabilities)
    evaluated = 0
    for w in candidates:
        # Default: Entscheid an tau/2 genuegt. Risikomass-Variante: ein Ziel
        # ist erst entschieden, wenn tau selbst erreicht ist.
        open_ids = [
            gid for gid, row in state.items()
            if not (row["tau_reachable"] if risk_variant else row["reachable"])
        ]
        if not open_ids:
            break
        evaluated += 1
        wealth = _solver._simulate_context_wealth(validation_context, w)
        # Engine v10: jedes Ziel auf seinem priorisierten Scope (direkter
        # Replay, nur wenn ein Scope vom gemeinsamen Pfad abweicht).
        scopes = (
            _solver._context_scope_wealth(validation_context, w, wealth)
            if any_scoped
            else scope_wealth_for(wealth, validation_context.liabilities, None)
        )
        annualized = _solver._annualized_twr_bps_per_path(validation_context, w)
        for gid in open_ids:
            row = state[gid]
            success = _goal_probability_core(
                scopes.for_goal(row["goal"]),
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
            if upper >= row["tau"]:
                row["tau_reachable"] = True

    unreachable = sorted(gid for gid, row in state.items() if not row["reachable"])
    # Engine v9: fuer Ziele, die der guenstige Screen nicht an tau/2 findet,
    # die lokale Suche ueber die zulaessige Menge. Engine v11
    # (GOAL-REVISION-DECISION-001): ihr Miss ist nur ein Vorschlag an den
    # Berater (``revision_suggested_goal_ids``), nie eine Herabstufung.
    for gid in unreachable:
        row = state[gid]
        row["certificate"] = certify_goal_reachability(
            context, validation_context, row["goal"], candidates,
            tau=row["tau"], cube_hash=cube_hash,
        )
    revision_suggested = sorted(
        gid for gid in unreachable
        if state[gid]["certificate"]["status"] != CERTIFICATE_STATUS_REACHABLE
    )
    # Herabgestuft ist nur, was eine gueltige GoalRevisionDecisionV1 traegt
    # (``goal_revision_decision.apply_to_liabilities`` markiert die Liability).
    decided = {
        str(liab.goal_id): liab for liab in context.liabilities
        if getattr(liab, "demoted", False)
    }
    # Engine v7: reine Offenlegung -- in KEINEM Modus wird ein Ziel aus
    # Zielfunktion oder Strafe genommen. "not_found_reachable_in_screen_set"
    # heisst: auf der endlichen Pruefmenge nicht gefunden, kein Beweis.
    not_tau_reachable = sorted(
        gid for gid, row in state.items() if not row["tau_reachable"]
    )
    flagged = set(not_tau_reachable if risk_variant else unreachable)
    return {
        "version": GOAL_REACHABILITY_SCREEN_VERSION,
        "role": "advisory_disclosure_only",
        "objective_mode": mode,
        "screening_seed": int(validation_seed),
        "screening_cube_hash": cube_hash,
        "screening_n_paths": n_paths,
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
                # In der Default-Variante wird tau nur bis zum Entscheid an
                # tau/2 verfolgt; None = nicht abschliessend geprueft.
                "tau_reachable": (
                    bool(row["tau_reachable"])
                    if risk_variant or row["tau_reachable"] or not row["reachable"]
                    else None
                ),
                "status": (
                    "not_found_reachable_in_screen_set"
                    if gid in flagged
                    else "found_reachable_in_screen_set"
                ),
                "penalty_exempt": False,
                # Engine v9: lokale Suche (nur fuer Screen-Misses an tau/2).
                "certificate": row.get("certificate"),
                # Engine v11: nie zertifiziert unerreichbar (kein globaler
                # Nachweis); ein Miss ist nur ein Vorschlag an den Berater.
                "certified_unreachable": False,
                "revision_suggested": gid in revision_suggested,
                "demoted_by_decision": gid in decided,
                "revision_decision_id": getattr(decided.get(gid), "revision_decision_id", None),
                "revision_decision_hash": getattr(decided.get(gid), "revision_decision_hash", None),
                "goal_snapshot_hash": getattr(row["goal"], "goal_snapshot_hash", None),
            }
            for gid, row in state.items()
        ],
        # Historischer Name: Ziele, die auf der Pruefmenge nicht einmal tau/2
        # erreichen (keine Aussage ueber den ganzen zulaessigen Raum).
        "unreachable_goal_ids": unreachable,
        "not_found_reachable_goal_ids": sorted(flagged),
        # Engine v11 (GOAL-REVISION-DECISION-001): keine automatische
        # Herabstufung. Operativ wirkt nur die Berater-Entscheidung
        # (``demoted_goal_ids`` = Ziele mit gueltiger GoalRevisionDecisionV1);
        # ein lokaler Such-Miss ist ein Vorschlag.
        "certificate_version": GOAL_REACHABILITY_CERTIFICATE_VERSION,
        "global_certificate": GLOBAL_CERTIFICATE_STATUS,
        "certified_unreachable_goal_ids": [],
        "revision_suggested_goal_ids": revision_suggested,
        "demoted_goal_ids": sorted(decided),
        # Immer leer seit v4 (Engine v7): kein Ziel wird ausgenommen.
        "penalty_exempt_goal_ids": [],
    }


def _best_found(row: dict) -> float:
    certificate = row.get("certificate") or {}
    return max(
        float(row.get("max_probability") or 0.0),
        float(certificate.get("max_probability") or 0.0),
    )


def reachability_reasoning(screen: dict | None) -> list[str]:
    """Beraterhinweis je Ziel, das lokal nicht mit ausreichender Sicherheit
    gefunden wurde oder per Berater-Entscheid nachrangig ist.

    Engine v11 (GOAL-REVISION-DECISION-001): keine Unmoeglichkeits- oder
    Garantieaussage. Ein lokal nicht gefundenes Ziel bleibt mit seinem
    Haertegrad geschuetzt; der Hinweis schlaegt die Einstufung als
    nachrangiges Wunschziel nur VOR (Berater-Entscheid mit Begruendung).
    """
    if not screen:
        return []
    lines = []
    for row in screen.get("goals") or ():
        label = repr(str(row["label"]))
        if row.get("demoted_by_decision"):
            reference = str(row.get("revision_decision_id") or "")
            digest = str(row.get("revision_decision_hash") or "")[:12]
            lines.append(
                "Beraterhinweis: Ziel " + label + " ist per Beraterentscheid"
                + (f" ({reference}, SHA-256 {digest})" if reference else "")
                + " als nachrangiges Wunschziel eingestuft; es wird als "
                "nachrangiges Wunschziel verfolgt und verdraengt keine "
                "erreichbaren Ziele. Eine Aenderung des Ziels hebt die "
                "Einstufung auf. Ziel mit dem Kunden ueberpruefen (Betrag, "
                "Termin, Prioritaet)."
            )
            continue
        if row.get("status") != "not_found_reachable_in_screen_set":
            continue
        figures = (
            f"beste gefundene Allokation {100.0 * _best_found(row):.1f} %, gefordert "
            f"{100.0 * float(row['tau']):.0f} %"
        )
        if row.get("revision_suggested"):
            lines.append(
                "Beraterhinweis: Ziel " + label + " wird mit den geprueften "
                "Allokationen nicht mit ausreichender Sicherheit erreicht ("
                + figures + "). Es bleibt mit seinem Haertegrad vorrangig "
                "geschuetzt. Ziel mit dem Kunden ueberpruefen (Betrag, Termin, "
                "Prioritaet) oder als nachrangiges Wunschziel einstufen "
                "(Begruendung erforderlich)."
            )
        elif screen.get("objective_mode") == "goal_shortfall":
            # Von der lokalen Suche erreichbar gefunden: normal verfolgt.
            continue
        else:
            lines.append(
                "Beraterhinweis: Ziel " + label + " erreichte in "
                "der Risikovariante (" + str(screen.get("objective_mode")) + ") auf "
                "keiner der geprueften zulaessigen Allokationen die geforderte "
                "Sicherheit (" + figures + "). Ziel mit dem Kunden ueberpruefen "
                "(Betrag, Termin, Prioritaet); es bleibt Teil der Zielfunktion."
            )
    return lines


def _revision_evidence(row: dict, screen: dict) -> dict:
    """GOAL-REVISION-DECISION-001: Engine-Evidenz je gepruefter Zielzeile
    (Grundlage einer spaeteren GoalRevisionDecisionV1)."""
    from .solver import OPTIMIZER_ENGINE_VERSION

    certificate = row.get("certificate") or {}
    if row.get("reachable"):
        status = "found_reachable_in_screen_set"
    else:
        status = certificate.get("status") or CERTIFICATE_STATUS_UNAVAILABLE
    upper = max(
        float(row.get("max_upper_bound") or 0.0),
        float(certificate.get("max_upper_bound") or 0.0),
    )
    return {
        "status": status,
        "revision_suggested": bool(row.get("revision_suggested")),
        "demoted_by_decision": bool(row.get("demoted_by_decision")),
        "revision_decision_id": row.get("revision_decision_id"),
        "revision_decision_hash": row.get("revision_decision_hash"),
        "best_probability": _best_found(row),
        "wilson_upper_bound": upper,
        "upper_bound_kind": "sampling_wilson_at_best_found_point",
        "tau": float(row.get("tau") or 0.0),
        "threshold": UNREACHABLE_TAU_FRACTION * float(row.get("tau") or 0.0),
        "global_certificate": GLOBAL_CERTIFICATE_STATUS,
        "screening_cube_hash": screen.get("screening_cube_hash"),
        "goal_snapshot_hash": row.get("goal_snapshot_hash"),
        "engine_version": OPTIMIZER_ENGINE_VERSION,
        "policy": screen.get("version"),
    }


def annotate_rows(rows, screen: dict | None) -> list[dict]:
    """Setzt auf jeder GEPRUEFTEN Zielzeile ``feasible_set_reachable`` und
    (Engine v11) ``goal_revision`` (Evidenz + Vorschlag).

    ``feasible_set_reachable`` (bool, Vertrag seit Engine v7/v9): True =
    eine zulaessige Allokation mit ausreichender Sicherheit (obere Grenze >=
    tau/2) gefunden -- im Screen oder von der lokalen Suche; False = nicht
    gefunden. False ist eine Offenlegung, KEIN Unerreichbarkeitsnachweis
    (Engine v11): der ehrliche Status steht in ``goal_revision.status``."""
    screen = screen or {}
    by_goal = {str(row["goal_id"]): row for row in (screen.get("goals") or ())}
    out = []
    for row in rows:
        row = dict(row)
        goal_id = row.get("goal_id")
        # Nur gepruefte Ziele (Untergrenze, im Horizont) bekommen die Felder;
        # alle anderen Zeilen bleiben unveraendert.
        screened = by_goal.get(str(goal_id)) if goal_id is not None else None
        if screened is not None:
            found = bool(screened["reachable"]) or (
                (screened.get("certificate") or {}).get("status")
                == CERTIFICATE_STATUS_REACHABLE
            )
            row["feasible_set_reachable"] = bool(found)
            row["goal_revision"] = _revision_evidence(screened, screen)
        out.append(row)
    return out
