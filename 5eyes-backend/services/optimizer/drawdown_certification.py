"""Drawdown-Zertifizierung auf dem unabhaengigen Validierungs-Cube.

OPTIMIZER-DRAWDOWN-CERTIFICATION-001 (Owner-Entscheid 2026-10-14)
================================================================

**Befund.** Der Modus ``max_drawdown`` optimiert auf dem Jahresgitter
(``objective_variants._annual_grid_max_drawdowns``), weil die
Brueckenverfeinerung (DRAWDOWN-TIME-GRID-001, ``drawdown_refinement``) in jeder
SLSQP-Iteration unbezahlbar waere. Das Jahresgitter unterschaetzt den
Drawdown volatilitaetsabhaengig und bevorzugt als Zielfunktion damit
riskantere Allokationen. Die bisherige Nachrechnung
(``refined_drawdown_check_for_winner`` in ``run_solver``) hatte zwei Luecken:

1. Sie lief auf dem TRAININGS-Cube -- demselben, auf dem selektiert wurde.
   Eine darauf gemessene Zahl ist nicht selektionsfrei (Winner's Curse, siehe
   OPTIMIZER-POST-SELECTION-CERTIFICATION-001).
2. Sie lief nur fuer den GEWINNER und war reine Anzeige. Ob die
   Proxy-Verzerrung die ENTSCHEIDUNG bewegt hat, liess sich so nicht
   beantworten -- dafuer muss man die Alternativen auf dem genauen Mass kennen.

**Verfahren (Drawdown-Rerank).** Alle zulaessigen Multi-Start-Finalisten
werden in ihrer gerundeten bps-Form (genau der Allokation, die publiziert
wuerde) auf dem unabhaengigen Validierungs-Cube
(``solver._build_validation_context``, derselbe Cube wie die
Zielerreichungs-Nachzertifizierung) bewertet:

    validiertes Objective = verfeinerter mittlerer Max-Drawdown
                          + Chance-Penalty
                          + Soft-Preference-Strafe (falls aktiv)

Das ist exakt die Zielfunktion des Modus ``max_drawdown``
(``combined_objective_two_phase``: Primaerterm + Chance-Penalty, kein
Vol-Term in den Varianten; ``_objective_from_array``: + Soft-Preference), nur
mit dem genauen Mass statt des Jahresgitter-Proxy und auf selektionsfreien,
ungewichteten Pfaden. Gewinner ist das Minimum; numerischer Gleichstand
(relative Toleranz ``1e-12``) entscheidet die Trainingsreihenfolge. Alles ist
deterministisch: der Validierungs-Cube und der Brueckenstrom sind aus dem
Lauf-Seed abgeleitet.

Der Audit-Eintrag haelt fest, ob die Rangfolge und ob der Gewinner sich
geaendert haben -- also ob die Proxy-Verzerrung die Entscheidung bewegt hat.

Dieses Modul haelt die Logik bewusst ausserhalb von ``solver.py``: der Solver
ruft nur ``certify_drawdown_candidates`` und
``drawdown_certification_reasoning`` auf. Solver-Interna werden lazy
importiert (kein Zirkularimport).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

DRAWDOWN_CERTIFICATION_VERSION = "validation_cube_refined_rerank_v1"

_TIE_REL_TOL = 1e-12


def rerank_by_validated_objective(entries: Sequence[dict]) -> dict:
    """Rangfolge vor und nach der Validierung.

    ``entries`` in Trainingsreihenfolge (Index 0 = Trainingsgewinner) mit
    ``validated_objective``. Liefert Indizes in ``entries``:

    * ``training_order``: 0..n-1 (gegeben).
    * ``validated_order``: aufsteigend nach validiertem Objective, Gleichstand
      nach Trainingsposition.
    * ``validated_winner_index``, ``winner_changed``, ``ranking_changed``.
    """
    n = len(entries)
    if n == 0:
        raise ValueError("Keine Kandidaten fuer die Drawdown-Zertifizierung.")
    values = [float(entry["validated_objective"]) for entry in entries]
    if not all(np.isfinite(values)):
        raise ValueError("Validiertes Objective ist nicht endlich.")
    floor = min(values)
    tol = max(abs(floor) * _TIE_REL_TOL, 1e-15)
    # Werte innerhalb der Toleranz gelten als gleich; damit entscheidet bei
    # numerischem Gleichstand die Trainingsreihenfolge, nicht Rundungsrauschen.
    quantized = [round((value - floor) / tol) for value in values]
    validated_order = sorted(range(n), key=lambda index: (quantized[index], index))
    training_order = list(range(n))
    winner = validated_order[0]
    return {
        "training_order": training_order,
        "validated_order": validated_order,
        "validated_winner_index": winner,
        "winner_changed": winner != 0,
        "ranking_changed": validated_order != training_order,
    }


def validated_drawdown_evaluation(
    validation_context,
    weights_array: np.ndarray,
    *,
    validation_seed: int,
) -> dict[str, float]:
    """Objective des Modus max_drawdown mit GENAUEM Mass auf dem Validierungs-Cube.

    Verfeinerter Drawdown (Brownsche Bruecke, Bruecken-Seed = Validierungs-
    Seed) + dieselbe Chance-Penalty + dieselbe Soft-Preference-Strafe wie im
    Training. Ungewichtet: der Validierungs-Cube hat kein Importance Sampling.
    """
    from . import solver as _solver
    from .allocation_intent import preference_loss_from_array
    from .objective import chance_constraint_penalty
    from .objective_variants import refined_drawdown_check_for_winner

    factors = _solver._portfolio_return_factors(validation_context, weights_array)
    drawdown = refined_drawdown_check_for_winner(
        factors, seed=int(validation_seed), weights=None,
    )
    wealth = _solver._simulate_context_wealth(validation_context, weights_array)
    chance, _rows = chance_constraint_penalty(
        wealth,
        validation_context.liabilities,
        int(validation_context.advisory_wealth_rappen),
        weights=None,
        annualized_return_bps_per_path=_solver._annualized_twr_bps_per_path(
            validation_context, weights_array, portfolio_factors=factors,
        ),
    )
    preference = 0.0
    if validation_context.preferred_target_bps:
        preference = float(preference_loss_from_array(
            weights_array,
            validation_context.preferred_target_bps,
            lam=validation_context.preference_penalty_lambda,
        ))
    refined = float(drawdown["refined_mean_drawdown"])
    return {
        "refined_mean_drawdown": refined,
        "annual_grid_mean_drawdown": float(drawdown["annual_grid_mean_drawdown"]),
        "chance_penalty": float(chance),
        "preference_penalty": preference,
        "validated_objective": refined + float(chance) + preference,
        "sub_steps_per_year": int(drawdown["sub_steps_per_year"]),
        "model_version": str(drawdown["model_version"]),
    }


def _not_certified(reason: str) -> dict:
    return {
        "version": DRAWDOWN_CERTIFICATION_VERSION,
        "objective_mode": "max_drawdown",
        "certified": False,
        "reason": reason,
        "validation_seed": None,
        "ranking_changed": None,
        "winner_changed": False,
    }


def certify_drawdown_candidates(
    context,
    *,
    winner_weights: np.ndarray,
    candidates: Sequence[dict],
) -> tuple[np.ndarray | None, dict]:
    """Drawdown-Rerank ALLER zulaessigen Finalisten auf dem Validierungs-Cube.

    ``winner_weights`` ist der auf dem Trainings-Cube (Jahresgitter-Proxy)
    gewaehlte Gewinner, ``candidates`` die zulaessigen Multi-Start-Finalisten
    (Dicts mit ``weights`` und ``source``). Bewertet wird die GERUNDETE
    bps-Allokation; nach dem Runden unzulaessige Kandidaten scheiden aus,
    gleiche bps-Allokationen werden zusammengefasst.

    Returns ``(gewichte, audit)``. ``gewichte`` ist die gerundete Allokation
    des validierten Gewinners -- oder None, wenn nicht zertifiziert werden
    konnte; dann bleibt der Trainingsgewinner und ``audit["reason"]`` sagt
    warum.
    """
    from . import solver as _solver
    from .constraints import is_feasible
    from .scenario_engine import BUCKET_ORDER

    validation = _solver._build_validation_context(context)
    if validation is None:
        return None, _not_certified("no_independent_validation_cube")
    validation_context, validation_seed, cube_hash = validation

    pool: list[tuple[str, np.ndarray]] = [
        ("training_winner", np.asarray(winner_weights, dtype=np.float64)),
    ]
    for index, candidate in enumerate(candidates):
        pool.append((
            f"{candidate.get('source', 'candidate')}#{index + 1}",
            np.asarray(candidate["weights"], dtype=np.float64),
        ))

    entries: list[dict] = []
    seen: set[tuple[int, ...]] = set()
    skipped_infeasible = 0
    for label, raw_weights in pool:
        normalized = _solver._normalize_to_bounds(
            np.clip(raw_weights, 0.0, 1.0), context.bounds,
        )
        bps = _solver._weights_to_bps_dict(normalized, bounds=context.bounds)
        key = tuple(int(bps.get(bucket, 0)) for bucket in BUCKET_ORDER)
        if key in seen:
            continue
        seen.add(key)
        rounded = _solver._trusted_weights_bps_to_array(bps)
        feasible, _violations = is_feasible(
            rounded, bounds=context.bounds, constraints=context.scipy_constraints,
        )
        if not feasible:
            if label == "training_winner":
                # Ohne publizierbaren Trainingsgewinner gibt es nichts zu
                # vergleichen; der Lauf wird ohnehin als
                # `diverged_infeasible` markiert.
                return None, _not_certified("training_winner_infeasible_after_rounding")
            skipped_infeasible += 1
            continue
        evaluation = validated_drawdown_evaluation(
            validation_context, rounded, validation_seed=validation_seed,
        )
        entries.append({
            "label": label,
            "weights_bps": dict(bps),
            "training_objective": float(_solver._objective_from_array(context, rounded)),
            **evaluation,
            "_rounded_weights": rounded,
        })

    # Trainingsreihenfolge: Gewinner zuerst, dann nach Trainings-Objective
    # (stabil, gleiche Werte behalten die Startreihenfolge).
    head, rest = entries[:1], entries[1:]
    rest.sort(key=lambda entry: entry["training_objective"])
    ordered = head + rest
    outcome = rerank_by_validated_objective(ordered)
    winner = ordered[outcome["validated_winner_index"]]
    validated_rank = {
        position: rank for rank, position in enumerate(outcome["validated_order"])
    }
    audit = {
        "version": DRAWDOWN_CERTIFICATION_VERSION,
        "objective_mode": "max_drawdown",
        "certified": True,
        "reason": "validation_cube_rerank",
        "validation_seed": int(validation_seed),
        "validation_cube_hash": cube_hash,
        "validation_n_paths": int(validation_context.n_paths),
        "sub_steps_per_year": int(winner["sub_steps_per_year"]),
        "model_version": str(winner["model_version"]),
        "n_candidates": len(ordered),
        "n_candidates_infeasible_after_rounding": int(skipped_infeasible),
        "ranking_changed": bool(outcome["ranking_changed"]),
        "winner_changed": bool(outcome["winner_changed"]),
        "training_winner_weights_bps": dict(ordered[0]["weights_bps"]),
        "validated_winner_weights_bps": dict(winner["weights_bps"]),
        "validated_order": [int(i) for i in outcome["validated_order"]],
        "candidates": [
            {
                key: value
                for key, value in entry.items()
                if not key.startswith("_")
                and key not in ("sub_steps_per_year", "model_version")
            }
            | {"training_rank": position, "validated_rank": validated_rank[position]}
            for position, entry in enumerate(ordered)
        ],
    }
    return np.asarray(winner["_rounded_weights"], dtype=np.float64), audit


def drawdown_certification_reasoning(
    audit: dict,
    *,
    training_cube_check: dict | None = None,
) -> list[str]:
    """Audit-Trail-Zeilen zur Drawdown-Zertifizierung (deutsch, persistiert).

    ``training_cube_check`` (Ergebnis von ``refined_drawdown_check_for_winner``
    auf dem Trainings-Cube) wird nur verwendet, wenn nicht zertifiziert werden
    konnte -- dann bleibt wenigstens die bisherige Offenlegung der
    Proxy-Verzerrung des Gewinners erhalten, ausdruecklich als NICHT
    selektionsfrei gekennzeichnet.
    """
    if not audit.get("certified"):
        lines = [
            "Zielfunktion max_drawdown: optimiert auf dem Jahresgitter (Proxy). "
            "Die Auswahl ist NICHT auf dem verfeinerten Zeitgitter "
            f"zertifiziert (Grund: {audit.get('reason')})."
        ]
        if training_cube_check is not None:
            lines.append(
                "Nachrechnung des Gewinners auf dem Trainings-Cube (nicht "
                "selektionsfrei): "
                f"{training_cube_check['annual_grid_mean_drawdown'] * 100:.2f}% "
                "mittlerer Max-Drawdown auf dem Jahresgitter, "
                f"{training_cube_check['refined_mean_drawdown'] * 100:.2f}% auf dem "
                f"verfeinerten Zeitgitter ({training_cube_check['sub_steps_per_year']} "
                f"Teilschritte/Jahr, {training_cube_check['model_version']})."
            )
        return lines
    candidates = list(audit.get("candidates") or [])
    training = candidates[0] if candidates else {}
    winner = next(
        (c for c in candidates if c.get("validated_rank") == 0), training,
    )
    lines = [
        "Zielfunktion max_drawdown: optimiert auf dem Jahresgitter (Proxy). "
        f"Alle {audit.get('n_candidates')} zulaessigen Finalisten auf dem "
        "unabhaengigen Validierungs-Cube "
        f"(Seed {audit.get('validation_seed')}, {audit.get('validation_n_paths')} "
        "Pfade) mit verfeinertem Drawdown "
        f"({audit.get('sub_steps_per_year')} Teilschritte/Jahr, "
        f"{audit.get('model_version')}) neu bewertet und gerankt.",
        "Trainingsgewinner auf dem Validierungs-Cube: "
        f"{float(training.get('refined_mean_drawdown', 0.0)) * 100:.2f}% "
        "mittlerer Max-Drawdown verfeinert vs "
        f"{float(training.get('annual_grid_mean_drawdown', 0.0)) * 100:.2f}% "
        "auf dem Jahresgitter.",
    ]
    if audit.get("winner_changed"):
        lines.append(
            "Die Proxy-Verzerrung hat die Entscheidung BEWEGT: gewaehlt ist "
            "der validiert beste Kandidat "
            f"({float(winner.get('refined_mean_drawdown', 0.0)) * 100:.2f}% "
            "verfeinert) statt des Trainingsgewinners."
        )
    elif audit.get("ranking_changed"):
        lines.append(
            "Die Rangfolge der uebrigen Kandidaten hat sich verschoben, der "
            "Gewinner bleibt derselbe -- die Proxy-Verzerrung hat die "
            "Entscheidung nicht bewegt."
        )
    else:
        lines.append(
            "Rangfolge unveraendert -- die Proxy-Verzerrung hat die "
            "Entscheidung nicht bewegt."
        )
    return lines


__all__ = [
    "DRAWDOWN_CERTIFICATION_VERSION",
    "certify_drawdown_candidates",
    "drawdown_certification_reasoning",
    "rerank_by_validated_objective",
    "validated_drawdown_evaluation",
]
